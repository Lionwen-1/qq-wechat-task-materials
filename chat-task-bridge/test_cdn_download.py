"""Synthetic transport tests. Never use account credentials or external network."""
import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from bridge import BridgeError
from wechat_cdn import account_route, download, pack_fields, protobuf, route_from_table, unpack_fields
from wechat_db_worker import fetch_cdn, public_content
from qq_cdn import image_url, fetch_image


def v(value):
    out = bytearray()
    while value > 127:
        out.append((value & 127) | 128)
        value >>= 7
    return bytes(out) + bytes([value])


def pb(fields):
    return b"".join(v(n * 8 + (2 if isinstance(value, bytes) else 0)) +
                    (v(len(value)) + value if isinstance(value, bytes) else v(value)) for n, value in fields)


def table(uin=42, ip=0x08080808):
    conf = pb([(1, 1), (3, ip), (7, 443), (8, b"synthetic-auth")])
    rule = pb([(1, 0), (2, 1), (3, 1), (4, 0), (5, 2), (6, 1)])
    return pb([(1, 1), (2, uin), (7, conf), (8, rule)])


class Response:
    status = 200

    def __init__(self, raw):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, maximum):
        return self.raw[:maximum]


class CDNTests(unittest.TestCase):
    def setUp(self):
        self.plain = b"synthetic source bytes" * 4000
        key = b"k" * 16
        pad = padding.PKCS7(128).padder()
        padded = pad.update(self.plain) + pad.finalize()
        encrypt = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        self.encrypted = encrypt.update(padded) + encrypt.finalize()
        self.route = route_from_table(protobuf(table()), 1)
        self.descriptor = {"filetype": 1, "size": len(self.plain), "key": key,
                           "fileid": "synthetic-file", "md5": hashlib.md5(self.plain).hexdigest()}
        self.requests = []

    def reply(self, req, **kwargs):
        fields = unpack_fields(req.data)
        self.requests.append(fields)
        start, end = int(fields["rangestart"]), int(fields["rangeend"])
        block = self.encrypted[start:end + 1]
        return Response(pack_fields({"retcode": b"0", "seq": fields["seq"],
            "rangestart": str(start).encode(), "rangeend": str(start + len(block) - 1).encode(),
            "totalsize": str(len(self.encrypted)).encode(), "filedata": block}))

    def run_download(self, effect=None):
        with patch("wechat_cdn.urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = effect or self.reply
            return download(self.route, self.descriptor, time.monotonic() + 5, 1024 * 1024, 123)

    def test_multirange_aes_padding_and_message_digest(self):
        actual, result = self.run_download()
        self.assertEqual(actual, self.plain)
        self.assertTrue(result["source_digest_verified"])
        self.assertEqual([int(r["rangestart"]) for r in self.requests], [0, 65536])

    def test_wrong_message_digest_never_returns_bytes(self):
        self.descriptor["md5"] = "0" * 32
        with self.assertRaises(BridgeError):
            self.run_download()

    def test_bad_sequence_never_returns_bytes(self):
        def wrong(req, **kw):
            response = self.reply(req)
            fields = unpack_fields(response.raw)
            fields["seq"] = b"99"
            return Response(pack_fields(fields))
        with self.assertRaises(BridgeError):
            self.run_download(wrong)

    def test_expired_server_result_is_an_error(self):
        def expired(req, **kw):
            return Response(pack_fields({"retcode": b"-510305"}))
        with self.assertRaisesRegex(BridgeError, "-510305"):
            self.run_download(expired)

    def test_oversize_rejected_before_network(self):
        with patch("wechat_cdn.urllib.request.build_opener") as factory:
            with self.assertRaises(BridgeError):
                download(self.route, self.descriptor, time.monotonic() + 5, 100, 123)
            factory.assert_not_called()

    def test_truncated_and_duplicate_fields_rejected(self):
        field = pack_fields({"filedata": b"abc"})
        for raw in [field[:-1], field + field, b"\xff\xff\xff\xff"]:
            with self.assertRaises(BridgeError):
                unpack_fields(raw)

    def test_private_cdn_route_rejected(self):
        with self.assertRaises(BridgeError):
            route_from_table(protobuf(table(ip=0x0100007f)), 1)

    def test_ambiguous_route_priority_rejected(self):
        raw = table()
        fields = protobuf(raw)
        rule = next(value for n, w, value in fields if n == 8)
        with self.assertRaises(BridgeError):
            route_from_table(protobuf(raw + pb([(8, rule)])), 1)

    def test_latest_route_is_selected_only_for_live_uin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Tencent/xwechat/net/cdncomm"
            root.mkdir(parents=True)
            records = [pb([(2, stamp), (7, table(uin))]) for stamp, uin in [(10, 42), (20, 42), (30, 99)]]
            (root / "cdninfo_new.cache").write_bytes(pb([(1, record) for record in records]))
            with patch.dict("os.environ", {"APPDATA": temp}):
                self.assertEqual(account_route(42, 1)["uin"], 42)
                with self.assertRaises(BridgeError):
                    account_route(50, 1)

    def test_cache_only_never_reads_cdn_credentials(self):
        with patch("wechat_cdn.account_route") as route:
            for req in [{"settings": {"active_download": False}},
                        {"settings": {"active_download": True}, "fetch_if_missing": False}]:
                with self.assertRaises(BridgeError):
                    fetch_cdn(None, None, req, None, "file", "a.zip")
            route.assert_not_called()

    def test_qq_original_url_uses_source_descriptor_and_spec_zero(self):
        segment = {"cdn_url": "/download?appid=1407&fileid=ABCDEFGHIJKLMNOP&spec=198"}
        self.assertEqual(image_url(segment), "https://multimedia.nt.qq.com.cn/download?appid=1407&fileid=ABCDEFGHIJKLMNOP&spec=0")

    def test_qq_external_url_duplicate_id_and_unknown_app_rejected(self):
        for value in ["https://evil.example/download?appid=1407&fileid=ABCDEFGHIJKLMNOP",
                      "/download?appid=1407&fileid=ABCDEFGHIJKLMNOP&fileid=QRSTUVWXYZ123456",
                      "/download?appid=9999&fileid=ABCDEFGHIJKLMNOP"]:
            with self.assertRaises(BridgeError):
                image_url({"cdn_url": value})

    def test_qq_cache_only_never_scans_process_or_uses_network(self):
        with patch("qq_cdn.read_rkeys") as credentials, patch("qq_cdn.socket.getaddrinfo") as dns:
            with self.assertRaises(BridgeError):
                fetch_image({}, {"settings": {"active_download": True}, "fetch_if_missing": False}, 0, None)
            credentials.assert_not_called()
            dns.assert_not_called()

    def test_media_credentials_never_become_public_message_text(self):
        xml = '<msg><img aeskey="synthetic-secret" cdnbigimgurl="synthetic-file"/></msg>'
        for kind in (3, 34, 43, 47):
            text = public_content(kind, xml)
            self.assertNotIn("synthetic-secret", text)
            self.assertNotIn("synthetic-file", text)
        self.assertEqual(public_content(1, "normal task message"), "normal task message")


if __name__ == "__main__":
    unittest.main()
