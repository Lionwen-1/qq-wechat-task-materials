import hashlib
import hmac
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from bridge import Bridge, BridgeError, load_json, write_json
from qq_db_worker import select_rows
from wechat_db_worker import authenticated_page, card_xml, decrypt_snapshot, load_read_modules


class ReadOnlyTests(unittest.TestCase):
    def test_qq_sql_only_selected_group_and_dates(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute('CREATE TABLE group_msg_table("40001","40050","40020","40033","40011","40090","40093","40800","40021")')
        # A selected group, an excluded group with the same timestamp, and an old row.
        for mid, group, stamp in [(1, 100, 1790812800), (2, 200, 1790812800), (3, 100, 1759276800)]:
            c.execute('INSERT INTO group_msg_table VALUES(?,?,?,?,?,?,?,?,?)', (mid, stamp, "sender", 1, 2, "", "", b"", group))
        req = {"chat": {"kind": "group", "id": "100"}, "start_date": "2026-10-01", "end_date": "2026-10-02", "scan_limit": 100}
        self.assertEqual([r["msg_id"] for r in select_rows(c, req)], [1])
        self.assertEqual([r["msg_id"] for r in select_rows(c, req, message_id="2")], [])
        c.close()

    def test_unapproved_chat_never_reaches_db_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            write_json(path, load_json(Path(__file__).with_name("config.example.json")))
            bridge = Bridge(path)
            with patch.object(bridge, "worker") as worker:
                with self.assertRaises(BridgeError):
                    bridge.search("excluded", "2026-10-01", "2026-10-02", "", "test")
                worker.assert_not_called()

    def test_parent_cleans_snapshot_after_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            cfg = load_json(Path(__file__).with_name("config.example.json"))
            write_json(path, cfg)
            bridge = Bridge(path)
            with patch("bridge.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 1)):
                with self.assertRaises(BridgeError):
                    bridge.worker({"chat": {"platform": "wechat"}})
            self.assertEqual(list(bridge.state.glob("wx-request-*")), [])

    def test_parent_cleans_snapshot_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            write_json(path, load_json(Path(__file__).with_name("config.example.json")))
            bridge = Bridge(path)
            result = subprocess.CompletedProcess([], 0, stdout='{"ok":true,"result":{"rows":[]}}')
            with patch("bridge.subprocess.run", return_value=result):
                self.assertEqual(bridge.worker({"chat": {"platform": "wechat"}}), {"rows": []})
            self.assertEqual(list(bridge.state.glob("wx-request-*")), [])

    def test_group_prefix_xml_does_not_hide_file(self):
        value = 'wxid_example:\n<?xml version="1.0"?><msg><appmsg><type>6</type><title>任务.zip</title></appmsg></msg>'
        self.assertEqual(card_xml(value).findtext(".//appmsg/type"), "6")
        self.assertIsNone(card_xml("plain text"))

    def test_read_modules_never_import_gui(self):
        load_read_modules()
        self.assertFalse(any(name in sys.modules for name in ("pyweixin", "pywinauto", "uiautomation", "pyautogui")))

    def test_wechat_page_hmac_rejects_tampering(self):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        module, _ = load_read_modules()
        key, salt, iv = b"k" * 32, b"s" * 16, b"i" * 16
        plain = b"p" * 4016
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        encrypted = encryptor.update(plain) + encryptor.finalize()
        mac_key = hashlib.pbkdf2_hmac("sha512", key, bytes(b ^ 0x3A for b in salt), 2, 32)
        body = encrypted + iv
        digest = hmac.new(mac_key, body + struct.pack("<I", 2), hashlib.sha512).digest()
        page = body + digest
        self.assertEqual(authenticated_page(module, key, salt, page, 2)[:4016], plain)
        tampered = bytearray(page)
        tampered[12] ^= 1
        with self.assertRaises(BridgeError):
            authenticated_page(module, key, salt, bytes(tampered), 2)

    def test_wechat_wal_does_not_apply_uncommitted_tail(self):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        module, _ = load_read_modules()
        key, salt, iv = b"k" * 32, b"s" * 16, b"i" * 16
        mac_key = hashlib.pbkdf2_hmac("sha512", key, bytes(b ^ 0x3A for b in salt), 2, 32)

        def page(number, fill):
            plain = fill * (4000 if number == 1 else 4016)
            encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
            encrypted = encryptor.update(plain) + encryptor.finalize()
            body = encrypted + iv
            digest = hmac.new(mac_key, body + struct.pack("<I", number), hashlib.sha512).digest()
            return (salt if number == 1 else b"") + body + digest

        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "encrypted.db", Path(directory) / "plain.db"
            source.write_bytes(page(1, b"A") + page(2, b"A"))
            header = struct.pack(">I", 0x377F0682) + b"\0" * 12 + b"GENSALT1" + b"\0" * 8
            committed = struct.pack(">II", 2, 2) + b"GENSALT1" + b"\0" * 8 + page(2, b"B")
            pending = struct.pack(">II", 2, 0) + b"GENSALT1" + b"\0" * 8 + page(2, b"C")
            Path(str(source) + "-wal").write_bytes(header + committed + pending)
            decrypt_snapshot(module, source, target, key)
            self.assertEqual(target.read_bytes()[4096:4096 + 4016], b"B" * 4016)


if __name__ == "__main__":
    unittest.main()
