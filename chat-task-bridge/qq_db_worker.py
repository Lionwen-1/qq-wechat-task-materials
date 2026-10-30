"""QQNT direct read-only adapter. No injection, login, GUI, or persistent keys."""
from __future__ import annotations
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from datetime import date, datetime, timedelta

from bridge import BridgeError, ROOT, TZ
from merged_records import qq_card

VENDOR = ROOT / "vendor/qqnt_readonly"


def module(name):
    spec = importlib.util.spec_from_file_location("bridge_qq_" + name, VENDOR / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def identity(settings):
    import psutil
    import win32api
    def canonical(path):
        # Resolve short (8.3) paths and directory aliases on both sides. The
        # bound source already uses Path.resolve(); abspath alone is asymmetric.
        return os.path.normcase(str(Path(path).resolve()))

    expected_exe = canonical(settings.get("executable", ""))
    candidates = [p for p in psutil.process_iter(["name", "cmdline"]) if p.info["name"] == "QQ.exe"
                  and not any("--type" in a for a in p.info["cmdline"] or [])
                  and canonical(p.exe()) == expected_exe]
    if len(candidates) != 1:
        raise BridgeError("当前个人 QQ 主进程未唯一确定")
    raw = win32api.GetFileVersionInfo(expected_exe, "\\")
    ms, ls = raw["FileVersionMS"], raw["FileVersionLS"]
    version = ".".join(map(str, (ms >> 16, ms & 65535, ls >> 16, ls & 65535)))
    if version != settings.get("client_version"):
        raise BridgeError("QQ 版本变化，需重新核验只读适配")
    source = Path(settings.get("db_path", "")).resolve()
    account = str(settings.get("account", ""))
    if not account or account not in source.parts or source.name != "nt_msg.db":
        raise BridgeError("QQ 数据库路径未绑定本人账号")
    process = candidates[0]
    paths = [p.path for p in process.memory_maps() if "nt_db" in p.path.lower()]
    mapped = {canonical(p[:-4] if p.endswith(("-shm", "-wal")) else p) for p in paths}
    if canonical(source) not in mapped:
        try:
            paths = [p.path for p in process.open_files() if "nt_db" in p.path.lower()]
        except psutil.AccessDenied:
            raise BridgeError("无法从 QQ 当前映射或句柄核验绑定数据库") from None
        mapped.update(canonical(p[:-4] if p.endswith(("-shm", "-wal")) else p) for p in paths)
    if canonical(source) not in mapped:
        raise BridgeError("绑定数据库不是当前 QQ 打开的数据库")
    return {"pid": process.pid, "process_start": process.create_time(), "source": str(source), "version": version}


def snapshot(source, destination):
    def stat(p):
        try:
            s = p.stat()
            return s.st_size, s.st_mtime_ns
        except FileNotFoundError:
            return None
    wal = Path(str(source) + "-wal")
    need = source.stat().st_size + (wal.stat().st_size if wal.exists() else 0) + 100 * 1024 * 1024
    if shutil.disk_usage(destination.parent).free < need:
        raise BridgeError("QQ 临时加密快照需要更多磁盘空间")
    for _ in range(3):
        before = stat(source)
        with source.open("rb") as src, destination.open("wb") as out:
            src.seek(1024)
            shutil.copyfileobj(src, out, 8 * 1024 * 1024)
        target_wal = Path(str(destination) + "-wal")
        if target_wal.exists():
            target_wal.unlink()
        consistent = True
        try:
            with wal.open("rb") as stream:
                mark = os.fstat(stream.fileno())
                length = mark.st_size
                header = stream.read(min(32, length))
                stream.seek(0)
                # Copy a bounded WAL prefix. Normal appends do not invalidate
                # it: SQLite validates frame checksums and ignores uncommitted
                # or incomplete tails. A reset/replacement/checkpoint does.
                with target_wal.open("wb") as out:
                    remaining = length
                    while remaining:
                        block = stream.read(min(1024 * 1024, remaining))
                        if not block:
                            consistent = False
                            break
                        out.write(block)
                        remaining -= len(block)
                stream.seek(0)
                same_header = stream.read(min(32, length)) == header
                current = wal.stat()
                consistent = consistent and same_header and (mark.st_dev, mark.st_ino) == (current.st_dev, current.st_ino)
        except FileNotFoundError:
            consistent = not target_wal.exists()
        if consistent and before == stat(source):
            return
        time.sleep(0.2)
    raise BridgeError("QQ 正在写入，未取得稳定快照，请稍后重试")


def open_db(settings, info, scratch):
    scan = module("key_scan")
    source = Path(info["source"])
    salt = scan.read_salt(str(source)).hex()
    result = scan.scan_pid(info["pid"], salt, [""] * 40)
    keys = {h["key_hex"].lower() for h in result.get("hits", []) if h.get("salt_match")}
    if not keys:
        raise BridgeError("未取得与本人 QQ 数据库盐值匹配的只读凭据")
    destination = scratch / "nt_msg.encrypted.db"
    snapshot(source, destination)
    from sqlcipher3 import dbapi2 as sqlcipher
    for key in keys:
        if not re.fullmatch("[a-f0-9]{64}", key) or not re.fullmatch("[a-f0-9]{32}", salt):
            continue
        conn = sqlcipher.connect(destination.as_uri() + "?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA cipher_page_size=4096")
            conn.execute("PRAGMA key=\"x'" + key + salt + "'\"")
            conn.execute("PRAGMA cipher_hmac_algorithm=HMAC_SHA1")
            conn.execute("PRAGMA query_only=ON")
            conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='group_msg_table'").fetchone()
            conn.row_factory = sqlcipher.Row
            return conn
        except sqlcipher.DatabaseError:
            conn.close()
    raise BridgeError("QQ 只读数据库凭据未通过 SQLCipher 页面校验")


def select_rows(conn, request, message_id=None):
    chat = request["chat"]
    if chat["kind"] != "group" or not str(chat["id"]).isdigit():
        raise BridgeError("QQ 直接读取首版仅开放明确群号")
    columns = '"40001" msg_id,"40050" ts,"40020" sender_uid,"40033" sender_qq,"40011" msg_type,"40090" card,"40093" nick,"40800" blob'
    sql = "SELECT " + columns + ' FROM group_msg_table WHERE "40021" IN (?,?)'
    args = [chat["id"], int(chat["id"])]
    if message_id is not None:
        sql += ' AND "40001" IN (?,?)'
        args.extend([str(message_id), int(message_id)])
    else:
        start = datetime.combine(date.fromisoformat(request["start_date"]), datetime.min.time(), TZ).timestamp()
        end = datetime.combine(date.fromisoformat(request["end_date"]) + timedelta(days=1), datetime.min.time(), TZ).timestamp()
        sql += ' AND "40050">=? AND "40050"<? ORDER BY "40050" DESC,"40001" DESC LIMIT ?'
        args.extend([int(start), int(end), request["scan_limit"]])
    return conn.execute(sql, args).fetchall()


def parse_row(row, parser):
    segments, error = parser.parse_40800(row["blob"] or b"")
    if error:
        raise BridgeError("QQ 指定消息体解析失败，未返回空文本")
    content = parser.build_content(row["msg_type"], segments)
    attachments = []
    for i, segment in enumerate(segments):
        converted = parser.segment_of(segment)
        if converted.get("type") in {"image", "file", "video"}:
            attachments.append({"kind": converted["type"], "name": segment.get("filename") or "", "bytes": segment.get("filesize"), "_segment": i})
    result = {"id": str(row["msg_id"]), "time": row["ts"], "sender": row["card"] or row["nick"] or row["sender_qq"] or row["sender_uid"] or "unknown",
            "text": parser.content_preview(content), "kind": (content or {}).get("type", "unknown"), "attachments": attachments,
            "_qq_blob_sha256": hashlib.sha256(row["blob"] or b"").hexdigest(), "_qq_segments": segments}
    card = qq_card(segments)
    if card:
        result.update(kind="forward", text="[合并聊天记录] " + card["title"] + "\n" + card["preview"],
                      merged_record={"available": True, "state": "preview_only", "complete": False})
    return result


def read_record(row, request, info):
    if row["_qq_blob_sha256"] != request["row"].get("_qq_blob_sha256"):
        raise BridgeError("QQ 原消息内容已变化，请重新查询")
    card = qq_card(row["_qq_segments"])
    if not card:
        raise BridgeError("指定 QQ 消息不是可展开的合并聊天记录")
    from qq_forward import fetch_record
    return fetch_record(card, request, info, module("key_scan"))


def fetch(row, request):
    segments = row["_qq_segments"]
    expected = request["row"]
    if row["_qq_blob_sha256"] != expected.get("_qq_blob_sha256"):
        raise BridgeError("QQ 原消息内容已变化，请重新查询")
    index = int(request.get("attachment_index", 0))
    attachment = row["attachments"][index]
    segment = segments[attachment["_segment"]]
    account_root = Path(request["settings"]["db_path"]).resolve().parents[2]
    allowed = [account_root] + [Path(p).resolve() for p in request["settings"].get("media_roots", [])]
    candidates = []
    for field in ("filepath", "local_path", "ntos_path"):
        value = segment.get(field)
        if value:
            p = Path(value).resolve()
            if p.is_file() and any(p.is_relative_to(root) for root in allowed):
                candidates.append(p)
    md5 = segment.get("md5_hex") or ""
    if not re.fullmatch(r"[a-fA-F0-9]{32}", md5):
        raise BridgeError("QQ 附件缺少可校验的来源 MD5")
    if not candidates:
        # QQ often stores no path in received-file messages. Look only for this
        # observed filename/hash in known caches, then verify bytes against MD5.
        names = {str(segment.get("filename") or "").casefold()}
        cache_roots = [account_root / "FileRecv", account_root / "nt_qq/nt_data/File",
                       account_root / "nt_qq/nt_data/Pic"]
        for root in cache_roots:
            if not root.is_dir():
                continue
            for directory, _, files in os.walk(root, followlinks=False):
                for name in files:
                    if name.casefold() in names or Path(name).stem.casefold() == md5.casefold():
                        p = Path(directory, name).resolve()
                        if p.is_relative_to(root.resolve()) and p not in candidates:
                            candidates.append(p)
            if len(candidates) > 20:
                break
    for p in candidates:
        if p.stat().st_size > int(request.get("maximum_bytes", 100 * 1024 * 1024)):
            raise BridgeError("QQ 附件超过大小上限")
        if hashlib.md5(p.read_bytes()).hexdigest().lower() != md5.lower():
            continue
        if attachment["kind"] == "image":
            from privacy import verify_image
            verify_image(p)
        out = Path(request["target"]) / p.name
        shutil.copyfile(p, out)
        return {"files": [str(out)], "media_tier": "source_verified", "source_digest_verified": True}
    if attachment["kind"] == "image":
        from qq_cdn import fetch_image
        return fetch_image(segment, request, identity(request["settings"])["pid"], module("key_scan"))
    if attachment["kind"] == "file":
        from qq_group_file import fetch_group_file
        return fetch_group_file(segment, request, identity(request["settings"]), module("key_scan"))
    raise BridgeError("QQ 此附件类型尚不支持后台取回")


def main():
    request = json.load(sys.stdin)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            info = identity(request["settings"])
            parser = module("msg_parser")
            with contextlib.closing(open_db(request["settings"], info, Path(request["scratch"]))) as conn:
                if request["operation"] == "search":
                    rows = [parse_row(r, parser) for r in select_rows(conn, request)]
                    result = {"rows": rows, "coverage": {"source": "qqnt_db_readonly", "date_filter": "selected_group_sql",
                              "process_write": False, "key_persistence": False, "plaintext_db_persistence": False,
                              "snapshot_lifetime": "request_only", "upstream_exhausted": len(rows) < request["scan_limit"]}}
                elif request["operation"] in {"fetch", "read_record"}:
                    rows = select_rows(conn, request, request["row"]["id"])
                    if len(rows) != 1:
                        raise BridgeError("QQ 原消息未唯一定位")
                    row = parse_row(rows[0], parser)
                    result = read_record(row, request, info) if request["operation"] == "read_record" else fetch(row, request)
                else:
                    raise BridgeError("QQ 只读适配不支持此操作")
            if identity(request["settings"]) != info:
                raise BridgeError("QQ 操作期间账号或进程变化，拒绝返回")
        payload = {"ok": True, "result": result}
    except BridgeError as exc:
        payload = {"ok": False, "error": str(exc)}
    except Exception as exc:
        payload = {"ok": False, "error": "QQ 只读数据库适配失败：" + type(exc).__name__}
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
