"""Retrieve one source-bound QQ merged record. No login or generic packet API."""
import secrets
import base64
import json
import socket
import zlib

from bridge import BridgeError
from merged_records import append, attach, limit, view
from qq_group_file import (build_sso_request, crypto, decode_sso_reply, encode,
                           public_addresses, receive)
from qq_session import check_kernel, device_and_app, read_material
from wechat_cdn import protobuf, one

COMMAND = b"trpc.group.long_msg_interface.MsgService.SsoRecvLongMsg"
MAX_BODY = 512 * 1024


def text(fields, field, default=""):
    return one(fields, field, 2, default.encode()).decode("utf-8", errors="replace")


def image_descriptors(elem):
    for field in (4, 8):
        for n, w, value in elem:
            if n != field or w != 2:
                continue
            image = protobuf(value)
            yield {"transport": "qq_record_image", "filename": text(image, 1 if field == 4 else 2),
                   "filesize": one(image, 2 if field == 4 else 25, 0, 0),
                   "md5_hex": one(image, 7 if field == 4 else 13, 2, b"").hex()}
    for n, w, value in elem:
        if n != 53 or w != 2:
            continue
        common = protobuf(value)
        if one(common, 1, 0, 0) != 48 or one(common, 3, 0, 0) not in {10, 20}:
            continue
        # MsgInfo / MsgInfoBody / IndexNode / FileInfo. No URLs are followed here.
        info = protobuf(one(common, 2, 2, b""))
        for n, w, value in info:
            if n != 1 or w != 2:
                continue
            body = protobuf(value)
            index = protobuf(one(body, 1, 2))
            file = protobuf(one(index, 1, 2))
            descriptor = {"transport": "qq_record_image", "filename": text(file, 4),
                          "filesize": one(file, 1, 0, 0), "md5_hex": text(file, 2)}
            picture = protobuf(one(body, 2, 2, b""))
            extension = protobuf(one(picture, 2, 2, b""))
            if text(picture, 3) == "multimedia.nt.qq.com.cn":
                path, params = text(picture, 1), text(extension, 1).lstrip("?&")
                descriptor["cdn_url"] = path + (("&" if "?" in path else "?") + params if params else "")
            yield descriptor


def private_file(value):
    file = protobuf(value)
    return {"transport": "qq_record_private_file", "filename": text(file, 5),
            "filesize": one(file, 6, 0, 0), "md5_hex": one(file, 4, 2, b"").hex(),
            "file_uuid": text(file, 3), "file_hash": text(file, 57)}


def group_file(elem, group):
    for n, w, value in elem:
        if n != 5 or w != 2:
            continue
        trans = protobuf(value)
        if one(trans, 1, 0, 0) != 24:
            continue
        raw = one(trans, 2, 2)
        if len(raw) < 3 or int.from_bytes(raw[1:3], "big") != len(raw) - 3:
            raise BridgeError("合并记录群文件描述长度无效")
        outer = protobuf(raw[3:])
        file = protobuf(one(protobuf(one(outer, 7, 2)), 2, 2))
        descriptor = {"transport": "qq_record_group_file", "filename": text(file, 4),
                      "filesize": one(file, 3, 0, 0), "md5_hex": one(file, 8, 2, b"").hex(),
                      "file_uuid": text(file, 2), "bus_id": one(file, 1, 0, 0), "group_id": one(group, 1, 0, 0)}
        # Forwarding may copy a group file and retain its OLD outer UUID/group.
        # ExtInfo identifies the resulting copy. It must match the visible name
        # and size; neither the original source group nor arbitrary links are read.
        extra = text(file, 7)
        if extra and len(extra) <= 16384:
            try:
                encoded = json.loads(extra).get("ExtInfo")
                inner = protobuf(one(protobuf(base64.b64decode(encoded, validate=True)), 2, 2))
                if (one(inner, 1, 0, 0) == 3 and one(inner, 3, 0, 0) > 0
                        and text(inner, 5) == descriptor["filename"] and one(inner, 6, 0, 0) == descriptor["filesize"]
                        and one(inner, 13, 0, 0) == descriptor["bus_id"]):
                    descriptor.update(group_id=one(inner, 3, 0), file_uuid=text(inner, 4))
            except (ValueError, TypeError, AttributeError, BridgeError):
                pass
        yield descriptor


def parse_payload(data, title):
    result = view(title)
    buffers = []
    for n, w, value in protobuf(data):
        if n == 2 and w == 2:
            item = protobuf(value)
            if text(item, 1) == "MultiMsg":
                buffers.extend(v for n, w, v in protobuf(one(item, 2, 2)) if n == 1 and w == 2)
    if not buffers:
        raise BridgeError("QQ 合并记录没有可解析的消息正文")
    for raw in buffers:
        msg = protobuf(raw)
        head = protobuf(one(msg, 1, 2))
        content_head = protobuf(one(msg, 2, 2))
        group = protobuf(one(head, 8, 2, b""))
        sender = text(group, 4) or str(one(head, 1, 0, 0))
        stamp = one(content_head, 6, 0, 0)
        message = protobuf(one(msg, 3, 2, b""))
        rich = protobuf(one(message, 1, 2, b""))
        parts = []
        attachments = []
        for n, w, value in rich:
            if n != 2 or w != 2:
                continue
            elem = protobuf(value)
            try:
                attachments.extend(("image", descriptor) for descriptor in image_descriptors(elem))
                files = list(group_file(elem, group))
            except BridgeError:
                files = []
                limit(result, "attachment_descriptor_unsupported")
            attachments.extend(("file", descriptor) for descriptor in files)
            if any(n == 1 and w == 2 for n, w, _ in elem):
                parts.append(text(protobuf(one(elem, 1, 2)), 1))
            elif any(n in {3, 4, 8} for n, _, _ in elem):
                parts.append("[图片]")
            elif files:
                parts.extend("[文件] " + descriptor["filename"] for descriptor in files)
            elif any(n == 2 for n, _, _ in elem):
                parts.append("[表情]")
            elif any(n == 19 for n, _, _ in elem):
                parts.append("[视频]")
            elif any(n == 45 for n, _, _ in elem):
                quoted = []
                for n, w, value in protobuf(one(elem, 45, 2)):
                    if n == 5 and w == 2:
                        ref = protobuf(value)
                        if any(n == 1 and w == 2 for n, w, _ in ref):
                            quoted.append(text(protobuf(one(ref, 1, 2)), 1))
                        else:
                            quoted.append("[引用的媒体或卡片]")
                parts.append("[引用] " + "".join(quoted) + "\n")
            elif any(n == 53 for n, _, _ in elem):
                common = protobuf(one(elem, 53, 2))
                service = one(common, 1, 0, 0)
                business = one(common, 3, 0, 0)
                if service == 48 and business in {10, 20}:
                    parts.append("[图片]")
                elif service == 48 and business in {11, 21}:
                    parts.append("[视频]")
                elif service == 45:
                    parts.append(text(protobuf(one(common, 2, 2)), 1))
                else:
                    parts.append("[未展开的消息]")
                    limit(result, "unsupported_or_nested_message")
            elif any(n == 16 for n, _, _ in elem):
                extra = protobuf(one(elem, 16, 2))
                sender = text(extra, 2) or text(extra, 1) or sender
            elif all(n in {9, 37} for n, _, _ in elem):
                pass  # Transport flags, not message text or credentials to expose.
            else:
                parts.append("[未展开的消息]")
                limit(result, "unsupported_or_nested_message")
        if any(n == 2 for n, _, _ in message):
            descriptor = private_file(one(protobuf(one(message, 2, 2)), 1, 2))
            attachments.append(("file", descriptor))
            parts.append("[文件] " + descriptor["filename"])
        for n, w, value in rich:
            if n == 3 and w == 2:
                descriptor = private_file(value)
                attachments.append(("file", descriptor))
                parts.append("[文件] " + descriptor["filename"])
            elif n == 4:
                parts.append("[语音]")
        if not parts:
            parts.append("[未支持的消息]")
            limit(result, "unsupported_message_type")
        if not append(result, sender, stamp, "message", "".join(parts)):
            break
        for kind, descriptor in attachments:
            attach(result, result["messages"][-1], kind, descriptor["filename"], descriptor["filesize"], descriptor)
    return result


def fetch_record(card, request, info, scan):
    settings = request["settings"]
    if not request.get("fetch_if_missing", True) or not settings.get("active_download", False):
        raise BridgeError("QQ 本地只有合并记录预览；主动取回未启用或本次为 cache_only")
    resid = card.get("_resid")
    if not isinstance(resid, str) or not 1 <= len(resid) <= 512 or any(ord(c) < 33 for c in resid):
        raise BridgeError("QQ 合并记录缺少可校验的来源标识")
    binding = check_kernel(settings, info)
    material = read_material(settings, info, scan)
    guid, appid = device_and_app(settings, material)
    body = encode([(1, encode([(1, encode([(2, material["uid"].encode())])), (2, resid.encode()), (3, 1)])),
                   (15, encode([(1, 2), (2, 0), (3, 0), (4, 0)]))])
    tea = crypto()
    sequence = secrets.randbelow(0x7fffff) + 0x10000
    packet = build_sso_request(settings["account"], body, COMMAND, material, guid, appid, binding["version"], sequence, tea)
    addresses = public_addresses("msfwifi.3g.qq.com", 8080)
    try:
        with socket.create_connection((addresses[0][4][0], 8080), timeout=15) as sock:
            sock.sendall(packet)
            length = int.from_bytes(receive(sock, 4), "big")
            reply = decode_sso_reply(receive(sock, length - 4), settings["account"], sequence, material["key"], tea, COMMAND)
    except OSError:
        raise BridgeError("QQ 合并记录取回未完成；可能已过期或暂不可用") from None
    response = protobuf(one(protobuf(reply), 1, 2))
    result = parse_response(response, resid, card["title"])
    check_kernel(settings, info)
    result["source"] = "qq_source_bound_sso"
    return result


def parse_response(response, resid, title):
    if text(response, 3) != resid:
        raise BridgeError("QQ 合并记录响应与来源消息不符")
    try:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = decoder.decompress(one(response, 4, 2), MAX_BODY + 1)
        if len(data) > MAX_BODY or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError()
    except (ValueError, zlib.error):
        raise BridgeError("QQ 合并记录正文超过上限或压缩内容无效") from None
    return parse_payload(data, title)
