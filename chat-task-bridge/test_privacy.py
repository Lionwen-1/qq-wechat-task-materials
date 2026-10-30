"""Security regressions use only temporary files and synthetic credentials."""
import io
import json
import os
from pathlib import Path
import ssl
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from bridge import Bridge, BridgeError, load_json, write_json
from privacy import (PrivacyError, cleanup_receipts, cleanup_scratch, mark_download, private_directory,
                     read_receipt, reject_reparse, verify_image, worker_environment, write_receipt)
from wechat_cdn import RouteHTTPSConnection, TLS_SERVER_NAME, download, https_post


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)

    def tearDown(self):
        self.scratch.cleanup()

    def test_dpapi_receipt_roundtrip_hides_message_and_credentials(self):
        path = self.root / "receipts" / ("a" * 32 + ".json")
        value = {"created_at": time.time(), "text": "private synthetic text", "secret": "synthetic-only-key"}
        write_receipt(path, value)
        self.assertEqual(read_receipt(path), value)
        self.assertNotIn(value["text"], path.read_text())
        self.assertNotIn(value["secret"], path.read_text())

    def test_dpapi_tampering_does_not_return_partial_data(self):
        path = self.root / "receipt.json"
        write_receipt(path, {"text": "synthetic"})
        envelope = json.loads(path.read_text())
        envelope["sealed"] = "AAAA" + envelope["sealed"][4:]
        path.write_text(json.dumps(envelope))
        with self.assertRaises(PrivacyError):
            read_receipt(path)

    def test_legacy_plaintext_is_never_accepted_as_new_receipt(self):
        path = self.root / "receipt.json"
        write_json(path, {"created_at": time.time(), "rows": []})
        with self.assertRaisesRegex(PrivacyError, "旧版"):
            read_receipt(path)

    def test_expiry_cleanup_keeps_recent_and_unrelated_files(self):
        old, recent, unrelated = (self.root / name for name in ("a" * 32 + ".json", "b" * 32 + ".json", "user-file.txt"))
        for path in (old, recent, unrelated):
            path.write_text("synthetic")
        write_receipt(recent, {"fixture": True})
        os.utime(old, (0, 0))
        self.assertEqual(cleanup_receipts(self.root), 1)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists() and unrelated.exists())

    def test_private_directory_and_json_remove_broad_user_access(self):
        import win32security as security
        directory = private_directory(self.root / "private")
        file = directory / "config.json"
        write_json(file, {"fixture": True})
        forbidden = {str(security.CreateWellKnownSid(kind)) for kind in
                     (security.WinWorldSid, security.WinBuiltinUsersSid, security.WinAuthenticatedUserSid)}
        for path in (directory, file):
            sd = security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT, security.DACL_SECURITY_INFORMATION)
            dacl = sd.GetSecurityDescriptorDacl()
            self.assertIsNotNone(dacl)
            self.assertEqual(dacl.GetAceCount(), 3)
            self.assertFalse({str(dacl.GetAce(i)[2]) for i in range(3)} & forbidden)

    def test_download_is_marked_as_internet_material(self):
        path = self.root / "fixture.txt"
        path.write_text("synthetic")
        mark_download(path)
        with open(str(path) + ":Zone.Identifier") as stream:
            self.assertIn("ZoneId=3", stream.read())

    def test_worker_does_not_inherit_model_or_cloud_credentials(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic", "AWS_SECRET_ACCESS_KEY": "synthetic", "GITHUB_TOKEN": "synthetic", "PYTHONPATH": "untrusted"}):
            env = worker_environment()
        self.assertFalse({"OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "PYTHONPATH"} & env.keys())
        self.assertIn("APPDATA", env)

    def test_unsupported_python_is_rejected_before_worker_start(self):
        path = self.root / "config.json"
        write_json(path, load_json(Path(__file__).with_name("config.example.json")))
        bridge = Bridge(path)
        with patch("privacy.sys.version_info", (3, 10, 9)), patch("bridge.subprocess.run") as start:
            with self.assertRaisesRegex(PrivacyError, "Python"):
                bridge.worker({"chat": {"platform": "wechat"}})
            start.assert_not_called()

    def test_vulnerable_pillow_is_rejected_before_worker_start(self):
        path = self.root / "config.json"
        write_json(path, load_json(Path(__file__).with_name("config.example.json")))
        bridge = Bridge(path)
        with patch("importlib.metadata.version", return_value="12.3.0"), patch("bridge.subprocess.run") as start:
            with self.assertRaisesRegex(PrivacyError, "图片库"):
                bridge.worker({"chat": {"platform": "wechat"}})
            start.assert_not_called()

    def test_audit_does_not_store_raw_group_or_task(self):
        path = self.root / "config.json"
        write_json(path, load_json(Path(__file__).with_name("config.example.json")))
        bridge = Bridge(path)
        bridge.audit("search", "private group name", "private task description", {"ok": True, "extra": "private extra"})
        text = (bridge.state / "audit-v2.jsonl").read_text()
        self.assertNotIn("private group name", text)
        self.assertNotIn("private task description", text)
        self.assertNotIn("private extra", text)

    def test_raster_verification_rejects_postscript_without_running_it(self):
        data = io.BytesIO(b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage\n")
        with patch("subprocess.Popen") as execute:
            with self.assertRaises(PrivacyError):
                verify_image(data)
            execute.assert_not_called()

    def test_supported_image_still_verifies(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (2, 3)).save(buffer, "PNG")
        buffer.seek(0)
        self.assertEqual(verify_image(buffer), ("PNG", (2, 3)))

    def test_abandoned_snapshot_cleanup_preserves_other_materials(self):
        scratch, keep = self.root / "wx-request-fixture", self.root / "user-materials"
        for directory in (scratch, keep):
            directory.mkdir()
            (directory / "file.txt").write_text("synthetic")
        cleanup_scratch(self.root)
        self.assertFalse(scratch.exists())
        self.assertTrue((keep / "file.txt").is_file())

    def test_reparse_path_refused_before_privacy_writes(self):
        import stat
        from types import SimpleNamespace
        with patch.object(Path, "lstat", return_value=SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)):
            with self.assertRaises(PrivacyError):
                reject_reparse(self.root)

    def test_tls_has_required_certificates_and_pins_tencent_hostname(self):
        connection = RouteHTTPSConnection("8.8.8.8", 2)
        self.assertTrue(connection._context.check_hostname)
        self.assertEqual(connection._context.verify_mode, ssl.CERT_REQUIRED)
        context, stream = MagicMock(), MagicMock()
        connection._context = context
        with patch("wechat_cdn.socket.create_connection", return_value=stream) as connect:
            connection.connect()
        connect.assert_called_once_with(("8.8.8.8", 443), timeout=2)
        context.wrap_socket.assert_called_once_with(stream, server_hostname=TLS_SERVER_NAME)

    def test_invalid_certificate_closes_socket_without_plaintext_fallback(self):
        connection = RouteHTTPSConnection("8.8.8.8", 2)
        context, stream = MagicMock(), MagicMock()
        context.wrap_socket.side_effect = ssl.SSLCertVerificationError("synthetic")
        connection._context = context
        with patch("wechat_cdn.socket.create_connection", return_value=stream):
            with self.assertRaises(ssl.SSLCertVerificationError):
                connection.connect()
        stream.close.assert_called_once()

    def test_https_redirect_is_not_followed(self):
        with patch("wechat_cdn.RouteHTTPSConnection") as factory:
            response = factory.return_value.getresponse.return_value
            response.status = 302
            with self.assertRaises(BridgeError):
                https_post("8.8.8.8", b"synthetic", 1)
            response.read.assert_not_called()
            factory.return_value.close.assert_called_once()

    def test_unavailable_tls_never_uses_http(self):
        route = {"version": 1, "uin": 42, "auth": b"synthetic", "server_ips": ["8.8.8.8"]}
        descriptor = {"size": 1, "filetype": 1, "key": b"x" * 16, "fileid": "synthetic", "md5": "0" * 32}
        with patch("wechat_cdn.https_post", side_effect=ssl.SSLCertVerificationError("synthetic")), patch("urllib.request.urlopen") as plaintext:
            with self.assertRaisesRegex(BridgeError, "未回退"):
                download(route, descriptor, time.monotonic() + 1, 1024, 1)
            plaintext.assert_not_called()


if __name__ == "__main__":
    unittest.main()
