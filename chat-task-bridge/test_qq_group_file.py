"""Synthetic tests for session decoding, scoped requests and authenticated replies."""
import hashlib
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from bridge import BridgeError
from qq_db_worker import snapshot
from qq_group_file import COMMAND, build_request, crypto, encode, endpoint, fetch_group_file, parse_reply, sized, take_sized
from qq_session import check_kernel, decode_fields


class GroupFileTests(unittest.TestCase):
    def setUp(self):
        self.tea = crypto()
        self.key = b"k" * 16
        self.account = "42"
        self.sequence = 234567
        self.digest = hashlib.md5(b"synthetic file").hexdigest()

    def result(self, host=b"gzc-download.ftn.qq.com", digest=None):
        return [(1, 0, 0), (5, 2, host), (6, 2, b"synthetic-ticket"),
                (9, 2, bytes.fromhex(digest or self.digest))]

    def response(self, seq=None, command=COMMAND, code=0, compression=0, data=None, extension=b""):
        if data is None:
            result = encode([(n, v) for n, w, v in self.result()])
            data = encode([(1, 0x6d6), (2, 2), (3, 0), (4, encode([(3, result)]))])
        head = (struct.pack(">Ii", self.sequence if seq is None else seq, code) + sized(b"server-secret") +
                sized(command) + sized(b"session-secret") + struct.pack(">I", compression) + sized(b"") + extension)
        plain = sized(head) + sized(data)
        return b"\0\0\0\x0c\x01\0" + sized(self.account.encode()) + self.tea.qqtea_encrypt(plain, self.key)

    def parse(self, frame):
        return parse_reply(frame, self.account, self.sequence, self.key, self.tea)

    def test_request_contains_only_fixed_download_command_and_selected_group(self):
        material = {"a2": b"a" * 72, "d2": b"d" * 88, "key": self.key, "uid": "u_" + "x" * 22}
        packet = build_request("42", "100", "/12345678-1234-1234-1234-123456789abc", material,
                               b"g" * 16, 537391628, "9.9.36-53644", self.sequence, self.tea)
        stream = io.BytesIO(packet)
        service = io.BytesIO(take_sized(stream))
        self.assertEqual(service.read(5), b"\0\0\0\x0c\x01")
        self.assertEqual(take_sized(service), material["d2"])
        service.read(1)
        self.assertEqual(take_sized(service), b"42")
        plaintext = self.tea.qqtea_decrypt(service.read(), self.key)
        self.assertIn(COMMAND, plaintext)
        self.assertNotIn(b"Register", plaintext)
        self.assertNotIn(b"Login", plaintext)

    def test_authenticated_reply_and_opaque_header_extension(self):
        result = self.parse(self.response(extension=b"opaque-header"))
        self.assertIn((9, 2, bytes.fromhex(self.digest)), result)

    def test_reply_account_command_and_sequence_must_match(self):
        for frame in [self.response(seq=self.sequence + 1), self.response(command=b"OtherCommand")]:
            with self.assertRaises(BridgeError):
                self.parse(frame)
        with self.assertRaises(BridgeError):
            parse_reply(self.response(), "43", self.sequence, self.key, self.tea)

    def test_wrong_session_key_rejected(self):
        with self.assertRaises(BridgeError):
            parse_reply(self.response(), self.account, self.sequence, b"z" * 16, self.tea)

    def test_service_error_does_not_echo_server_wording(self):
        with self.assertRaises(BridgeError) as caught:
            self.parse(self.response(code=-10003))
        self.assertIn("-10003", str(caught.exception))
        self.assertNotIn("server-secret", str(caught.exception))

    def test_compressed_reply_is_bounded(self):
        with self.assertRaises(BridgeError):
            self.parse(self.response(compression=1, data=zlib.compress(b"x" * (2 * 1024**2 + 1))))

    def test_unencrypted_reply_is_not_accepted(self):
        frame = bytearray(self.response())
        frame[4] = 0
        with self.assertRaises(BridgeError):
            self.parse(bytes(frame))

    def test_sized_fields_reject_truncation_and_impossible_length(self):
        for value in [b"", b"\0\0\0\x03", b"\xff\xff\xff\xff", b"\0\0\0\x10x"]:
            with self.assertRaises(BridgeError):
                take_sized(io.BytesIO(value))

    def test_cdn_host_and_source_digest_checked_before_dns(self):
        with patch("qq_group_file.public_addresses") as dns:
            for result in [self.result(host=b"evil.example"), self.result(host=b"127.0.0.1"),
                           self.result(digest="0" * 32)]:
                with self.assertRaises(BridgeError):
                    endpoint(result, self.digest)
            dns.assert_not_called()

    def test_valid_cdn_endpoint_preserves_opaque_server_ticket(self):
        with patch("qq_group_file.public_addresses", return_value=[]):
            url = endpoint(self.result(), self.digest)
        self.assertTrue(url.startswith("https://gzc-download.ftn.qq.com/ftn_handler/"))

    def test_cache_only_does_not_read_session_or_device(self):
        with patch("qq_group_file.read_material") as reader, patch("qq_group_file.check_kernel") as kernel:
            for settings, option in [({"active_download": False}, True), ({"active_download": True}, False)]:
                with self.assertRaises(BridgeError):
                    fetch_group_file({}, {"settings": settings, "chat": {}, "fetch_if_missing": option}, {}, None)
            reader.assert_not_called()
            kernel.assert_not_called()

    def test_invalid_target_or_filename_never_reads_credentials(self):
        segment = {"file_uuid": "/12345678-1234-1234-1234-123456789abc", "filesize": 14,
                   "md5_hex": self.digest, "filename": "../outside.zip"}
        request = {"settings": {"active_download": True}, "chat": {"kind": "group", "id": "100"}}
        with patch("qq_group_file.read_material") as reader:
            with self.assertRaises(BridgeError):
                fetch_group_file(segment, request, {}, None)
            segment["filename"] = "normal.zip"
            request["chat"]["kind"] = "friend"
            with self.assertRaises(BridgeError):
                fetch_group_file(segment, request, {}, None)
            reader.assert_not_called()

    def test_kernel_update_refused(self):
        with patch("qq_session.kernel_binding", return_value={"version": "9.9.36-53644", "wrapper_sha256": "changed"}):
            with self.assertRaises(BridgeError):
                check_kernel({"group_file_kernel": {}}, {})

    def test_qt6_session_layout_validated_without_real_process(self):
        instance = 0x10000
        memory = {}
        values = [b"a" * 144, b"d" * 176, b"e" * 32]
        for i, (offset, value) in enumerate(zip((0x158, 0x170, 0x188), values)):
            pointer = 0x20000 + i * 0x1000
            memory[instance + offset] = struct.pack("<QQQ", len(value) + 17, len(value), pointer)
            memory[pointer] = value
        memory[instance + 0x50] = struct.pack("<QQQ", 49, 24, 0x25000)
        memory[0x25000] = b"u_" + b"x" * 22
        def read(address, size):
            return memory.get(address, b"\0" * size)[:size]
        result = decode_fields(read, instance)
        self.assertEqual(len(result["key"]), 16)
        self.assertEqual(len(result["a2"]), 72)
        memory[0x22000] = b"not-a-valid-key" * 3
        self.assertIsNone(decode_fields(read, instance))

    def test_snapshot_accepts_append_only_wal_during_main_copy(self):
        import shutil
        original = shutil.copyfileobj
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.db", Path(directory) / "copy.db"
            source.write_bytes(b"h" * 1024 + b"encrypted-main")
            wal = Path(str(source) + "-wal")
            wal.write_bytes(b"w" * 32 + b"old-frames")
            def copy(src, dst, length):
                original(src, dst, length)
                with wal.open("ab") as stream:
                    stream.write(b"new-frames")
            with patch("qq_db_worker.shutil.copyfileobj", side_effect=copy) as mocked:
                snapshot(source, target)
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(target.read_bytes(), b"encrypted-main")
            self.assertEqual(Path(str(target) + "-wal").read_bytes(), wal.read_bytes())

    def test_snapshot_refuses_concurrent_main_checkpoint(self):
        import shutil
        original = shutil.copyfileobj
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.db", Path(directory) / "copy.db"
            source.write_bytes(b"h" * 1024 + b"encrypted-main")
            def copy(src, dst, length):
                original(src, dst, length)
                with source.open("ab") as stream:
                    stream.write(b"changed")
            with patch("qq_db_worker.shutil.copyfileobj", side_effect=copy), patch("qq_db_worker.time.sleep"):
                with self.assertRaises(BridgeError):
                    snapshot(source, target)


if __name__ == "__main__":
    unittest.main()
