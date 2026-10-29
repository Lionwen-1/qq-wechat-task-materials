"""Bind one running Weixin account without importing any UI library."""
import hashlib
import os
from pathlib import Path

from bridge import BridgeError


def inspect_identity(settings):
    import psutil
    import win32api
    processes = [p for p in psutil.process_iter(["name", "cmdline"]) if p.info["name"] == "Weixin.exe"
                 and not any("--type" in a for a in p.info["cmdline"] or [])]
    if len(processes) != 1:
        raise BridgeError("微信主进程未唯一确定，拒绝跨账号读取")
    process = processes[0]
    executable = os.path.normcase(os.path.abspath(settings.get("executable", "")))
    if os.path.normcase(process.exe()) != executable:
        raise BridgeError("运行的微信与绑定程序路径不符")
    raw = win32api.GetFileVersionInfo(executable, "\\")
    ms, ls = raw["FileVersionMS"], raw["FileVersionLS"]
    version = ".".join(map(str, (ms >> 16, ms & 65535, ls >> 16, ls & 65535)))
    if version != settings.get("client_version"):
        raise BridgeError("微信版本变化，需重新核验适配")
    folders = {os.path.normcase(os.path.normpath(os.path.dirname(m.path).replace("db_storage", "").replace("MMKV", "")))
               for m in process.memory_maps() if "MMKV" in m.path}
    if len(folders) != 1:
        raise BridgeError("微信进程映射的账号目录未唯一确定")
    account_dir = Path(next(iter(folders))).resolve()
    fingerprint = hashlib.sha256(os.path.normcase(os.path.abspath(account_dir)).encode("utf-8")).hexdigest()
    if fingerprint != settings.get("account_fingerprint"):
        raise BridgeError("微信登录账号与绑定不符")
    return {"pid": process.pid, "process_start": process.create_time(), "account_dir": str(account_dir),
            "account_fingerprint": fingerprint, "client_version": version}
