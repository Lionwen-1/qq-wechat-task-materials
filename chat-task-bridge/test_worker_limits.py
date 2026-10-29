import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from bridge import Bridge, BridgeError, file_lock, load_json, write_json
import worker_entry


class WorkerLimitsTests(unittest.TestCase):
    def test_priority_is_changed_only_for_current_bridge_process(self):
        import psutil
        process = MagicMock()
        process.nice.side_effect = lambda *args: None if args else psutil.BELOW_NORMAL_PRIORITY_CLASS
        process.ionice.side_effect = lambda *args: None if args else psutil.IOPRIO_VERYLOW
        with patch("psutil.Process", return_value=process) as lookup:
            worker_entry.lower_priority()
        lookup.assert_called_once_with()
        process.nice.assert_any_call(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        process.ionice.assert_any_call(psutil.IOPRIO_VERYLOW)

    def test_priority_failure_never_loads_adapter(self):
        stream = io.StringIO()
        with patch.object(sys, "argv", ["worker_entry.py", "qq_db_worker.py"]), patch.object(worker_entry, "lower_priority", side_effect=PermissionError), patch("runpy.run_path") as adapter, contextlib.redirect_stdout(stream):
            self.assertEqual(worker_entry.main(), 1)
        adapter.assert_not_called()
        self.assertFalse(json.loads(stream.getvalue())["ok"])

    def test_unknown_worker_denied_before_scheduling_or_loading(self):
        with patch.object(sys, "argv", ["worker_entry.py", "other.py"]), patch.object(worker_entry, "lower_priority") as limits, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(worker_entry.main(), 1)
        limits.assert_not_called()

    def test_actual_worker_startup_can_lower_priority_without_client_access(self):
        path = Path(__file__).with_name("worker_entry.py")
        run = subprocess.run([sys.executable, str(path), "scope_worker.py"], input='{"operation":"invalid","target":"fixture"}',
                             text=True, encoding="utf-8", capture_output=True,
                             env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}, timeout=15)
        body = json.loads(run.stdout)
        self.assertFalse(body["ok"])
        self.assertIn("精确群名", body["error"])
        self.assertNotIn("优先级", body["error"])

    def test_one_shared_lock_denies_cross_platform_overlap_before_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            write_json(path, load_json(Path(__file__).with_name("config.example.json")))
            bridge = Bridge(path)
            with file_lock(bridge.state / "client-access.lock"), patch("bridge.subprocess.run") as child:
                with self.assertRaises(BridgeError):
                    bridge.worker({"chat": {"platform": "wechat"}})
            child.assert_not_called()


if __name__ == "__main__":
    unittest.main()
