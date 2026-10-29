"""Named-group requests preserve explicit task scope and existing block rules."""
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from bridge import Bridge, BridgeError, load_json, write_json
from scope import Scope
from scope_worker import qq_groups, wechat_groups
from qq_db_worker import identity


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "config.json"
        self.config = load_json(Path(__file__).with_name("config.example.json"))
        self.config["qq"]["enabled"] = True
        self.config["wechat"]["enabled"] = True
        self.config["chats"] = {
            "course": {"platform": "qq", "kind": "group", "id": "100", "name": "课程群"},
            "wx": {"platform": "wechat", "kind": "group", "id": "wx@chatroom", "name": "课程群"}}
        write_json(self.path, self.config)
        self.bridge = Bridge(self.path)
        self.scope = Scope(self.bridge)

    def tearDown(self):
        self.temp.cleanup()

    def metadata(self, groups=None):
        return {"groups": groups or [{"platform": "qq", "kind": "group", "id": "200", "name": "新课程群", "remark": ""}],
                "metadata_only": True, "message_database_opened": False}

    def test_existing_group_name_uses_binding_without_reading_data(self):
        with patch.object(self.bridge, "worker") as worker:
            result = self.scope.locate("qq", "课程群")
            self.assertEqual(result["alias"], "course")
            self.assertTrue(result["allowed"])
            worker.assert_not_called()

    def test_exact_blocked_name_denies_before_metadata_lookup(self):
        self.config["blocked"] = ["qq:name:新课程群"]
        write_json(self.path, self.config)
        with patch.object(self.bridge, "worker") as worker:
            with self.assertRaises(BridgeError):
                self.scope.locate("qq", "新课程群")
            worker.assert_not_called()

    def test_resolved_blocked_id_denies_without_registering(self):
        self.config["blocked"] = ["qq:group:200"]
        write_json(self.path, self.config)
        with patch.object(self.bridge, "worker", return_value=self.metadata()) as worker:
            with self.assertRaises(BridgeError):
                self.scope.allow("qq", "新课程群", "用户交付任务")
            self.assertEqual(worker.call_args.args[0]["operation"], "resolve_group")
        self.assertEqual(load_json(self.path), self.config)

    def test_new_named_chat_search_does_not_implicitly_allow(self):
        with patch.object(self.bridge, "worker", return_value=self.metadata()), patch.object(self.bridge, "search") as search:
            with self.assertRaises(BridgeError):
                self.scope.search("qq", "新课程群", "用户任务")
            search.assert_not_called()
        self.assertEqual(load_json(self.path), self.config)

    def test_allow_adds_only_exact_target_and_preserves_blocks(self):
        self.config["blocked"] = ["qq:group:999", "wechat:name:排除群"]
        write_json(self.path, self.config)
        with patch.object(self.bridge, "worker", return_value=self.metadata()):
            result = self.scope.allow("qq", "新课程群", "用户点名整理作业")
        final = load_json(self.path)
        self.assertEqual(final["blocked"], self.config["blocked"])
        self.assertEqual(final["qq"], self.config["qq"])
        self.assertEqual(final["wechat"], self.config["wechat"])
        self.assertEqual(len(final["chats"]), 3)
        self.assertEqual(final["chats"][result["alias"]]["id"], "200")

    def test_rename_cannot_bypass_legacy_name_block(self):
        self.config["blocked"] = ["课程群"]
        write_json(self.path, self.config)
        group = {"platform": "qq", "kind": "group", "id": "100", "name": "新名字", "remark": ""}
        with patch.object(self.bridge, "worker", return_value=self.metadata([group])):
            with self.assertRaises(BridgeError):
                self.scope.allow("qq", "新名字", "用户任务")
        self.assertEqual(load_json(self.path), self.config)

    def test_ambiguous_name_does_not_write_allow_list(self):
        groups = self.metadata()["groups"] * 2
        groups[1] = dict(groups[1], id="201")
        with patch.object(self.bridge, "worker", return_value=self.metadata(groups)):
            with self.assertRaises(BridgeError):
                self.scope.allow("qq", "新课程群", "用户任务")
        self.assertEqual(load_json(self.path), self.config)

    def test_allow_requires_task_purpose_before_any_lookup(self):
        with patch.object(self.bridge, "worker") as worker:
            with self.assertRaises(BridgeError):
                self.scope.allow("qq", "新群", " ")
            worker.assert_not_called()

    def test_empty_search_purpose_denied_before_metadata_lookup(self):
        with patch.object(self.bridge, "worker") as worker:
            with self.assertRaises(BridgeError):
                self.scope.search("qq", "新群", " ")
            worker.assert_not_called()

    def test_mapped_account_database_avoids_unrelated_deleted_handles(self):
        proc = MagicMock()
        proc.info = {"name": "QQ.exe", "cmdline": ["QQ.exe"]}
        proc.pid = 123
        executable = str(Path(self.temp.name) / "QQ.exe")
        source = str(Path(self.temp.name) / "42/nt_qq/nt_db/nt_msg.db")
        proc.exe.return_value = executable
        proc.memory_maps.return_value = [type("Mapping", (), {"path": source + "-shm"})()]
        proc.open_files.side_effect = PermissionError("unrelated deleted NTFS file")
        proc.create_time.return_value = 1
        settings = {"executable": executable, "account": "42", "db_path": source, "client_version": "9.9.35.52892"}
        version = {"FileVersionMS": 9 * 65536 + 9, "FileVersionLS": 35 * 65536 + 52892}
        with patch("psutil.process_iter", return_value=[proc]), patch("win32api.GetFileVersionInfo", return_value=version):
            self.assertEqual(identity(settings)["pid"], 123)
        proc.open_files.assert_not_called()

    def test_database_directory_alias_matches_the_same_bound_file(self):
        real = Path(self.temp.name) / "real"
        real.mkdir()
        alias = Path(self.temp.name) / "alias"
        result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(alias), str(real)],
                                capture_output=True)
        self.assertEqual(result.returncode, 0)
        source = real / "42/nt_qq/nt_db/nt_msg.db"
        source.parent.mkdir(parents=True)
        source.touch()
        mapped = alias / "42/nt_qq/nt_db/nt_msg.db-shm"
        proc = MagicMock()
        proc.info = {"name": "QQ.exe", "cmdline": ["QQ.exe"]}
        proc.pid = 123
        executable = str(real / "QQ.exe")
        proc.exe.return_value = executable
        proc.memory_maps.return_value = [type("Mapping", (), {"path": str(mapped)})()]
        proc.open_files.side_effect = PermissionError("unrelated deleted NTFS file")
        proc.create_time.return_value = 1
        settings = {"executable": executable, "account": "42", "db_path": str(source), "client_version": "9.9.35.52892"}
        version = {"FileVersionMS": 9 * 65536 + 9, "FileVersionLS": 35 * 65536 + 52892}
        with patch("psutil.process_iter", return_value=[proc]), patch("win32api.GetFileVersionInfo", return_value=version):
            self.assertEqual(identity(settings)["source"], str(source.resolve()))
        proc.open_files.assert_not_called()

    def test_canonical_paths_still_reject_another_database(self):
        proc = MagicMock()
        proc.info = {"name": "QQ.exe", "cmdline": ["QQ.exe"]}
        proc.pid = 123
        executable = str(Path(self.temp.name) / "QQ.exe")
        source = str(Path(self.temp.name) / "bound/42/nt_qq/nt_db/nt_msg.db")
        other = str(Path(self.temp.name) / "other/42/nt_qq/nt_db/nt_msg.db-shm")
        proc.exe.return_value = executable
        proc.memory_maps.return_value = [type("Mapping", (), {"path": other})()]
        proc.open_files.return_value = []
        settings = {"executable": executable, "account": "42", "db_path": source, "client_version": "9.9.35.52892"}
        version = {"FileVersionMS": 9 * 65536 + 9, "FileVersionLS": 35 * 65536 + 52892}
        with patch("psutil.process_iter", return_value=[proc]), patch("win32api.GetFileVersionInfo", return_value=version):
            with self.assertRaises(BridgeError):
                identity(settings)

    def test_unbound_group_can_be_blocked_without_open_client(self):
        with patch.object(self.bridge, "worker") as worker:
            self.scope.change_block("qq", "未知群", True, "用户要求屏蔽")
            worker.assert_not_called()
        self.assertIn("qq:name:未知群", load_json(self.path)["blocked"])

    def test_known_group_block_survives_alias_and_name_changes(self):
        self.scope.change_block("qq", "课程群", True, "用户要求屏蔽")
        config = load_json(self.path)
        config["chats"]["renamed"] = dict(config["chats"]["course"], name="改过的名字")
        write_json(self.path, config)
        with self.assertRaises(BridgeError):
            self.bridge.chat("renamed")
        self.assertEqual(self.bridge.chat("wx")["platform"], "wechat")

    def test_remark_name_block_applies_through_another_alias(self):
        self.config["chats"]["course"]["remark"] = "我的课程备注"
        self.config["blocked"] = ["qq:name:我的课程备注"]
        write_json(self.path, self.config)
        with self.assertRaises(BridgeError):
            self.bridge.chat("course")

    def test_unblock_does_not_clear_unrelated_or_legacy_global_rules(self):
        self.config["blocked"] = ["qq:group:100", "qq:group:999", "课程群"]
        write_json(self.path, self.config)
        self.scope.change_block("qq", "课程群", False, "用户明确解除这个群的屏蔽")
        self.assertEqual(load_json(self.path)["blocked"], ["qq:group:999", "课程群"])
        with self.assertRaises(BridgeError):
            self.bridge.chat("course")

    def test_search_passes_one_group_and_concrete_date_scope(self):
        with patch.object(self.bridge, "search", return_value={"messages": [], "coverage": {}}) as search:
            result = self.scope.search("qq", "课程群", "整理作业")
            args = search.call_args.args
            self.assertEqual(args[0], "course")
            self.assertEqual(args[4], "整理作业")
            self.assertEqual(result["scope"]["timezone"], "Asia/Shanghai")

    def test_explicit_end_date_sets_default_seven_day_window(self):
        with patch.object(self.bridge, "search", return_value={}) as search:
            self.scope.search("qq", "课程群", "整理作业", end="2026-10-15")
            self.assertEqual(search.call_args.args[1:3], ("2026-10-09", "2026-10-15"))

    def test_contact_lookup_is_exact_and_never_needs_message_tables(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute('CREATE TABLE group_list("60001","60007","60026")')
        c.executemany('INSERT INTO group_list VALUES(?,?,?)', [(100, "课程群", ""), (200, "课程群大群", "")])
        self.assertEqual([r["id"] for r in qq_groups(c, "课程群")], ["100"])
        self.assertEqual(qq_groups(c, "' OR 1=1 --"), [])
        c.execute("CREATE TABLE contact(username,nick_name,remark)")
        c.executemany("INSERT INTO contact VALUES(?,?,?)", [("g@chatroom", "课程群", ""), ("private-user", "课程群", "")])
        self.assertEqual([r["id"] for r in wechat_groups(c, "课程群")], ["g@chatroom"])
        c.close()


if __name__ == "__main__":
    unittest.main()
