"""Inventory / portable reports from a scoped receipt and existing downloads only."""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from bridge import BridgeError, attachment_key, load_json, write_json

MAX_FILES = 200

def safe_name(value):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(value)).strip(" .")[:120] or "attachment"
    if name.split(".")[0].upper() in {"CON", "NUL", "AUX", "PRN", *("COM" + str(i) for i in range(1, 10)), *("LPT" + str(i) for i in range(1, 10))}:
        name = "_" + name
    return name


def literal(value):
    text = str(value)
    fence = "`" * max(3, 1 + max((len(m.group()) for m in re.finditer(r"`+", text)), default=0))
    return fence + "text\n" + text + "\n" + fence


def source_files(directory, manifest, maximum):
    root = (directory / "files").resolve()
    if not root.is_relative_to(directory.resolve()) or not isinstance(manifest.get("files"), list) or not 0 < len(manifest["files"]) <= MAX_FILES:
        raise ValueError("path")
    checked = []
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise ValueError("file")
        path = Path(item["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("path")
        if not isinstance(item["bytes"], int) or not 0 <= item["bytes"] <= maximum or path.stat().st_size != item["bytes"]:
            raise ValueError("size")
        if not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]):
            raise ValueError("digest")
        checked.append((path, item))
    return checked


def matches_saved_file(path, item):
    digest, total = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while block := stream.read(min(1024 * 1024, item["bytes"] - total + 1)):
            total += len(block)
            if total > item["bytes"]:
                return False
            digest.update(block)
    return total == item["bytes"] and digest.hexdigest() == item["sha256"]


def copy_verified(source, target, item):
    digest, total = hashlib.sha256(), 0
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        while block := incoming.read(min(1024 * 1024, item["bytes"] - total + 1)):
            total += len(block)
            if total > item["bytes"]:
                raise BridgeError("材料在整理期间变化，未生成可交付文件夹")
            digest.update(block)
            outgoing.write(block)
    if total != item["bytes"] or digest.hexdigest() != item["sha256"]:
        raise BridgeError("材料在整理期间变化，未生成可交付文件夹")


def prepare(bridge, receipt_id, message_ids=None, write_bundle=False):
    if not isinstance(write_bundle, bool):
        raise BridgeError("write_bundle 必须是布尔值")
    receipt, chat = bridge.receipt(receipt_id)
    rows = receipt["rows"]
    if message_ids is not None:
        if not isinstance(message_ids, list) or not message_ids or not all(isinstance(m, str) for m in message_ids) or len(set(message_ids)) != len(message_ids):
            raise BridgeError("必须提供非空、无重复的本次命中消息 ID 列表")
        if not set(message_ids).issubset({r["id"] for r in rows}):
            raise BridgeError("材料消息不在本次查询结果中")
        rows = [r for r in rows if r["id"] in message_ids]
    if len({r["id"] for r in rows}) != len(rows):
        raise BridgeError("本次消息 ID 不唯一，拒绝整理")
    output = bridge.output.resolve()
    root = (output / receipt_id).resolve()
    if not root.is_relative_to(output):
        raise BridgeError("材料目录超出本程序输出范围")
    wanted = {}
    for row in rows:
        for index, attachment in enumerate(row.get("attachments", [])):
            if index in row.get("matched_attachment_indices", list(range(len(row.get("attachments", []))))):
                key = attachment_key(row["id"], index)
                if key in wanted:
                    raise BridgeError("附件标识冲突，未省略或覆盖材料")
                wanted[key] = (row, index, attachment)
    if len(wanted) > 500:
        raise BridgeError("材料超过本次500项上限，请限定消息后再整理")
    candidates, invalid = defaultdict(list), defaultdict(bool)
    if root.is_dir():
        for count, directory in enumerate(root.iterdir()):
            if count >= 2000:
                raise BridgeError("本次下载目录过多，请限定消息并整理本程序旧输出")
            if not re.fullmatch(r"[a-f0-9]{16}-[a-f0-9]{8}", directory.name) or directory.name[:16] not in wanted:
                continue
            key = directory.name[:16]
            row, index, attachment = wanted[key]
            try:
                if not directory.resolve().is_relative_to(root) or (directory / "FAILED.json").exists():
                    raise ValueError("incomplete")
                path = directory / "source.json"
                if path.stat().st_size > 256 * 1024:
                    raise ValueError("manifest")
                manifest = load_json(path)
                if not isinstance(manifest, dict) or not isinstance(manifest.get("media_tier", ""), (str, type(None))):
                    raise ValueError("manifest")
                expected = {"receipt_id": receipt_id, "chat_alias": receipt["chat_alias"], "platform": chat["platform"],
                            "message_id": row["id"], "attachment_index": index}
                if any(manifest.get(k) != v for k, v in expected.items()):
                    raise ValueError("scope")
                candidates[key].append((directory, manifest))
            except (OSError, ValueError, KeyError, TypeError):
                invalid[key] = True
    maximum = min(int(bridge.config.get("max_attachment_mb", 100)), 100) * 1024 * 1024
    remaining = maximum
    materials, copies = [], []
    for key, (row, index, attachment) in wanted.items():
        item = {"message_id": row["id"], "attachment_index": index, "kind": attachment.get("kind", "unknown"),
                "name": attachment.get("name", ""), "status": "no_verified_local_copy", "files": []}
        if invalid[key]:
            item["reason"] = "invalid_or_incomplete_local_copy"
        rank = {"original": 0, "source_verified": 0, "file": 0, "received": 1, "compressed": 2, "thumbnail": 9}
        for directory, manifest in sorted(candidates[key], key=lambda v: (rank.get(v[1].get("media_tier"), 5), v[0].name)):
            try:
                files = source_files(directory, manifest, maximum)
                if len(copies) + len(files) > MAX_FILES:
                    item["reason"] = "per_call_file_budget_exceeded"
                    continue
                size = sum(f[1]["bytes"] for f in files)
                if size > remaining:
                    item["reason"] = "per_call_byte_budget_exceeded"
                    continue
                # Charge even failed candidates to bound disk reads on corruption.
                remaining -= size
                if any(not matches_saved_file(path, info) for path, info in files):
                    item["reason"] = "saved_file_hash_mismatch"
                    continue
                item.update(status="ready", media_tier=manifest.get("media_tier"), save_method=manifest.get("save_method"),
                            source_digest_verified=bool(manifest.get("original_bytes_independently_verified")))
                item.pop("reason", None)
                for position, (path, info) in enumerate(files):
                    relative = "assets/" + key + "-" + str(position) + "-" + safe_name(path.name)
                    item["files"].append({"path": relative, "bytes": info["bytes"], "sha256": info["sha256"]})
                    copies.append((path, relative, info))
                break
            except (OSError, ValueError, KeyError, TypeError):
                item["reason"] = "invalid_local_copy"
        materials.append(item)
    report = {"schema": "chat-task-materials/v1", "receipt_id": receipt_id, "scope": receipt.get("scope", {}),
              "purpose": receipt["purpose"], "client_access": False, "network_access": False,
              "query_coverage": receipt.get("coverage", {"history_complete": False}),
              "messages": [{k: r.get(k, "") for k in ("id", "time", "sender", "text")} for r in rows], "materials": materials,
              "coverage": {"messages": len(rows), "attachments": len(materials),
                           "ready": sum(m["status"] == "ready" for m in materials),
                           "unavailable": sum(m["status"] != "ready" for m in materials),
                           "verified_bytes": sum(f["bytes"] for m in materials for f in m["files"]),
                           "bytes_checked": maximum - remaining, "byte_budget": maximum, "history_complete": False,
                           "note": "只统计本次查询中选定的附件；缺失不触发下载，不代表原消息没有附件。"}}
    bridge.receipt(receipt_id)  # A new block / rebind revokes preview and export, too.
    if write_bundle:
        root.mkdir(parents=True, exist_ok=True)
        final = root / ("bundle-" + secrets.token_hex(8))
        with tempfile.TemporaryDirectory(prefix=".materials-", dir=root) as temporary:
            target = Path(temporary)
            (target / "assets").mkdir()
            for source, relative, info in copies:
                copy_verified(source, target / relative, info)
            write_json(target / "materials.json", report)
            lines = ["# 任务材料", "", literal(receipt["purpose"]), "",
                     "仅包含本次查询选定的消息和已验证本地材料；没有访问客户端或联网。", "",
                     "查询范围与截断信息：", "", literal(json.dumps({"scope": report["scope"], "coverage": report["query_coverage"]}, ensure_ascii=False)), ""]
            for row in report["messages"]:
                lines += ["## 消息", "", literal(row["time"] + " | " + row["sender"] + " | " + row["id"]), "", literal(row["text"]), ""]
                for item in (m for m in materials if m["message_id"] == row["id"]):
                    lines += [literal(str(item["attachment_index"]) + " | " + item["kind"] + " | " + item["status"] + " | " + str(item.get("media_tier", ""))), ""]
                    for file in item["files"]:
                        from urllib.parse import quote
                        lines += ["[保存的附件](" + quote(file["path"], safe="/") + ")", "", "SHA256: " + file["sha256"], ""]
            (target / "materials.md").write_text("\n".join(lines), encoding="utf-8")
            bridge.receipt(receipt_id)
            os.replace(target, final)
        report["bundle"] = {"directory": str(final), "markdown": str(final / "materials.md"), "manifest": str(final / "materials.json")}
    # Relative paths in previews are descriptive until a bundle has been requested.
    report["files_copied"] = len(copies) if write_bundle else 0
    if not write_bundle:
        report["local_file_paths"] = {relative: str(source) for source, relative, info in copies}
    bridge.audit("materials", receipt["chat_alias"], receipt["purpose"], {"ok": True, "write_bundle": bool(write_bundle), "count": len(materials)})
    return report
