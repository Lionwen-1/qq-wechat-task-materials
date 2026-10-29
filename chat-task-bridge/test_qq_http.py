"""Local fixture server: exercise the actual HTTP transport and attachment copy."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from bridge import Bridge, load_json, write_json


class QQHTTPTests(unittest.TestCase):
    def test_read_query_and_attachment_over_real_http(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            media = root / "media"
            media.mkdir()
            fixture = media / "fixture.txt"
            fixture.write_bytes(b"task attachment fixture")
            calls = []

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_POST(self):
                    data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    calls.append((self.path, data))
                    if self.path == "/get_login_info":
                        result = {"user_id": 42}
                    elif self.path == "/get_group_msg_history":
                        if data.get("message_seq"):
                            result = {"messages": []}
                        else:
                            result = {"messages": [{"message_id": 11, "time": 1790906400, "sender": {"nickname": "fixture"},
                                                     "message": [{"type": "text", "data": {"text": "assignment"}},
                                                                 {"type": "file", "data": {"file_id": "opaque-observed-id", "name": "fixture.txt"}}]}]}
                    elif self.path == "/get_file":
                        assert data == {"file": "opaque-observed-id"}
                        result = {"file": str(fixture), "file_name": "fixture.txt"}
                    else:
                        self.send_error(403)
                        return
                    body = json.dumps({"status": "ok", "retcode": 0, "data": result}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                config = load_json(Path(__file__).with_name("config.example.json"))
                config["qq"].update(enabled=True, account="42", backend="napcat", endpoint=f"http://127.0.0.1:{server.server_port}", media_roots=[str(media)])
                config["chats"] = {"allowed": {"platform": "qq", "kind": "group", "id": "100", "name": "fixture"}}
                path = root / "config.json"
                write_json(path, config)
                bridge = Bridge(path)
                search = bridge.search("allowed", "2026-10-01", "2026-10-02", "assignment", "transport fixture", scan_limit=5)
                self.assertEqual(len(search["messages"]), 1)
                result = bridge.fetch(search["receipt_id"], "11")
                self.assertEqual(Path(result["files"][0]["path"]).read_bytes(), fixture.read_bytes())
                actions = {c[0] for c in calls}
                self.assertEqual(actions, {"/get_login_info", "/get_group_msg_history", "/get_file"})
                history_calls = [c[1] for c in calls if c[0] == "/get_group_msg_history"]
                self.assertTrue(all(c["group_id"] == "100" and c["disable_get_url"] and not c["parse_mult_msg"] for c in history_calls))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
