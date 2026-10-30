"""Scoped Weixin DB reader. ReadProcessMemory only; never imports GUI modules."""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
import sys
import time
import types
from datetime import date, datetime, timedelta

from bridge import BridgeError, ROOT, TZ, sha256_file
from wechat_identity import inspect_identity
from privacy import verify_image
from merged_records import descriptor_digest, wechat_record, render, xml

VENDOR = ROOT / "vendor/wechatauto_readonly"


def card_xml(text):
    """Group messages can prefix XML with the sender's username and a newline."""
    return xml(text)


def public_content(local_type, text):
    # Media XML can contain per-attachment AES keys and CDN capability IDs.
    # Re-read it from the scoped database only during fetch, never return/cache
    # those credentials as message text for an agent.
    return {3: "[图片]", 34: "[语音]", 43: "[视频]", 47: "[表情]"}.get(local_type, text)


def load_read_modules():
    pkg = types.ModuleType("wechatauto")
    pkg.__path__ = [str(VENDOR)]
    sys.modules["wechatauto"] = pkg
    logger = types.ModuleType("wechatauto.logger")
    logger.wxlog = logging.getLogger("chat_bridge_readonly_vendor")
    logger.wxlog.disabled = True
    sys.modules["wechatauto.logger"] = logger
    modules = []
    for name in ("db", "media"):
        spec = importlib.util.spec_from_file_location("wechatauto." + name, VENDOR / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        setattr(pkg, name, module)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def signature(path):
    try:
        st = path.stat()
        return st.st_size, st.st_mtime_ns
    except FileNotFoundError:
        return None


def stable_encrypted_copy(source, target):
    wal = Path(str(source) + "-wal")
    for _ in range(4):
        before = (signature(source), signature(wal))
        if before[0] is None:
            raise BridgeError("目标微信数据库已变化，请重新发起查询")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        dest_wal = Path(str(target) + "-wal")
        if before[1]:
            shutil.copyfile(wal, dest_wal)
        elif dest_wal.exists():
            dest_wal.unlink()
        if before == (signature(source), signature(wal)):
            return
        time.sleep(0.2)
    raise BridgeError("微信正在写数据库，未取得稳定快照；请稍后重试")


def authenticated_page(module, key, salt, page, number):
    if len(page) != module.PAGE_SZ:
        raise BridgeError("微信数据库存在不完整页")
    actual = key[:32]
    salt = key[32:] if len(key) == 48 else salt
    mac_key = hashlib.pbkdf2_hmac("sha512", actual, bytes(b ^ 0x3A for b in salt), 2, 32)
    start = 16 if number == 1 else 0
    expected = hmac.new(mac_key, page[start:4032] + struct.pack("<I", number), hashlib.sha512).digest()
    if not hmac.compare_digest(expected, page[4032:4096]):
        raise BridgeError("微信数据库页完整性校验失败，未返回不可靠数据")
    return module._decrypt_page(key, page, number)


def decrypt_snapshot(module, source, destination, key):
    with source.open("rb") as encrypted:
        salt = encrypted.read(16)
        encrypted.seek(0)
        with destination.open("wb") as output:
            number = 0
            while page := encrypted.read(4096):
                number += 1
                output.write(authenticated_page(module, key, salt, page, number))
    wal = Path(str(source) + "-wal")
    if wal.exists() and wal.stat().st_size >= 32:
        with wal.open("rb") as stream:
            header = stream.read(32)
            if struct.unpack(">I", header[:4])[0] not in (0x377F0682, 0x377F0683):
                raise BridgeError("微信 WAL 格式不支持")
            frames, committed, db_pages = [], 0, 0
            while frame := stream.read(4120):
                if len(frame) < 4120:
                    break
                head, page = frame[:24], frame[24:]
                if head[8:16] != header[16:24]:
                    break
                number, commit_pages = struct.unpack(">II", head[:8])
                if number <= 0:
                    break
                plain = authenticated_page(module, key, salt, page, number)
                frames.append((number, plain))
                if commit_pages:
                    committed, db_pages = len(frames), commit_pages
        if committed:
            with destination.open("r+b") as output:
                for number, plain in frames[:committed]:
                    output.seek((number - 1) * 4096)
                    output.write(plain)
                output.truncate(db_pages * 4096)


def create_reader(request, module, identity, scratch):
    account = Path(identity["account_dir"])
    storage = account / "db_storage"
    paths = sorted((storage / "contact").glob("contact.db"))
    if request["operation"] != "resolve_group":
        paths += sorted((storage / "message").glob("message_[0-9]*.db"))
    resource = storage / "message/message_resource.db"
    if request["operation"] == "fetch" and resource.is_file():
        paths.append(resource)

    class ScopedReader(module.WeChatDB):
        def _find_weixin_pids(self):
            return [identity["pid"]]

        def _save_keys(self):
            pass

        def _refresh_db_files(self):
            pass

        def _shard_rows(self, tables, sql_ext, params=(), order_ext="", per_shard_limit=None):
            # An unsupported shard/schema is an error, never a silent omission.
            limit = " LIMIT " + str(max(0, int(per_shard_limit))) if per_shard_limit is not None else ""
            rows = []
            for conn, table in tables:
                if not re.fullmatch(r"Msg_[0-9a-fA-F]{32}", table):
                    raise BridgeError("不支持的微信会话表标识")
                query = "SELECT local_id,local_type,real_sender_id,create_time,message_content,source,packed_info_data,compress_content,server_id,sort_seq,? AS shard FROM " + table + " " + sql_ext + " " + order_ext + limit
                rows.extend(conn.execute(query, (self._shard_label(conn),) + tuple(params)).fetchall())
            return rows

        def _open(self, rel):
            if rel not in self._keys:
                raise BridgeError("目标数据库缺少经校验的内存密钥")
            path = Path(self._db_path(rel))
            destination = scratch / "plain" / (rel.replace("\\", "__").replace("/", "__"))
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                decrypt_snapshot(module, path, destination, self._keys[rel])
            conn = sqlite3.connect(destination.as_uri() + "?mode=ro&immutable=1", uri=True)
            conn.row_factory = sqlite3.Row
            conn.text_factory = module._sqlite_text_factory
            conn.execute("PRAGMA query_only=ON")
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                conn.close()
                raise BridgeError("微信快照结构校验失败")
            return conn

    db = ScopedReader.__new__(ScopedReader)
    db.account, db.account_dir, db.db_dir = account.name, str(account), str(account.parent)
    db.workdir = str(scratch / "unused-key-cache")
    db.cfg_dword, db.master_key = None, None
    db._db_files = [(str(p.relative_to(storage)), str(p), p.stat().st_size) for p in paths]
    db._keys = db.extract_keys()
    if len(db._keys) != len(paths):
        raise BridgeError("本次需要的数据库未全部通过密钥校验")
    captured = []
    for rel, source, size in db._db_files:
        target = scratch / "encrypted" / rel
        stable_encrypted_copy(Path(source), target)
        captured.append((rel, str(target), size))
    db._db_files = captured
    return db


def resolve_chat(db, chat):
    rels = [rel for rel, p, _ in db._db_files if Path(p).name == "contact.db"]
    if len(rels) != 1:
        raise BridgeError("微信联系人数据库未唯一确定")
    with contextlib.closing(db._open(rels[0])) as conn:
        rows = conn.execute("SELECT username,nick_name,remark FROM contact WHERE nick_name=? OR remark=? OR username=? LIMIT 3",
                            (chat["id"], chat["id"], chat["id"])).fetchall()
    exact = [r for r in rows if (str(r["username"]).endswith("@chatroom")) == (chat["kind"] == "group")]
    if len(exact) != 1:
        raise BridgeError("指定微信会话没有唯一精确匹配，未查询其他群")
    return exact[0]["username"]


def scoped_history(db, user, request):
    start = datetime.combine(date.fromisoformat(request["start_date"]), datetime.min.time(), TZ).timestamp()
    end = datetime.combine(date.fromisoformat(request["end_date"]) + timedelta(days=1), datetime.min.time(), TZ).timestamp()
    limit = request["scan_limit"]
    got = db._run_msg_query(user, lambda tables: (
        db._shard_rows(tables, "WHERE create_time>=? AND create_time<?", (int(start), int(end)),
                       order_ext=db._MSG_ORDER_DESC, per_shard_limit=limit), db._shard_maps(tables)))
    rows, maps = got if got else ([], {})
    rows.sort(key=lambda r: r["sort_seq"], reverse=True)
    result = []
    for raw in rows[:limit]:
        row = db._msg_row_to_dict(raw, maps)
        local_type = int(raw["local_type"]) & 0xFFFFFFFF
        kind = {3: "image", 34: "record", 43: "video", 49: "file"}.get(local_type)
        text = public_content(local_type, str(row["content"]))
        record = wechat_record(str(row["content"])) if local_type == 49 else None
        if local_type == 49:
            element = card_xml(text)
            if element is not None:
                title = element.findtext(".//appmsg/title") or ""
                app_type = element.findtext(".//appmsg/type")
                text = ("[文件] " if app_type == "6" else "[卡片] ") + title
                if app_type != "6":
                    kind = None
            else:
                kind = None
                text = "[卡片正文无法解析]"
        if record is not None:
            text = render(record)
        result.append({"id": row["shard"] + ":" + str(row["local_id"]), "time": row["create_time"],
                       "text": text, "sender": row["sender_username"] or "unknown", "kind": row["type"],
                       "attachments": [{"kind": kind}] if kind else [],
                       "_db_user": user, "_db_shard": row["shard"], "_db_local_id": row["local_id"],
                       "_db_type": local_type, "_db_raw_type": int(raw["local_type"]), "_db_sort_seq": row["sort_seq"],
                       "_db_content_sha256": record_digest(raw["message_content"], raw["compress_content"])})
        if record is not None:
            result[-1].update(kind="forward", merged_record={"available": True, "state": "inline", **record})
    return {"rows": result, "coverage": {"source": "wechat_db_readonly", "date_filter": "selected_chat_sql",
            "upstream_exhausted": len(rows) < limit, "process_write": False, "key_persistence": False,
            "snapshot_lifetime": "request_only", "source_shards": len(db._message_dbs())}}


def record_digest(content, compressed):
    digest = hashlib.sha256()
    for value in (content, compressed):
        body = value if isinstance(value, bytes) else str(value).encode()
        digest.update(len(body).to_bytes(8, "big") + body)
    return digest.hexdigest()


def read_record(db, user, request):
    expected = request["row"]
    if expected.get("_db_user") != user:
        raise BridgeError("微信目标会话已变化，请重新查询")
    raw = db.get_message_row(user, int(expected["_db_local_id"]), local_type=expected["_db_raw_type"], shard=expected["_db_shard"])
    if not raw or str(raw["sort_seq"]) != str(expected["_db_sort_seq"]):
        raise BridgeError("原始微信消息未通过分片与序列校验")
    if record_digest(raw["content"], raw.get("compress_content")) != expected.get("_db_content_sha256"):
        raise BridgeError("微信原消息内容已变化，请重新查询")
    mtype = db._msg_type_name(raw["local_type"])
    text = db._friendly_content(raw["content"], mtype) if isinstance(raw["content"], bytes) else str(raw["content"] or "")
    if not text.strip() or text == "[" + str(mtype) + "]":
        compressed = raw.get("compress_content")
        if isinstance(compressed, bytes) and compressed:
            text = db._friendly_content(compressed, mtype)
    result = wechat_record(text)
    if result is None:
        raise BridgeError("指定微信消息不是合并聊天记录")
    result["source"] = "wechat_inline_record"
    return result


def fetch_attachment(db, media, user, request):
    if request.get("record_parent"):
        return fetch_record_attachment(db, user, request)
    expected = request["row"]
    if expected.get("_db_user") != user:
        raise BridgeError("微信目标会话已变化，请重新查询")
    raw = db.get_message_row(user, int(expected["_db_local_id"]), local_type=expected.get("_db_raw_type", expected["_db_type"]), shard=expected["_db_shard"])
    if not raw or str(raw["sort_seq"]) != str(expected["_db_sort_seq"]):
        raise BridgeError("原始微信消息未通过分片与序列校验")
    target = Path(request["target"]).resolve()
    maximum = int(request.get("maximum_bytes", 100 * 1024 * 1024))
    kind = expected["_db_type"]
    if kind == 49:
        # Never search the global file cache by a possibly duplicated filename.
        text = db._friendly_content(raw["content"], 49) if isinstance(raw["content"], bytes) else str(raw["content"])
        element = card_xml(text)
        if element is None:
            raise BridgeError("文件消息缺少可校验的附件 XML")
        title = element.findtext(".//appmsg/title")
        app_type = element.findtext(".//appmsg/type")
        if app_type != "6" or not title or Path(title).name != title or any(c in title for c in "\\/:\x00"):
            raise BridgeError("这条微信卡片不是可定位的文件附件")
        month = datetime.fromtimestamp(raw["create_time"], TZ).strftime("%Y-%m")
        source = Path(db.account_dir) / "msg/file" / month / title
        if not source.is_file():
            return fetch_cdn(db, raw, request, element, "file", title)
        if source.stat().st_size > maximum:
            raise BridgeError("附件超过大小上限")
        expected_md5 = element.findtext(".//appattach/md5") or element.findtext(".//md5")
        declared_size = element.findtext(".//appattach/totallen")
        if declared_size and declared_size.isdigit() and source.stat().st_size != int(declared_size):
            raise BridgeError("本地文件大小与消息声明不符")
        if not expected_md5 or not re.fullmatch(r"[0-9a-fA-F]{32}", expected_md5):
            raise BridgeError("文件缺少来源 MD5，首版不按同名文件猜测归属")
        digest = hashlib.md5(source.read_bytes()).hexdigest()
        if digest.lower() != expected_md5.lower():
            raise BridgeError("本地文件 MD5 与来源消息不符")
        out = target / title
        shutil.copyfile(source, out)
        return {"files": [str(out)], "media_tier": "file", "source_digest_verified": True}
    if kind != 3:
        raise BridgeError("此只读适配首版支持图片与带来源校验的文件")

    class ScopedMedia(media.MediaDownloader):
        def _persist_key(self, key):
            pass

        def _load_persisted_key(self):
            return None

        def _collect_templates(self, *args, **kwargs):
            return [p for p, _ in files.values()]

        def _probe_ct(self, dat_path=None):
            return super()._probe_ct(dat_path or selected_path)

        def _resolve_aes_key(self):
            derived = self._derive_cfg_key()
            return derived[0] if derived else self._scan_aes_key(monitor=False)

    md = ScopedMedia(db, save_dir=str(target))
    message_md5 = md._img_md5(raw)
    if not message_md5:
        raise BridgeError("图片消息缺少本地资源标识")
    files = md._image_files(user, message_md5)
    # No implicit downgrade to a thumbnail.
    requested_tier = request.get("image_tier", "received")
    original_ready = "original" in files and md.original_ready(files["original"][1], (files.get("mid") or (0, 0))[1])
    tier = None
    if requested_tier in {"original", "received", "best_available"} and original_ready:
        tier = "original"
    elif requested_tier in {"received", "best_available"} and "mid" in files:
        tier = "mid"
    elif requested_tier in {"thumbnail", "best_available"} and "thumb" in files:
        tier = "thumb"
    if not tier:
        text = db._friendly_content(raw["content"], 3) if isinstance(raw["content"], bytes) else str(raw["content"])
        return fetch_cdn(db, raw, request, card_xml(text), "image")
    selected_path, size = files[tier]
    if size > maximum:
        raise BridgeError("图片超过大小上限")
    cfg = db.extract_master_key()
    if cfg:
        db.cfg_dword = cfg[1]
    out = md.download_image(user, expected["_db_local_id"], save_dir=str(target), tier=tier, shard=expected["_db_shard"])
    if not out:
        raise BridgeError("微信图片本地保存失败")
    try:
        verify_image(out)
    except Exception:
        raise BridgeError("图片解密结果未通过格式验证") from None
    return {"files": [out], "media_tier": tier, "source_digest_verified": False}


def fetch_record_attachment(db, user, request):
    parent = request["record_parent"]
    record = read_record(db, user, {**request, "row": parent})
    expected = request["row"]
    index = int(expected["_record_entry"])
    selected = record["messages"][index]["attachments"][int(request["attachment_index"])]
    original = expected["attachments"][int(request["attachment_index"])]
    descriptor = selected["_record_descriptor"]
    if descriptor_digest(descriptor) != original.get("_descriptor_sha256"):
        raise BridgeError("微信合并附件来源描述已变化，请重新查询展开")
    kind = selected["kind"]
    name = selected["name"]
    # Only an exact message-derived filename, under a known cache, then MD5/size.
    if name:
        from record_media import safe_name, save_bytes, source_limits
        name = safe_name(name)
        digest, size = source_limits(descriptor, request)
        root = (Path(db.account_dir) / "msg/file").resolve()
        candidates = [month / name for month in root.iterdir() if month.is_dir()] if root.is_dir() else []
        for source in candidates[:120]:
            source = source.resolve()
            if not source.is_relative_to(root) or not source.is_file() or source.stat().st_size != size:
                continue
            body = source.read_bytes()
            if hashlib.md5(body).hexdigest() == digest:
                result = save_bytes(body, {**descriptor, "filename": name}, request, kind, "wechat_record_verified_cache")
                result["transport"] = "local_cache"
                return result
    if not request.get("fetch_if_missing", True) or not request["settings"].get("active_download", False):
        raise BridgeError("微信合并附件未缓存；主动下载未启用或本次为cache_only")
    if kind == "image" and request.get("image_tier") == "thumbnail":
        raise BridgeError("合并记录只提供完整图片下载描述；未冒充缩略图")
    return download_descriptor(db, request, descriptor.copy(), kind, name, "source_verified")


def fetch_cdn(db, raw, request, element, kind, filename=None):
    """Only a fresh, exact message row may supply the network descriptor."""
    if not request.get("fetch_if_missing", True) or not request["settings"].get("active_download", False):
        raise BridgeError("指定版本未在本地缓存中找到；主动下载未启用或本次为 cache_only")
    if element is None:
        raise BridgeError("原始消息没有可验证的 CDN 附件描述")
    from wechat_cdn import account_route, download
    maximum = int(request.get("maximum_bytes", 100 * 1024 * 1024))
    tier = request.get("image_tier", "received")
    if kind == "file":
        if element.findtext(".//appmsg/type") != "6":
            raise BridgeError("指定消息不是文件附件")
        descriptor = {"filetype": 5, "size": int(element.findtext(".//appattach/totallen") or 0),
                      "md5": element.findtext(".//appattach/md5") or element.findtext(".//md5") or "",
                      "fileid": element.findtext(".//appattach/cdnattachurl") or "",
                      "key": element.findtext(".//appattach/aeskey") or ""}
        result_tier = "file"
    else:
        if tier == "thumbnail":
            raise BridgeError("缩略图未缓存；当前主动下载只取完整图片")
        image = element.find(".//img")
        if image is None:
            raise BridgeError("图片消息缺少 CDN 描述")
        attrs = image.attrib
        original = bool(attrs.get("cdnbigimgurl")) and 0 < int(attrs.get("hdlength") or 0) <= maximum
        if tier == "original" and not original:
            raise BridgeError("该消息没有大小上限内的原图下载描述")
        descriptor = {"filetype": 1 if original else 2,
                      "size": int(attrs.get("hdlength" if original else "length") or 0),
                      "md5": attrs.get("md5", ""),
                      "fileid": attrs.get("cdnbigimgurl" if original else "cdnmidimgurl", ""),
                      "key": attrs.get("aeskey", "")}
        result_tier = "original" if original else "mid"
    return download_descriptor(db, request, descriptor, kind, filename, result_tier)


def download_descriptor(db, request, descriptor, kind, filename, result_tier):
    from wechat_cdn import account_route, download
    maximum = int(request.get("maximum_bytes", 100 * 1024 * 1024))
    if (not re.fullmatch(r"[a-fA-F0-9]{32}", descriptor["md5"])
            or not re.fullmatch(r"[a-fA-F0-9]{32}", descriptor["key"])
            or not 0 < descriptor["size"] <= maximum or not 0 < len(descriptor["fileid"]) <= 8192):
        raise BridgeError("消息中的 CDN 长度、校验值或凭据不完整")
    descriptor["md5"] = descriptor["md5"].lower()
    descriptor["key"] = bytes.fromhex(descriptor["key"])
    live = db.extract_master_key()
    if not live or db.account != live[2] and not db.account.startswith(live[2] + "_"):
        raise BridgeError("CDN 凭据与已绑定的当前微信账号不符")
    route = account_route(live[1], descriptor["filetype"])
    # Pinned observed client tokens, not a guessed conversion from version text.
    # 4.2.0.9 reports 4065599497 via its own WeChatAppEx child command line.
    versions = {"4.1.15.56": 0xf2540f38, "4.2.0.9": 0xf2544009}
    version = versions.get(request["settings"].get("client_version"))
    if version is None:
        raise BridgeError("此微信版本的主动下载协议尚未实机验证")
    plain, transfer = download(route, descriptor, time.monotonic() + 75, maximum,
                               version, b"UnifiedPCWindows")
    if kind == "image":
        try:
            fmt, dimensions = verify_image(io.BytesIO(plain))
        except Exception:
            raise BridgeError("CDN 图片未通过格式校验，未保存为可用附件") from None
        extensions = {"JPEG": ".jpg", "MPO": ".jpg", "PNG": ".png", "GIF": ".gif",
                      "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tif"}
        if fmt not in extensions:
            raise BridgeError("CDN 图片格式尚未支持")
        filename = descriptor["md5"] + extensions[fmt]
        transfer["dimensions"] = list(dimensions)
    from record_media import safe_name
    filename = safe_name(filename)
    out = Path(request["target"]) / filename
    with out.open("xb") as stream:
        stream.write(plain)
    return {"files": [str(out)], "media_tier": result_tier, "save_method": "wechat_cdn_download", **transfer}


def main():
    request = json.load(sys.stdin)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            info = inspect_identity(request["settings"])
            module, media = load_read_modules()
            scratch = Path(request["scratch"]).resolve()
            if not scratch.is_dir():
                raise BridgeError("缺少由调用端创建的临时工作目录")
            db = create_reader(request, module, info, scratch)
            user = resolve_chat(db, request["chat"])
            if request["operation"] == "search":
                result = scoped_history(db, user, request)
            elif request["operation"] == "fetch":
                result = fetch_attachment(db, media, user, request)
            elif request["operation"] == "read_record":
                result = read_record(db, user, request)
            else:
                raise BridgeError("只读数据库适配不支持此操作")
            db._keys.clear()
            if inspect_identity(request["settings"]) != info:
                raise BridgeError("微信读取期间账号变化，拒绝返回")
        payload = {"ok": True, "result": result}
    except BridgeError as exc:
        payload = {"ok": False, "error": str(exc)}
    except Exception as exc:
        payload = {"ok": False, "error": "微信只读数据库适配失败：" + type(exc).__name__}
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
