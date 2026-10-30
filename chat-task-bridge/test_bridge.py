from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bridge import Bridge, BridgeError, load_json, parse_time, write_json


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "config.json"
        self.config = load_json(Path(__file__).with_name("config.example.json"))
        self.config["qq"].update(enabled=True, account="42", backend="db_readonly")
        self.config["chats"]["sample"] = {"platform": "qq", "kind": "group", "id": "100", "name": "sample"}
        write_json(self.path, self.config)
        self.bridge = Bridge(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_default_denies_before_adapter(self):
        with patch.object(self.bridge, "worker") as source:
            with self.assertRaises(BridgeError):
                self.bridge.search("excluded", "2026-10-01", "2026-10-02", "", "test")
            source.assert_not_called()

    def test_block_canonical_cannot_be_bypassed_by_alias(self):
        self.config["chats"]["renamed"] = self.config["chats"]["sample"]
        self.config["blocked"] = ["qq:group:100"]
        write_json(self.path, self.config)
        with patch.object(self.bridge, "worker") as source:
            for alias in ["sample", "renamed"]:
                with self.assertRaises(BridgeError):
                    self.bridge.search(alias, "2026-10-01", "2026-10-02", "", "test")
            source.assert_not_called()

    def search_fixture(self):
        rows = [
            {"id": "m1", "time": "2026-10-02T10:00:00+08:00", "sender": "A", "text": "report", "attachments": [{"kind": "file", "file": "known", "_segment": 2}], "_secret": "private-ui", "_qq_segments": [{"cdn_url": "synthetic-transport-secret"}]},
            {"id": "m2", "time": "2026-09-30T10:00:00+08:00", "text": "report", "attachments": []},
            {"id": "m3", "time": None, "text": "report", "attachments": []},
        ]
        with patch.object(self.bridge, "worker", return_value={"rows": rows, "coverage": {}}):
            return self.bridge.search("sample", "2026-10-01", "2026-10-02", "report", "test")

    def test_date_filter_unknown_exclusion_and_private_evidence(self):
        result = self.search_fixture()
        self.assertEqual([r["id"] for r in result["messages"]], ["m1"])
        self.assertNotIn("_secret", result["messages"][0])
        self.assertNotIn("_segment", result["messages"][0]["attachments"][0])
        self.assertEqual(result["coverage"]["unknown_time_excluded"], 1)
        self.assertFalse(result["coverage"]["history_complete"])
        stored = load_json(self.bridge.state / "receipts" / (result["receipt_id"] + ".json"))
        self.assertNotIn("_qq_segments", stored["rows"][0])

    def test_block_after_search_revokes_download(self):
        receipt = self.search_fixture()["receipt_id"]
        self.config["blocked"] = ["qq:group:100"]
        write_json(self.path, self.config)
        with patch.object(self.bridge, "worker") as download:
            with self.assertRaises(BridgeError):
                self.bridge.fetch(receipt, "m1")
            download.assert_not_called()

    def test_unseen_and_negative_index_denied(self):
        receipt = self.search_fixture()["receipt_id"]
        for mid, index in [("other", 0), ("m1", -1), ("m1", 8)]:
            with self.assertRaises(BridgeError):
                self.bridge.fetch(receipt, mid, index)
        with self.assertRaises(BridgeError):
            self.bridge.fetch("../outside", "m1")

    def test_receipt_expiry(self):
        receipt = self.search_fixture()["receipt_id"]
        p = self.bridge.state / "receipts" / (receipt + ".json")
        obj = load_json(p)
        obj["created_at"] -= 3601
        write_json(p, obj)
        with self.assertRaises(BridgeError):
            self.bridge.fetch(receipt, "m1")

    def test_download_hash_and_source_manifest(self):
        receipt = self.search_fixture()["receipt_id"]

        def save(request):
            target = Path(request["target"])
            p = target / "task.txt"
            p.write_bytes(b"fixture")
            return {"files": [str(p)]}

        with patch.object(self.bridge, "worker", side_effect=save):
            result = self.bridge.fetch(receipt, "m1")
        self.assertEqual(result["files"][0]["bytes"], 7)
        self.assertEqual(len(result["files"][0]["sha256"]), 64)
        self.assertTrue((Path(result["files"][0]["path"]).parent.parent / "source.json").is_file())

    def test_unsupported_backend_denied_before_client_access(self):
        self.config["qq"]["backend"] = "unsupported"
        write_json(self.path, self.config)
        with patch.object(self.bridge, "worker") as source:
            with self.assertRaises(BridgeError):
                self.bridge.search("sample", "2026-10-01", "2026-10-02", "", "test")
            source.assert_not_called()

    def test_chinese_timestamps(self):
        self.assertEqual(parse_time("2026年10月2日 09:24").isoformat(), "2026-10-02T09:24:00+08:00")


if __name__ == "__main__":
    unittest.main()
