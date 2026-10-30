import base64
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image
from bridge import BridgeError, public_value, write_json
from merged_records import attach, descriptor_digest, view, wechat_record
from privacy import read_receipt, write_receipt
from qq_cdn import image_url
from qq_forward import group_file, image_descriptors
from qq_group_file import encode, fetch_group_file
from record_media import fetch_qq_legacy_image, private_endpoint, safe_name, save_bytes
import test_merged_records as fixtures
from test_merged_records import wx_item, wx_record
from wechat_cdn import protobuf
from wechat_db_worker import fetch_record_attachment


UUID='12345678-1234-1234-1234-123456789abc'


def group_element(extra=None, digest=b''):
    values=[(1,102),(2,('/'+UUID).encode()),(3,42),(4,b'sample.txt'),(8,digest)]
    if extra is not None:values.append((7,json.dumps(extra).encode()))
    outer=encode([(1,6),(7,encode([(2,encode(values))]))])
    raw=b'\x01'+len(outer).to_bytes(2,'big')+outer
    return protobuf(encode([(5,encode([(1,24),(2,raw)]))]))


def copied_extra(name=b'sample.txt',size=42):
    data=encode([(2,encode([(1,3),(3,200),(4,UUID.encode()),(5,name),(6,size),(13,102)]))])
    return {'ExtInfo':base64.b64encode(data).decode()}


class MediaParserTests(unittest.TestCase):
    def test_forward_copy_extinfo_overrides_old_group_and_uuid(self):
        descriptor=list(group_file(group_element(copied_extra()),[(1,0,100)]))[0]
        self.assertEqual(descriptor['group_id'],200)
        self.assertEqual(descriptor['file_uuid'],UUID)
        self.assertEqual(descriptor['filesize'],42)

    def test_copy_metadata_must_match_original_name_size_and_type(self):
        for extra in [copied_extra(name=b'other.txt'),copied_extra(size=43),{'ExtInfo':'bad base64'}]:
            descriptor=list(group_file(group_element(extra),[(1,0,100)]))[0]
            self.assertEqual(descriptor['group_id'],100)
            self.assertEqual(descriptor['file_uuid'],'/'+UUID)

    def test_group_missing_digest_is_only_eligible_for_source_bound_file_metadata(self):
        descriptor=list(group_file(group_element(copied_extra()),[(1,0,100)]))[0]
        result=view();result['messages']=[{}]
        attach(result,result['messages'][0],'file','sample.txt',42,descriptor)
        self.assertTrue(result['messages'][0]['attachments'][0]['downloadable'])
        descriptor['transport']='ordinary_file'
        result=view();result['messages']=[{}]
        attach(result,result['messages'][0],'file','sample.txt',42,descriptor)
        self.assertFalse(result['messages'][0]['attachments'][0]['downloadable'])

    def test_modern_image_url_joins_existing_query_without_second_question_mark(self):
        file=encode([(1,42),(2,b'a'*32),(4,b'image.jpg')])
        pic=encode([(1,b'/download?appid=1407&fileid=abcdefghijklmnop'),(2,encode([(1,b'&spec=0')])),(3,b'multimedia.nt.qq.com.cn')])
        info=encode([(1,encode([(1,encode([(1,file)])),(2,pic)]))])
        elem=protobuf(encode([(53,encode([(1,48),(2,info),(3,20)]))]))
        descriptor=list(image_descriptors(elem))[0]
        self.assertEqual(descriptor['cdn_url'].count('?'),1)
        self.assertIn('fileid=abcdefghijklmnop',image_url(descriptor))

    def test_wechat_nested_media_private_fields_do_not_enter_public_view(self):
        extra='<datatitle>sample.txt</datatitle><datasize>42</datasize><fullmd5>'+('a'*32)+'</fullmd5><cdndataurl>private-file-id</cdndataurl><cdndatakey>'+('b'*32)+'</cdndatakey>'
        result=wechat_record(wx_record(wx_item(typ='8',extra=extra)))
        self.assertTrue(result['attachments_downloadable'])
        rendered=json.dumps(public_value(result))
        self.assertNotIn('private-file-id',rendered)
        self.assertNotIn('b'*32,rendered)
        self.assertEqual(result['messages'][0]['attachments'][0]['name'],'sample.txt')


class MediaDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        buffer=io.BytesIO();Image.new('RGB',(2,3),'blue').save(buffer,format='PNG');self.image=buffer.getvalue()
        self.digest=hashlib.md5(self.image).hexdigest()
        self.descriptor={'md5_hex':self.digest,'filesize':len(self.image),'filename':'source.png'}
        self.request={'settings':{'active_download':True},'target':str(self.root),'maximum_bytes':1024*1024,'image_tier':'original'}

    def tearDown(self):self.temp.cleanup()

    def test_legacy_image_uses_fixed_https_digest_endpoint_and_verifies_bytes(self):
        descriptor={**self.descriptor,'url':'https://untrusted.example/secret'}
        with patch('record_media.get_https',return_value=self.image) as network:
            result=fetch_qq_legacy_image(descriptor,self.request)
        self.assertEqual(network.call_args[0][0],'https://gchat.qpic.cn/gchatpic_new/0/0-0-'+self.digest.upper()+'/0')
        self.assertEqual(Path(result['files'][0]).read_bytes(),self.image)
        self.assertEqual(result['dimensions'],[2,3])

    def test_source_digest_and_size_mismatch_do_not_create_file(self):
        with self.assertRaises(BridgeError):save_bytes(self.image+b'x',self.descriptor,self.request,'image','fixture')
        with self.assertRaises(BridgeError):save_bytes(b'x'*len(self.image),self.descriptor,self.request,'image','fixture')
        self.assertEqual(list(self.root.iterdir()),[])

    def test_cache_only_and_thumbnail_never_fetch_legacy_original(self):
        with patch('record_media.get_https') as network:
            for request in [{**self.request,'fetch_if_missing':False},{**self.request,'image_tier':'thumbnail'}]:
                with self.assertRaises(BridgeError):fetch_qq_legacy_image(self.descriptor,request)
            network.assert_not_called()

    def test_bad_filename_and_private_endpoint_are_rejected(self):
        for value in ['../outside','C:\\bad','CON.txt','trailing.','bad?.txt']:
            with self.assertRaises(BridgeError):safe_name(value)
        for host,path in [(b'evil.example',b'/ftn_handler/x?key=y'),(b'127.0.0.1',b'/ftn_handler/x'),(b'download.qq.com',b'//evil.example/x')]:
            with self.assertRaises(BridgeError):private_endpoint(protobuf(encode([(20,host),(50,path)])))

    def test_private_file_endpoint_is_upgraded_to_verified_https(self):
        result=private_endpoint(protobuf(encode([(20,b'download.ftn.qq.com'),(40,80),(50,b'/ftn_handler/token?fname=x')])) )
        self.assertEqual(result,'https://download.ftn.qq.com/ftn_handler/token?fname=x&isthumb=0')

    def test_missing_group_file_digest_uses_authenticated_reply_then_verifies_bytes(self):
        plain=b'source-bound-file';digest=hashlib.md5(plain).digest()
        descriptor={'transport':'qq_record_group_file','bus_id':102,'filename':'task.txt','filesize':len(plain),'file_uuid':UUID}
        request={**self.request,'settings':{'active_download':True,'account':'42'},'chat':{'kind':'group','id':'100'}}
        material={'key':b'k'*16,'a2':b'a'*72,'d2':b'd'*88,'uid':'u_'+'x'*22}
        opener=MagicMock();response=opener.open.return_value.__enter__.return_value;response.status=200;response.read.return_value=plain
        reply=[(5,2,b'download.ftn.qq.com'),(6,2,b'ticket'),(9,2,digest)]
        with ExitStack() as stack:
            for name,value in [('check_kernel',{'version':'9.9.36-53644'}),('read_material',material),('device_and_app',(b'g'*16,123)),('public_addresses',[(2,1,6,'',('8.8.8.8',8080))]),('parse_reply',reply)]:
                stack.enter_context(patch('qq_group_file.'+name,return_value=value))
            stack.enter_context(patch('qq_group_file.socket.create_connection'))
            stack.enter_context(patch('qq_group_file.receive',side_effect=[(12).to_bytes(4,'big'),b'reply']))
            stack.enter_context(patch('qq_group_file.urllib.request.build_opener',return_value=opener))
            result=fetch_group_file(descriptor,request,{},None)
        self.assertEqual(Path(result['files'][0]).read_bytes(),plain)
        self.assertEqual(result['digest_origin'],'qq_authenticated_file_metadata')
        self.assertTrue(result['source_digest_verified'])

    def test_ordinary_missing_digest_cannot_use_record_fallback(self):
        descriptor={'bus_id':102,'filename':'task.txt','filesize':42,'file_uuid':UUID}
        request={**self.request,'chat':{'kind':'group','id':'100'}}
        with patch('qq_group_file.read_material') as session:
            with self.assertRaises(BridgeError):fetch_group_file(descriptor,request,{},None)
            session.assert_not_called()

    def wechat_request(self,kind='file'):
        plain=b'synthetic source file' if kind=='file' else self.image
        descriptor={'transport':'wechat_record','filetype':5 if kind=='file' else 1,'md5':hashlib.md5(plain).hexdigest(),'size':len(plain),'fileid':'private-file-id','key':'b'*32}
        attachment={'kind':kind,'name':'task.txt' if kind=='file' else 'image.png','_record_descriptor':descriptor,'_descriptor_sha256':descriptor_digest(descriptor)}
        row={'_record_entry':0,'attachments':[attachment]}
        request={**self.request,'settings':{'active_download':True,'client_version':'4.2.0.9'},'record_parent':{'id':'parent'},'row':row,'attachment_index':0}
        db=SimpleNamespace(account_dir=str(self.root/'account'),account='acct',extract_master_key=lambda:(0,42,'acct'))
        return db,request,attachment,plain

    def test_wechat_file_and_image_reuse_verified_cdn_downloader(self):
        for kind in ('file','image'):
            db,request,attachment,plain=self.wechat_request(kind)
            with patch('wechat_db_worker.read_record',return_value={'messages':[{'attachments':[attachment]}]}),patch('wechat_cdn.account_route',return_value={}),patch('wechat_cdn.download',return_value=(plain,{'transport':'wechat_https_cdn','source_digest_verified':True})) as network:
                result=fetch_record_attachment(db,'group@chatroom',request)
            self.assertEqual(Path(result['files'][0]).read_bytes(),plain)
            self.assertEqual(network.call_args[0][1]['filetype'],5 if kind=='file' else 1)

    def test_wechat_changed_descriptor_and_cache_only_never_reach_cdn(self):
        db,request,attachment,plain=self.wechat_request()
        with patch('wechat_db_worker.read_record',return_value={'messages':[{'attachments':[attachment]}]}),patch('wechat_cdn.download') as network:
            with self.assertRaises(BridgeError):fetch_record_attachment(db,'g',{**request,'fetch_if_missing':False})
            altered={**attachment,'_record_descriptor':{**attachment['_record_descriptor'],'fileid':'different'}}
            with patch('wechat_db_worker.read_record',return_value={'messages':[{'attachments':[altered]}]}):
                with self.assertRaises(BridgeError):fetch_record_attachment(db,'g',request)
            network.assert_not_called()


class ExpandedReceiptTests(unittest.TestCase):
    setUp=fixtures.RecordScopeTests.setUp
    tearDown=fixtures.RecordScopeTests.tearDown

    def expanded(self):
        descriptor={'md5_hex':'a'*32,'filesize':42,'file_uuid':'private-uuid','key':'private-key'}
        attachment={'kind':'file','name':'task.txt','bytes':42,'downloadable':True,'_record_descriptor':descriptor,'_descriptor_sha256':descriptor_digest(descriptor)}
        with patch.object(self.bridge,'worker',return_value={'messages':[{'time':'2022-01-01','text':'[文件]','attachments':[attachment]}],'complete':True}):
            return self.bridge.read_record(self.receipt,'m1')

    def test_derived_receipt_preserves_parent_and_expiry_without_mutating_query(self):
        parent,_=self.bridge.receipt(self.receipt)
        result=self.expanded()
        child,_=self.bridge.receipt(result['receipt_id'])
        self.assertNotEqual(result['receipt_id'],self.receipt)
        self.assertEqual(child['created_at'],parent['created_at'])
        self.assertEqual(child['record_parent']['id'],'m1')
        self.assertEqual(result['messages'][0]['id'],'record:0')
        self.assertEqual(result['messages'][0]['matched_attachment_indices'],[0])
        self.assertNotIn('private-key',json.dumps(result))
        unchanged,_=self.bridge.receipt(self.receipt)
        self.assertEqual(unchanged['rows'][0]['attachments'],[])

    def test_new_block_revokes_derived_download_before_worker(self):
        result=self.expanded();self.cfg['blocked']=['qq:group:100'];write_json(self.path,self.cfg)
        with patch.object(self.bridge,'worker') as worker:
            with self.assertRaises(BridgeError):self.bridge.fetch(result['receipt_id'],'record:0')
            worker.assert_not_called()

    def test_expired_derived_receipt_does_not_reach_worker(self):
        result=self.expanded();path=self.bridge.state/'receipts'/(result['receipt_id']+'.json')
        receipt=read_receipt(path);receipt['created_at']-=3601;write_receipt(path,receipt)
        with patch.object(self.bridge,'worker') as worker:
            with self.assertRaises(BridgeError):self.bridge.fetch(result['receipt_id'],'record:0')
            worker.assert_not_called()


if __name__=='__main__':unittest.main()
