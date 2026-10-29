"""Local operator setup; only updates this bridge's config, never an AI client's."""
import argparse
import hashlib
import os
from pathlib import Path
import re

from bridge import BridgeError, ROOT, load_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config.local.json"))
    parser.add_argument("--qq-group", help="Explicit QQ group number to allow")
    parser.add_argument("--wechat-chat", help="Exact unique Weixin group display name to allow")
    parser.add_argument("--active-download", action="store_true", help="Enable scoped CDN retrieval for explicitly bound platforms")
    args = parser.parse_args()
    if not args.qq_group and not args.wechat_chat:
        parser.error("至少指定一个目标群，不支持自动加入全部会话")
    import psutil
    import win32api

    def process(name):
        rows = [p for p in psutil.process_iter(["name", "cmdline"]) if p.info["name"] == name
                and not any("--type" in a for a in p.info["cmdline"] or [])]
        if len(rows) != 1:
            raise BridgeError(name + " 主进程未唯一确定，请只登录要绑定的个人账号")
        return rows[0]

    def version(exe):
        info = win32api.GetFileVersionInfo(exe, "\\")
        ms, ls = info["FileVersionMS"], info["FileVersionLS"]
        return ".".join(map(str, (ms >> 16, ms & 65535, ls >> 16, ls & 65535)))

    path = Path(args.config).resolve()
    config = load_json(path if path.exists() else ROOT / "config.example.json")
    if args.qq_group:
        if not args.qq_group.isdigit():
            raise BridgeError("QQ群号必须为数字")
        proc = process("QQ.exe")
        paths = [p.path for p in proc.memory_maps() if "nt_db" in p.path.lower()]
        if not any(Path(p[:-4] if p.endswith(("-shm", "-wal")) else p).name == "nt_msg.db" for p in paths):
            paths += [p.path for p in proc.open_files() if "nt_db" in p.path.lower()]
        databases = {Path(p[:-4] if p.endswith(("-shm", "-wal")) else p).resolve() for p in paths}
        databases = {p for p in databases if p.name == "nt_msg.db" and p.is_file()}
        if len(databases) != 1:
            raise BridgeError("当前 QQ 打开的消息数据库未唯一确定")
        source = next(iter(databases))
        account = source.parents[2].name
        if not account.isdigit():
            raise BridgeError("未从当前 QQ 数据目录确定本人账号")
        config["qq"].update(enabled=True, backend="db_readonly", account=account, db_path=str(source), executable=proc.exe(), client_version=version(proc.exe()))
        from qq_session import kernel_binding
        config["qq"]["group_file_kernel"] = kernel_binding(config["qq"], {"pid": proc.pid})
        if args.active_download:
            config["qq"]["active_download"] = True
        config["chats"]["qq-work"] = {"platform": "qq", "kind": "group", "id": args.qq_group, "name": "QQ群" + args.qq_group}
    if args.wechat_chat:
        proc = process("Weixin.exe")
        folders = {os.path.normcase(os.path.normpath(os.path.dirname(m.path).replace("db_storage", "").replace("MMKV", "")))
                   for m in proc.memory_maps() if "MMKV" in m.path}
        if len(folders) != 1:
            raise BridgeError("当前微信账号目录未唯一确定")
        fingerprint = hashlib.sha256(os.path.normcase(os.path.abspath(next(iter(folders)))).encode()).hexdigest()
        config["wechat"].update(enabled=True, backend="db_readonly", executable=proc.exe(), client_version=version(proc.exe()), account_fingerprint=fingerprint)
        if args.active_download:
            config["wechat"]["active_download"] = True
        config["chats"]["wechat-work"] = {"platform": "wechat", "kind": "group", "id": args.wechat_chat, "name": args.wechat_chat}
    write_json(path, config)
    print("已绑定当前账号与明确指定的群；未读取聊天消息。请通过 search 完成真实读取验收。")


if __name__ == "__main__":
    main()
