"""Portable JSON CLI/MCP launcher; local paths are kept outside the shareable skill."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

SKILL = Path(__file__).resolve().parents[1]


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", default=os.environ.get("CHAT_TASK_BRIDGE_RUNTIME", str(SKILL / "runtime.local.json")))
    parser.add_argument("command", choices=["status", "rules", "resolve", "allow", "block", "unblock", "search", "fetch", "mcp"])
    args, remaining = parser.parse_known_args()
    try:
        runtime = Path(args.runtime)
        if runtime.is_file():
            settings = json.loads(runtime.read_text(encoding="utf-8-sig"))
            root = Path(settings["bridge_root"]).resolve()
            interpreter = Path(settings["python"]).resolve()
            config = Path(settings.get("config", str(root / "config.local.json"))).resolve()
        else:
            root = SKILL.parent / "chat-task-bridge"
            interpreter = root / ".venv/Scripts/python.exe"
            config = root / "config.local.json"
        if not interpreter.is_file() or not (root / "scope.py").is_file():
            raise ValueError("取材桥运行环境未配置：请按 references/cli-and-mcp.md 设置 runtime.local.json；不自动扫描磁盘或安装软件")
        if not config.is_file():
            if args.command == "status":
                config = root / "config.example.json"
            else:
                raise ValueError("本机账号／会话配置尚未建立，请先完成程序绑定")
        if args.command == "mcp":
            command = [str(interpreter), str(root / "mcp_server.py"), "--config", str(config)] + remaining
        elif args.command == "fetch":
            command = [str(interpreter), str(root / "bridge.py"), "--config", str(config), args.command] + remaining
        else:
            command = [str(interpreter), str(root / "scope.py"), "--config", str(config), args.command] + remaining
        names = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                 "PROGRAMDATA", "USERNAME", "USERDOMAIN", "HOMEDRIVE", "HOMEPATH"}
        environment = {k: v for k, v in os.environ.items() if k.upper() in names}
        environment.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        return subprocess.run(command, env=environment).returncode
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
