"""Bounded inbound CDN transport; credentials and plaintext remain request-local.

Wire-format reference / adapted range checks: rmqg/wechat-digest,
deployment/fetch-originals.py, b2a728bddf3c48dad47f92bb9beeb1fbcc4631fd.
Copyright (c) 2026 rmqg, MIT; see vendor/wechat_digest_LICENSE.
No login, client injection, screen reader, UI, or persistent credential cache.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
from pathlib import Path
import re
import struct
import time
import urllib.error
import urllib.request

from bridge import BridgeError


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise BridgeError("CDN 配置截断")
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            if value >= 1 << 64:
                break
            return value, offset
    raise BridgeError("CDN 配置整数越界")


def protobuf(data):
    if len(data) > 512 * 1024:
        raise BridgeError("CDN 配置超过上限")
    fields, offset = [], 0
    while offset < len(data):
        tag, offset = varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if not 0 < number <= 10000:
            raise BridgeError("CDN 配置字段无效")
        if wire == 0:
            value, offset = varint(data, offset)
        elif wire == 2:
            length, offset = varint(data, offset)
            if length > len(data) - offset:
                raise BridgeError("CDN 配置字段截断")
            value = data[offset:offset + length]
            offset += length
        else:
            raise BridgeError("CDN 配置格式不支持")
        fields.append((number, wire, value))
        if len(fields) > 10000:
            raise BridgeError("CDN 配置字段过多")
    return fields


def one(fields, number, wire, default=None):
    values = [v for n, w, v in fields if n == number and w == wire]
    if not values and default is not None:
        return default
    if len(values) != 1:
        raise BridgeError("CDN 配置字段缺失或不唯一")
    return values[0]


def route_from_table(table, filetype):
    rules = []
    for n, w, raw in table:
        if n != 8 or w != 2:
            continue
        rule = protobuf(raw)
        if any(n not in range(1, 7) or w != 0 for n, w, _ in rule):
            raise BridgeError("CDN 路由条件不支持")
        if all(one(rule, n, 0, 0) in (0, actual) for n, actual in ((2, 1), (3, 1), (4, filetype), (5, 2))):
            rank = one(rule, 1, 0) & 0xffffffff
            if rank & (1 << 31):
                rank -= 1 << 32
            rules.append((rank, one(rule, 6, 0)))
    rules.sort()
    if not rules or sum(rank == rules[0][0] for rank, _ in rules) != 1:
        raise BridgeError("CDN 下载路由缺失或不唯一")
    configs = [protobuf(raw) for n, w, raw in table if n == 7 and w == 2]
    configs = [c for c in configs if one(c, 1, 0) == rules[0][1]]
    if len(configs) != 1:
        raise BridgeError("CDN 路由目标不唯一")
    config = configs[0]
    auth, ips = one(config, 8, 2), []
    for n, w, value in config:
        if n == 3 and w == 0:
            low = value & 0xffffffff
            signed = low if low < (1 << 31) else low + 0xffffffff00000000
            if value not in (low, signed):
                raise BridgeError("CDN 端点整数无效")
            ip = ipaddress.IPv4Address(struct.pack("<I", low))
            if not ip.is_global or ip.is_multicast:
                raise BridgeError("CDN 端点不是公网地址")
            ips.append(str(ip))
    if (not ips or len(ips) > 32 or not 0 < len(auth) <= 65536
            or 443 not in [v for n, w, v in config if n == 7 and w == 0]):
        raise BridgeError("CDN 凭据或端点无效")
    return {"version": one(table, 1, 0), "uin": one(table, 2, 0), "auth": auth, "server_ips": ips}


def account_route(account_uin, filetype):
    """Only the route table matching the live client's account may be used."""
    root = Path(os.environ["APPDATA"]) / "Tencent/xwechat"
    paths = [root / name / "cdncomm/cdninfo_new.cache" for name in ("net", "net_1")]
    found = []
    for path in paths:
        if not path.is_file() or path.stat().st_size > 512 * 1024:
            continue
        for n, w, raw in protobuf(path.read_bytes()):
            if n == 1 and w == 2:
                record = protobuf(raw)
                table = protobuf(one(record, 7, 2))
                if one(table, 2, 0) & 0xffffffff == account_uin:
                    found.append((one(record, 2, 0), table))
    latest = max((stamp for stamp, _ in found), default=0)
    unique = {repr(table): table for stamp, table in found if stamp == latest}
    if len(unique) != 1:
        raise BridgeError("当前账号 CDN 路由未唯一确定，未尝试其他账号")
    return route_from_table(next(iter(unique.values())), filetype)


def pack_fields(fields):
    return b"".join(struct.pack(">I", len(part)) + part
                    for key, value in sorted(fields.items()) for part in (key.encode("ascii"), value))


def unpack_fields(raw):
    if len(raw) > 2 * 1024 * 1024:
        raise BridgeError("CDN 响应超过上限")
    fields, at = {}, 0
    while at < len(raw):
        parts = []
        for _ in range(2):
            if at + 4 > len(raw):
                raise BridgeError("CDN 响应长度截断")
            size = struct.unpack_from(">I", raw, at)[0]
            at += 4
            if size > len(raw) - at:
                raise BridgeError("CDN 响应字段截断")
            parts.append(raw[at:at + size])
            at += size
        key = parts[0]
        if not re.fullmatch(rb"[A-Za-z0-9_-]{1,128}", key) or key.decode() in fields or len(fields) >= 256:
            raise BridgeError("CDN 响应字段重复或无效")
        fields[key.decode()] = parts[1]
    return fields


def number(fields, key):
    value = fields.get(key, b"")
    if not re.fullmatch(rb"-?[0-9]{1,19}", value):
        raise BridgeError("CDN 响应整数缺失或无效")
    return int(value)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def download(route, descriptor, deadline, maximum, client_version, client_os=b"UnifiedPCWin"):
    """Return bytes only after all range, AES-padding, size and digest checks."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    size, kind = descriptor["size"], descriptor["filetype"]
    if not 0 < size <= maximum or len(descriptor["key"]) != 16:
        raise BridgeError("附件长度或解密描述不支持")
    if kind not in (1, 2, 5):
        raise BridgeError("此 CDN 传输尚未支持该附件类型")
    exact = kind != 2
    total = (size // 16 + 1) * 16 if exact else None
    limit = (maximum // 16 + 1) * 16
    fields = {k: str(v).encode() for k, v in {
        "ver": route["version"], "weixinnum": route["uin"], "clientversion": client_version,
        "nettype": 1, "acceptdupack": 1, "safeproto": 1, "filetype": kind,
        "wxchattype": 0, "lastretcode": 0, "ipseq": 0, "largesvideo": 0,
        "sourceflag": 0, "wxautostart": 0, "downpicformat": 4,
    }.items()}
    fields.update(clientostype=client_os, authkey=route["auth"], wxmsgflag=b"", fileid=descriptor["fileid"].encode())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    encrypted, sequence, representation = bytearray(), 0, None
    while total is None or len(encrypted) < total:
        sequence += 1
        if sequence > (limit + 65535) // 65536:
            raise BridgeError("CDN 传输次数超过附件上限")
        start = len(encrypted)
        end = start + 65535 if total is None else min(start + 65535, total - 1)
        fields.update(seq=str(sequence).encode(), rangestart=str(start).encode(), rangeend=str(end).encode())
        body, reply = pack_fields(fields), None
        for endpoint in route["server_ips"]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeError("CDN 下载超时")
            ip = ipaddress.IPv4Address(endpoint)
            if not ip.is_global or ip.is_multicast:
                raise BridgeError("CDN 端点不是公网地址")
            req = urllib.request.Request("http://" + str(ip) + ":443/download", data=body,
                headers={"Content-Type": "application/octet-stream", "User-Agent": "MicroMessenger Client",
                         "Connection": "close", "C-Seq": str(sequence)}, method="POST")
            try:
                with opener.open(req, timeout=min(10, remaining)) as response:
                    if response.status != 200:
                        raise BridgeError("CDN HTTP 状态 " + str(response.status))
                    reply = unpack_fields(response.read(2 * 1024 * 1024 + 1))
                break
            except urllib.error.HTTPError as exc:
                raise BridgeError("CDN HTTP 状态 " + str(exc.code)) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                continue
        if reply is None:
            raise BridgeError("当前账号的 CDN 端点均未能连接")
        code = number(reply, "retcode")
        if code:
            raise BridgeError("CDN 下载返回 " + str(code) + "；附件可能过期或当前路由不可用")
        block = reply.get("filedata", b"")
        returned_total, returned_end = number(reply, "totalsize"), number(reply, "rangeend")
        if (number(reply, "seq") != sequence or number(reply, "rangestart") != start
                or not block or not 0 < returned_total <= limit or returned_total % 16
                or returned_end != start + len(block) - 1 or returned_end > end
                or returned_end >= returned_total or total is not None and total != returned_total):
            raise BridgeError("CDN 分片关联或长度校验失败")
        current = {k: number(reply, k) if k in reply else None for k in ("substituteftype", "rsppicformat")}
        if representation is not None and representation != current:
            raise BridgeError("CDN 传输中图片版本变化")
        representation, total = current, returned_total
        if kind == 2 and current["substituteftype"] not in (2, 12):
            raise BridgeError("CDN 未返回完整接收图")
        encrypted.extend(block)
    cipher = Cipher(algorithms.AES(descriptor["key"]), modes.ECB()).decryptor()
    padded = cipher.update(bytes(encrypted)) + cipher.finalize()
    unpad = padding.PKCS7(128).unpadder()
    try:
        plain = unpad.update(padded) + unpad.finalize()
    except ValueError:
        raise BridgeError("CDN 附件解密校验失败") from None
    matches = len(plain) == size and hashlib.md5(plain).hexdigest() == descriptor["md5"]
    if not 0 < len(plain) <= maximum or exact and not matches:
        raise BridgeError("CDN 附件与原始消息的大小或 MD5 不符")
    return plain, {"transport": "wechat_cdn", "source_digest_verified": matches,
                   "ciphertext_bytes": len(encrypted), **representation}
