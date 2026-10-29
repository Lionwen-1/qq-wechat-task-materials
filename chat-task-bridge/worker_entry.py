"""Restrict scheduling of this disposable reader before loading any adapter."""
import json
import os
from pathlib import Path
import runpy
import sys

WORKERS = {"qq_db_worker.py", "wechat_db_worker.py", "scope_worker.py"}


def lower_priority():
    if os.name != "nt":
        return
    import psutil
    worker = psutil.Process()  # Never open a QQ / WeChat process for scheduling.
    worker.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    worker.ionice(psutil.IOPRIO_VERYLOW)
    if worker.nice() != psutil.BELOW_NORMAL_PRIORITY_CLASS or worker.ionice() != psutil.IOPRIO_VERYLOW:
        raise RuntimeError("Worker scheduling limits not applied")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in WORKERS:
        print(json.dumps({"ok": False, "error": "不允许的取材子进程"}, ensure_ascii=False))
        return 1
    try:
        lower_priority()
    except Exception:
        print(json.dumps({"ok": False, "error": "无法降低本桥读取子进程的CPU/磁盘优先级，未读取客户端"}, ensure_ascii=False))
        return 1
    runpy.run_path(str(Path(__file__).resolve().parent / sys.argv[1]), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
