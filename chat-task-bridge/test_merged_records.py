import gzip
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

from bridge import Bridge, BridgeError, load_json, write_json
from merged_records import MAX_DEPTH, MAX_ITEMS, MAX_TEXT, qq_card, render, wechat_record, xml
from qq_forward import fetch_record, parse_payload, parse_response
from qq_group_file import encode
from wechat_cdn import protobuf
from wechat_db_worker import read_record, record_digest, scoped_history


def wx_item(text="实验截止周五", typ="1", extra=""):
    return '<dataitem datatype="' + typ + '"><sourcename>同学甲</sourcename><sourcetime>2026-10-29 10:00</sourcetime><datadesc>' + escape(text) + '</datadesc>' + extra + '</dataitem>'


def wx_record(items, count=None):
    body = '<recordinfo><datalist' + (' count="' + str(count) + '"' if count is not None else '') + '>' + items + '</datalist></recordinfo>'
    return '<msg><appmsg><type>19</type><title>课程记录</title><recorditem><![CDATA[' + body + ']]></recorditem></appmsg></msg>'


def qq_body(elems=None, number=1):
    if elems is None:
        elems = [encode([(1, encode([(1, '实验截止周五'.encode())]))])]
    rich = encode([(2, e) for e in elems])
    msg = encode([(1, encode([(1, 42), (8, encode([(4, '同学甲'.encode())]))])),
                  (2, encode([(6, 1793239200)])), (3, encode([(1, rich)]))])
    return encode([(2, encode([(1, b'MultiMsg'), (2, encode([(1, msg)] * number))]))])


class RecordParserTests(unittest.TestCase):
    def test_wechat_cdata_text_and_sender(self):
        result = wechat_record('wxid_fixture:\n' + wx_record(wx_item()))
        self.assertTrue(result['complete'])
        self.assertEqual(result['messages'][0]['sender'], '同学甲')
        self.assertIn('实验截止周五', render(result))

    def test_escaped_record_and_direct_child_record(self):
        original = wx_record(wx_item())
        start = original.index('<![CDATA[')
        end = original.index(']]>')
        body = original[start + 9:end]
        for replacement in [escape(body), body]:
            result = wechat_record(original[:start] + replacement + original[end + 3:])
            self.assertEqual(len(result['messages']), 1)

    def test_nested_recordxml_body(self):
        nested = '<recordinfo><datalist>' + wx_item('嵌套作业') + '</datalist></recordinfo>'
        result = wechat_record(wx_record(wx_item(typ='17', extra='<recordxml>' + escape(nested) + '</recordxml>')))
        self.assertEqual([m['depth'] for m in result['messages']], [0, 1])
        self.assertIn('嵌套作业', render(result))

    def test_media_credentials_are_not_public_or_download_handles(self):
        extra = '<datatitle>图.jpg</datatitle><cdnattachurl>private-capability</cdnattachurl><aeskey>private-key</aeskey>'
        result = wechat_record(wx_record(wx_item('private-description', '2', extra)))
        serialized = json.dumps(result)
        for secret in ('private-capability', 'private-key', 'private-description'):
            self.assertNotIn(secret, serialized)
        self.assertEqual(result['messages'][0]['kind'], 'image')
        self.assertFalse(result['attachments_downloadable'])

    def test_non_record_cards_not_misclassified(self):
        self.assertIsNone(wechat_record('<msg><appmsg><type>6</type><title>f.zip</title></appmsg></msg>'))
        self.assertIsNone(wechat_record('plain'))

    def test_dtd_entities_and_large_xml_rejected(self):
        self.assertIsNone(xml('<!DOCTYPE x [<!ENTITY a "secret">]><x>&a;</x>'))
        self.assertIsNone(xml('x' * (2 * 1024**2 + 1)))

    def test_missing_invalid_and_count_mismatch_are_partial(self):
        for source in ['<msg><appmsg><type>19</type></appmsg></msg>', wx_record('', 5), wx_record(wx_item(), 2)]:
            self.assertFalse(wechat_record(source)['complete'])

    def test_message_and_text_budgets_mark_truncation(self):
        result = wechat_record(wx_record(wx_item('x') * (MAX_ITEMS + 1)))
        self.assertEqual(len(result['messages']), MAX_ITEMS)
        self.assertFalse(result['complete'])
        result = wechat_record(wx_record(wx_item('x' * (MAX_TEXT + 1))))
        self.assertEqual(len(result['messages'][0]['text']), MAX_TEXT)
        self.assertFalse(result['complete'])

    def test_nested_depth_bounded(self):
        body = '<recordinfo><datalist>' + wx_item() + '</datalist></recordinfo>'
        for _ in range(MAX_DEPTH + 2):
            body = '<recordinfo><datalist>' + wx_item(typ='17', extra='<recordxml>' + escape(body) + '</recordxml>') + '</datalist></recordinfo>'
        source = '<msg><appmsg><type>19</type><recorditem>' + escape(body) + '</recorditem></appmsg></msg>'
        self.assertIn('nesting_limit', wechat_record(source)['limitations'])

    def test_unknown_wechat_type_is_partial(self):
        self.assertFalse(wechat_record(wx_record(wx_item(typ='999')))['complete'])

    def test_qq_modern_and_legacy_card_detection(self):
        meta = {'app':'com.tencent.multimsg','meta':{'detail':{'resid':'private-id','news':[{'text':'预览'}],'summary':'2条'}}}
        card = qq_card([{'fwd_meta':json.dumps(meta)}])
        self.assertEqual(card['preview'], '预览')
        self.assertEqual(card['_resid'], 'private-id')
        card = qq_card([{'legacy_fwd_xml':'<msg m_resid="private-id"><item><title>预览</title></item></msg>'}])
        self.assertEqual(card['preview'], '预览')
        meta['app'] = 'com.tencent.other'
        self.assertIsNone(qq_card([{'fwd_meta':json.dumps(meta)}]))

    def test_qq_body_text_and_flags_without_credentials(self):
        elems = [encode([(37, b''), (9, b'')]), encode([(1, encode([(1, '实验要求'.encode())]))])]
        result = parse_payload(qq_body(elems), '记录')
        self.assertTrue(result['complete'])
        self.assertEqual(result['messages'][0]['text'], '实验要求')
        self.assertEqual(result['messages'][0]['sender'], '同学甲')

    def test_qq_reply_and_common_image(self):
        quote = encode([(5, encode([(1, encode([(1, b'quoted-text')]))]))])
        image = encode([(1,48),(2,b'private-key'),(3,20)])
        result = parse_payload(qq_body([encode([(45,quote)]),encode([(53,image)])]), '记录')
        self.assertIn('quoted-text', result['messages'][0]['text'])
        self.assertIn('[图片]', result['messages'][0]['text'])
        self.assertNotIn('private-key', json.dumps(result))

    def test_qq_unknown_nested_card_marks_partial_without_following_url(self):
        result = parse_payload(qq_body([encode([(51,b'https://untrusted.example/private')])]), '记录')
        self.assertFalse(result['complete'])
        self.assertNotIn('https://', json.dumps(result))

    def test_qq_response_source_and_compression_checked(self):
        response = protobuf(encode([(3,b'bound-id'),(4,gzip.compress(qq_body()))]))
        self.assertEqual(len(parse_response(response,'bound-id','title')['messages']),1)
        with self.assertRaises(BridgeError):
            parse_response(response,'other-id','title')
        for compressed in [gzip.compress(b'x' * (512 * 1024 + 1)), b'invalid', gzip.compress(qq_body())+b'tail']:
            with self.assertRaises(BridgeError):
                parse_response(protobuf(encode([(3,b'bound-id'),(4,compressed)])),'bound-id','title')

    def test_qq_cache_only_and_invalid_id_do_not_access_session(self):
        with patch('qq_forward.read_material') as session, patch('qq_forward.check_kernel') as kernel:
            for request in [{'settings':{'active_download':False}}, {'settings':{'active_download':True},'fetch_if_missing':False}, {'settings':{'active_download':True}}]:
                with self.assertRaises(BridgeError):
                    fetch_record({'_resid':None},request,{},None)
            session.assert_not_called()
            kernel.assert_not_called()

    def test_wechat_read_uses_exact_shard_and_detects_source_change(self):
        source = wx_record(wx_item())
        raw = {'content':source,'compress_content':None,'local_type':49,'sort_seq':7}
        calls=[]
        db=SimpleNamespace(get_message_row=lambda *a,**k:(calls.append(k) or raw),_msg_type_name=lambda _: '文件/链接/卡片')
        expected={'_db_user':'group@chatroom','_db_local_id':4,'_db_raw_type':49,'_db_shard':'message_2','_db_sort_seq':7,'_db_content_sha256':record_digest(source,None)}
        self.assertEqual(len(read_record(db,'group@chatroom',{'row':expected})['messages']),1)
        self.assertEqual(calls[0]['shard'],'message_2')
        raw['content']=source.replace('周五','周六')
        with self.assertRaises(BridgeError):read_record(db,'group@chatroom',{'row':expected})

    def test_wechat_search_expands_body_and_keeps_source_hash_private(self):
        source=wx_record(wx_item('正文里的作业关键词'))
        row={'content':source,'shard':'message_2','local_id':4,'create_time':1793239200,'sender_username':'sender','type':'文件/链接/卡片','sort_seq':7}
        raw={'local_type':(19<<32)|49,'sort_seq':7,'message_content':source,'compress_content':None}
        db=SimpleNamespace(_run_msg_query=lambda user, callback:([raw],{}),_msg_row_to_dict=lambda r,m:row,_message_dbs=lambda:['message_2'])
        result=scoped_history(db,'group@chatroom',{'start_date':'2026-10-29','end_date':'2026-10-29','scan_limit':10})
        record=result['rows'][0]
        self.assertIn('正文里的作业关键词',record['text'])
        self.assertEqual(record['merged_record']['state'],'inline')
        self.assertEqual(record['attachments'],[])
        self.assertEqual(record['_db_raw_type'],(19<<32)|49)

    def test_wechat_read_uses_compressed_body_fallback(self):
        source=wx_record(wx_item())
        raw={'content':b'','compress_content':source.encode(),'local_type':49,'sort_seq':7}
        db=SimpleNamespace(get_message_row=lambda *a,**k:raw,_msg_type_name=lambda _:'文件/链接/卡片',_friendly_content=lambda body,t:body.decode())
        expected={'_db_user':'g','_db_local_id':4,'_db_raw_type':49,'_db_shard':'message_2','_db_sort_seq':7,'_db_content_sha256':record_digest(b'',source.encode())}
        self.assertEqual(len(read_record(db,'g',{'row':expected})['messages']),1)


class RecordScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'config.json'
        self.cfg=load_json(Path(__file__).with_name('config.example.json'))
        self.cfg['qq'].update(enabled=True,account='42',backend='db_readonly',active_download=True)
        self.cfg['chats']['sample']={'platform':'qq','kind':'group','id':'100','name':'sample'}
        write_json(self.path,self.cfg)
        self.bridge=Bridge(self.path)
        row={'id':'m1','time':'2026-10-29T10:00:00+08:00','text':'[合并聊天记录]','attachments':[], 'merged_record':{'available':True}}
        with patch.object(self.bridge,'worker',return_value={'rows':[row],'coverage':{}}):
            self.receipt=self.bridge.search('sample','2026-10-29','2026-10-29','','验收')['receipt_id']

    def tearDown(self):self.temp.cleanup()

    def test_unseen_message_denied_before_worker(self):
        with patch.object(self.bridge,'worker') as worker:
            with self.assertRaises(BridgeError):self.bridge.read_record(self.receipt,'unseen')
            worker.assert_not_called()

    def test_block_after_search_revokes_record_before_worker(self):
        self.cfg['blocked']=['qq:group:100']
        write_json(self.path,self.cfg)
        with patch.object(self.bridge,'worker') as worker:
            with self.assertRaises(BridgeError):self.bridge.read_record(self.receipt,'m1')
            worker.assert_not_called()

    def test_inflight_block_revokes_return(self):
        def read(_):
            self.cfg['blocked']=['qq:group:100']
            write_json(self.path,self.cfg)
            return {'messages':[]}
        with patch.object(self.bridge,'worker',side_effect=read):
            with self.assertRaises(BridgeError):self.bridge.read_record(self.receipt,'m1')

    def test_public_result_hides_internal_keys(self):
        with patch.object(self.bridge,'worker',return_value={'messages':[{'text':'作业','_key':'private'}],'complete':True}) as worker:
            result=self.bridge.read_record(self.receipt,'m1',True)
        self.assertTrue(result['content_is_untrusted'])
        self.assertNotIn('_key',result['messages'][0])
        self.assertTrue(worker.call_args[0][0]['fetch_if_missing'])

    def test_qq_cache_only_denied_before_snapshot(self):
        with patch.object(self.bridge,'worker') as worker:
            with self.assertRaises(BridgeError):self.bridge.read_record(self.receipt,'m1',False)
            worker.assert_not_called()


if __name__=='__main__':unittest.main()
