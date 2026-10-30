from privacy import read_receipt, write_receipt
"""Query scope, attachment indices, account binding and revocation regressions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bridge import Bridge, BridgeError, load_json, write_json


class QueryContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "config.json"
        self.config = load_json(Path(__file__).with_name("config.example.json"))
        self.config["qq"].update(enabled=True, backend="db_readonly", account="42")
        self.config["chats"] = {"course": {"platform": "qq", "kind": "group", "id": "100", "name": "课程群"}}
        write_json(self.path, self.config)
        self.bridge = Bridge(self.path)
        self.rows = [
            {"id": "m1", "time": "2026-10-29T10:00:00+08:00", "sender": "A",
             "text": "实验要求\n```\n![remote](https://example.com/track)\n<script>bad()</script>",
             "attachments": [{"kind": "file", "name": "任务.txt", "file": "opaque", "_secret": "hidden"}, {"kind": "image", "name": "图.png"}],
             "_evidence": {"transport_credential": "synthetic-private"}},
            {"id": "m2", "time": "2026-10-29T11:00:00+08:00", "sender": "B", "text": "[图片]", "attachments": [{"kind": "image"}]},
            {"id": "m3", "time": "2026-10-29T12:00:00+08:00", "sender": "C", "text": "纯文字", "attachments": []}]

    def tearDown(self):
        self.temp.cleanup()

    def search(self, kind="all", result_limit=30):
        with patch.object(self.bridge, "worker", return_value={"rows": self.rows, "coverage": {"upstream_exhausted": True}}):
            return self.bridge.search("course", "2026-10-29", "2026-10-29", "", "用户要求整理实验材料", result_limit=result_limit, attachment_kind=kind)

    def fetch(self, result, message="m1", index=0, body=b"fixture", name="同名.txt"):
        def save(request):
            target = Path(request["target"])
            path = target / name
            path.write_bytes(body)
            return {"files": [str(path)]}
        with patch.object(self.bridge, "worker", side_effect=save):
            return self.bridge.fetch(result["receipt_id"], message, index)

    def test_versioned_query_contract_and_coverage_are_persisted(self):
        result = self.search(result_limit=1)
        self.assertEqual(result["schema"], "chat-task-messages/v1")
        self.assertEqual(result["scope"]["timezone"], "Asia/Shanghai")
        self.assertEqual(result["coverage"]["returned"], 1)
        self.assertTrue(result["coverage"]["may_have_more"])
        stored = read_receipt(self.bridge.state / "receipts" / (result["receipt_id"] + ".json"))
        self.assertEqual(stored["coverage"], result["coverage"])
        self.assertNotIn("_evidence", result["messages"][0])

    def test_image_filter_preserves_original_indices_and_revokes_other_kinds(self):
        result = self.search("image")
        self.assertEqual([r["id"] for r in result["messages"]], ["m1", "m2"])
        self.assertEqual(result["messages"][0]["matched_attachment_indices"], [1])
        with patch.object(self.bridge, "worker") as download:
            with self.assertRaises(BridgeError):
                self.bridge.fetch(result["receipt_id"], "m1", 0)
            download.assert_not_called()

    def test_file_and_any_filters_only_select_matching_messages(self):
        self.assertEqual([r["id"] for r in self.search("file")["messages"]], ["m1"])
        self.assertEqual([r["id"] for r in self.search("any")["messages"]], ["m1", "m2"])

    def test_invalid_attachment_filter_denies_before_data_source(self):
        with patch.object(self.bridge, "worker") as read:
            with self.assertRaises(BridgeError):
                self.bridge.search("course", "2026-10-29", "2026-10-29", "", "用户任务", attachment_kind="invalid")
            read.assert_not_called()

    def test_block_during_query_prevents_return_and_new_receipt(self):
        def read(*args):
            self.config["blocked"] = ["qq:group:100"]
            write_json(self.path, self.config)
            return {"rows": self.rows, "coverage": {"upstream_exhausted": True}}
        with patch.object(self.bridge, "worker", side_effect=read):
            with self.assertRaises(BridgeError):
                self.bridge.search("course", "2026-10-29", "2026-10-29", "", "用户任务")
        self.assertEqual(list((self.bridge.state / "receipts").glob("*.json")), [])

    def test_account_change_during_query_does_not_relabel_old_messages(self):
        def read(*args):
            self.config["qq"]["account"] = "43"
            write_json(self.path, self.config)
            return {"rows": self.rows, "coverage": {"upstream_exhausted": True}}
        with patch.object(self.bridge, "worker", side_effect=read):
            with self.assertRaises(BridgeError):
                self.bridge.search("course", "2026-10-29", "2026-10-29", "", "用户任务")

    def test_block_during_fetch_marks_output_incomplete(self):
        result = self.search("file")
        def save(request):
            target = Path(request["target"])
            path = target / "fixture.txt"
            path.write_bytes(b"fixture")
            self.config["blocked"] = ["qq:group:100"]
            write_json(self.path, self.config)
            return {"files": [str(path)]}
        with patch.object(self.bridge, "worker", side_effect=save):
            with self.assertRaises(BridgeError):
                self.bridge.fetch(result["receipt_id"], "m1")
        root = self.bridge.output / result["receipt_id"]
        self.assertEqual(list(root.glob("*/source.json")), [])
        self.assertEqual(len(list(root.glob("*/FAILED.json"))), 1)

    def test_account_change_during_fetch_refuses_completed_manifest(self):
        result = self.search("file")
        def save(request):
            target = Path(request["target"])
            path = target / "fixture.txt"
            path.write_bytes(b"fixture")
            self.config["qq"]["account"] = "43"
            write_json(self.path, self.config)
            return {"files": [str(path)]}
        with patch.object(self.bridge, "worker", side_effect=save):
            with self.assertRaises(BridgeError):
                self.bridge.fetch(result["receipt_id"], "m1")
        self.assertEqual(list((self.bridge.output / result["receipt_id"]).glob("*/source.json")), [])

    def test_ambiguous_message_id_index_concatenations_keep_both_attachments(self):
        # ('m1', 10) and ('m11', 0) must not share the key 'm110'.
        self.rows = [dict(self.rows[0], id="m1", attachments=[{"kind": "file"}] * 11),
                     dict(self.rows[1], id="m11", attachments=[{"kind": "file"}])]
        result = self.search()
        first = self.fetch(result, "m1", 10)
        second = self.fetch(result, "m11", 0)
        left, right = (Path(item["files"][0]["path"]).parent.parent for item in (first, second))
        self.assertNotEqual(left.name.split("-")[0], right.name.split("-")[0])


if __name__ == "__main__":
    unittest.main()
