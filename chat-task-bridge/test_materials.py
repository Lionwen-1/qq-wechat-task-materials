"""Offline materials preserve query scope, revoke access and verify portable bytes."""
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from bridge import Bridge, BridgeError, QQ, load_json, write_json


class MaterialsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "config.json"
        self.config = load_json(Path(__file__).with_name("config.example.json"))
        self.config["qq"].update(enabled=True, backend="napcat", account="42")
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
        with patch.object(QQ, "history", return_value=(self.rows, {"upstream_exhausted": True})):
            return self.bridge.search("course", "2026-10-29", "2026-10-29", "", "用户要求整理实验材料", result_limit=result_limit, attachment_kind=kind)

    def fetch(self, result, message="m1", index=0, body=b"fixture", name="同名.txt"):
        def save(settings, attachment, target, maximum):
            path = target / name
            path.write_bytes(body)
            return [path]
        with patch("bridge.save_qq_attachment", side_effect=save):
            return self.bridge.fetch(result["receipt_id"], message, index)

    def test_versioned_query_contract_and_coverage_are_persisted(self):
        result = self.search(result_limit=1)
        self.assertEqual(result["schema"], "chat-task-messages/v1")
        self.assertEqual(result["scope"]["timezone"], "Asia/Shanghai")
        self.assertEqual(result["coverage"]["returned"], 1)
        self.assertTrue(result["coverage"]["may_have_more"])
        stored = load_json(self.bridge.state / "receipts" / (result["receipt_id"] + ".json"))
        self.assertEqual(stored["coverage"], result["coverage"])
        self.assertNotIn("_evidence", result["messages"][0])

    def test_image_filter_preserves_original_indices_and_revokes_other_kinds(self):
        result = self.search("image")
        self.assertEqual([r["id"] for r in result["messages"]], ["m1", "m2"])
        self.assertEqual(result["messages"][0]["matched_attachment_indices"], [1])
        with patch("bridge.save_qq_attachment") as download:
            with self.assertRaises(BridgeError):
                self.bridge.fetch(result["receipt_id"], "m1", 0)
            download.assert_not_called()

    def test_file_and_any_filters_only_select_matching_messages(self):
        self.assertEqual([r["id"] for r in self.search("file")["messages"]], ["m1"])
        self.assertEqual([r["id"] for r in self.search("any")["messages"]], ["m1", "m2"])

    def test_invalid_attachment_filter_denies_before_data_source(self):
        with patch.object(QQ, "history") as read:
            with self.assertRaises(BridgeError):
                self.bridge.search("course", "2026-10-29", "2026-10-29", "", "用户任务", attachment_kind="invalid")
            read.assert_not_called()

    def test_missing_materials_preview_never_reads_clients_or_fetches(self):
        result = self.search()
        with patch.object(self.bridge, "worker", side_effect=AssertionError), patch.object(QQ, "call", side_effect=AssertionError), patch("psutil.Process", side_effect=AssertionError):
            preview = self.bridge.materials(result["receipt_id"])
        self.assertEqual(preview["coverage"]["attachments"], 3)
        self.assertEqual(preview["coverage"]["unavailable"], 3)
        self.assertFalse(preview["client_access"] or preview["network_access"] or preview["files_copied"])
        self.assertFalse((self.bridge.output / result["receipt_id"]).exists())

    def test_portable_bundle_verifies_bytes_and_uses_literal_chat_text(self):
        result = self.search()
        self.fetch(result, name="same[1].txt")
        self.fetch(result, "m2", name="same[1].txt")
        with patch.object(self.bridge, "worker", side_effect=AssertionError), patch.object(QQ, "call", side_effect=AssertionError):
            bundle = self.bridge.materials(result["receipt_id"], write_bundle=True)
        folder = Path(bundle["bundle"]["directory"])
        saved = load_json(folder / "materials.json")
        self.assertEqual(saved["coverage"]["ready"], 2)
        self.assertEqual(saved["coverage"]["unavailable"], 1)
        self.assertEqual(saved["coverage"]["verified_bytes"], 14)
        paths = [f["path"] for m in saved["materials"] for f in m["files"]]
        self.assertEqual(len(paths), len(set(paths)))
        for name in paths:
            self.assertEqual((folder / name).read_bytes(), b"fixture")
        text = (folder / "materials.md").read_text(encoding="utf-8")
        self.assertIn("````text", text)
        self.assertIn("[保存的附件](assets/", text)
        self.assertNotIn(str(self.root), json.dumps(saved, ensure_ascii=False))
        self.assertNotIn("synthetic-private", json.dumps(saved))
        self.assertNotIn("hidden", json.dumps(saved))

    def test_message_subset_and_empty_or_unseen_selection(self):
        result = self.search()
        self.fetch(result)
        preview = self.bridge.materials(result["receipt_id"], ["m2"])
        self.assertEqual(preview["coverage"]["attachments"], 1)
        self.assertEqual([r["id"] for r in preview["messages"]], ["m2"])
        for selection in ([], ["other"], ["m1", "m1"]):
            with self.assertRaises(BridgeError):
                self.bridge.materials(result["receipt_id"], selection)

    def test_new_block_revokes_preview_and_export(self):
        result = self.search()
        self.fetch(result)
        self.config["blocked"] = ["qq:group:100"]
        write_json(self.path, self.config)
        for write in (False, True):
            with self.assertRaises(BridgeError):
                self.bridge.materials(result["receipt_id"], write_bundle=write)
        self.assertEqual(list((self.bridge.output / result["receipt_id"]).glob("bundle-*")), [])

    def test_account_rebind_revokes_old_receipt_without_client_access(self):
        result = self.search()
        self.config["qq"]["account"] = "43"
        write_json(self.path, self.config)
        with patch.object(self.bridge, "worker", side_effect=AssertionError):
            with self.assertRaises(BridgeError):
                self.bridge.materials(result["receipt_id"], write_bundle=True)

    def test_expired_or_legacy_receipt_refuses_export(self):
        result = self.search()
        path = self.bridge.state / "receipts" / (result["receipt_id"] + ".json")
        stored = load_json(path)
        stored.pop("binding_digest")
        write_json(path, stored)
        with self.assertRaises(BridgeError):
            self.bridge.materials(result["receipt_id"])
        stored["created_at"] -= 3601
        write_json(path, stored)
        with self.assertRaises(BridgeError):
            self.bridge.materials(result["receipt_id"])

    def test_tampered_same_size_file_is_not_exported_or_counted_verified(self):
        result = self.search("file")
        manifest = self.fetch(result)
        Path(manifest["files"][0]["path"]).write_bytes(b"changed")
        bundle = self.bridge.materials(result["receipt_id"], write_bundle=True)
        self.assertEqual(bundle["coverage"]["ready"], 0)
        self.assertEqual(bundle["coverage"]["verified_bytes"], 0)
        self.assertEqual(bundle["materials"][0]["reason"], "saved_file_hash_mismatch")
        self.assertEqual(list((Path(bundle["bundle"]["directory"]) / "assets").iterdir()), [])

    def test_forged_manifest_cannot_copy_an_outside_file(self):
        result = self.search("file")
        manifest = self.fetch(result)
        outside = self.root / "private.txt"
        outside.write_bytes(b"fixture")
        manifest["files"][0]["path"] = str(outside)
        path = next((self.bridge.output / result["receipt_id"]).glob("*/source.json"))
        write_json(path, manifest)
        preview = self.bridge.materials(result["receipt_id"])
        self.assertEqual(preview["coverage"]["ready"], 0)

    def test_source_from_another_receipt_or_index_is_not_accepted(self):
        result = self.search("file")
        manifest = self.fetch(result)
        path = next((self.bridge.output / result["receipt_id"]).glob("*/source.json"))
        manifest["receipt_id"] = "0" * 32
        write_json(path, manifest)
        self.assertEqual(self.bridge.materials(result["receipt_id"])["coverage"]["ready"], 0)
        manifest["receipt_id"] = result["receipt_id"]
        manifest["attachment_index"] = 1
        write_json(path, manifest)
        self.assertEqual(self.bridge.materials(result["receipt_id"])["coverage"]["ready"], 0)

    def test_revocation_during_copy_removes_staging_bundle(self):
        result = self.search("file")
        self.fetch(result)
        from material_bundle import copy_verified
        def revoke(*args):
            copy_verified(*args)
            self.config["blocked"] = ["qq:group:100"]
            write_json(self.path, self.config)
        with patch("material_bundle.copy_verified", side_effect=revoke):
            with self.assertRaises(BridgeError):
                self.bridge.materials(result["receipt_id"], write_bundle=True)
        root = self.bridge.output / result["receipt_id"]
        self.assertEqual(list(root.glob("bundle-*")) + list(root.glob(".materials-*")), [])

    def test_bundle_byte_budget_reports_unavailable_without_copying(self):
        result = self.search("file")
        self.fetch(result, body=b"x" * (1024 * 1024 + 1))
        self.config["max_attachment_mb"] = 1
        write_json(self.path, self.config)
        preview = self.bridge.materials(result["receipt_id"])
        self.assertEqual(preview["coverage"]["ready"], 0)

    def test_total_byte_budget_keeps_one_copy_and_reports_the_other(self):
        result = self.search()
        self.fetch(result, body=b"x" * 700000)
        self.fetch(result, "m2", body=b"x" * 700000)
        self.config["max_attachment_mb"] = 1
        write_json(self.path, self.config)
        preview = self.bridge.materials(result["receipt_id"])
        self.assertEqual(preview["coverage"]["ready"], 1)
        self.assertEqual(preview["coverage"]["verified_bytes"], 700000)
        self.assertIn("per_call_byte_budget_exceeded", [m.get("reason") for m in preview["materials"]])

    def test_total_file_budget_does_not_expand_export_indefinitely(self):
        result = self.search()
        self.fetch(result)
        self.fetch(result, "m2")
        with patch("material_bundle.MAX_FILES", 1):
            preview = self.bridge.materials(result["receipt_id"])
        self.assertEqual(preview["coverage"]["ready"], 1)
        self.assertIn("per_call_file_budget_exceeded", [m.get("reason") for m in preview["materials"]])

    def test_block_during_query_prevents_return_and_new_receipt(self):
        def read(*args):
            self.config["blocked"] = ["qq:group:100"]
            write_json(self.path, self.config)
            return self.rows, {"upstream_exhausted": True}
        with patch.object(QQ, "history", side_effect=read):
            with self.assertRaises(BridgeError):
                self.bridge.search("course", "2026-10-29", "2026-10-29", "", "用户任务")
        self.assertEqual(list((self.bridge.state / "receipts").glob("*.json")), [])

    def test_account_change_during_query_does_not_relabel_old_messages(self):
        def read(*args):
            self.config["qq"]["account"] = "43"
            write_json(self.path, self.config)
            return self.rows, {"upstream_exhausted": True}
        with patch.object(QQ, "history", side_effect=read):
            with self.assertRaises(BridgeError):
                self.bridge.search("course", "2026-10-29", "2026-10-29", "", "用户任务")

    def test_block_during_fetch_marks_output_incomplete(self):
        result = self.search("file")
        def save(settings, attachment, target, maximum):
            path = target / "fixture.txt"
            path.write_bytes(b"fixture")
            self.config["blocked"] = ["qq:group:100"]
            write_json(self.path, self.config)
            return [path]
        with patch("bridge.save_qq_attachment", side_effect=save):
            with self.assertRaises(BridgeError):
                self.bridge.fetch(result["receipt_id"], "m1")
        root = self.bridge.output / result["receipt_id"]
        self.assertEqual(list(root.glob("*/source.json")), [])
        self.assertEqual(len(list(root.glob("*/FAILED.json"))), 1)

    def test_account_change_during_fetch_refuses_completed_manifest(self):
        result = self.search("file")
        def save(settings, attachment, target, maximum):
            path = target / "fixture.txt"
            path.write_bytes(b"fixture")
            self.config["qq"]["account"] = "43"
            write_json(self.path, self.config)
            return [path]
        with patch("bridge.save_qq_attachment", side_effect=save):
            with self.assertRaises(BridgeError):
                self.bridge.fetch(result["receipt_id"], "m1")
        self.assertEqual(list((self.bridge.output / result["receipt_id"]).glob("*/source.json")), [])

    def test_growing_file_read_stops_after_expected_size_plus_one(self):
        from material_bundle import matches_saved_file
        class Recording(io.BytesIO):
            def read(self, size=-1):
                self.sizes.append(size)
                return super().read(size)
        stream = Recording(b"x" * 100000)
        stream.sizes = []
        path = MagicMock()
        path.open.return_value = stream
        self.assertFalse(matches_saved_file(path, {"bytes": 7, "sha256": "0" * 64}))
        self.assertEqual(stream.sizes, [8])

    def test_ambiguous_message_id_index_concatenations_keep_both_attachments(self):
        # ('m1', 10) and ('m11', 0) must not share the key 'm110'.
        self.rows = [dict(self.rows[0], id="m1", attachments=[{"kind": "file"}] * 11),
                     dict(self.rows[1], id="m11", attachments=[{"kind": "file"}])]
        result = self.search()
        self.assertEqual(self.bridge.materials(result["receipt_id"])["coverage"]["attachments"], 12)


if __name__ == "__main__":
    unittest.main()
