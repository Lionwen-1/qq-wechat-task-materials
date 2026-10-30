"""One fixed OIDB 0x6D6_2 request, then bounded HTTPS inbound file retrieval.

No login, heartbeat, generic packet tool, plugin, injection or UI automation.
Wire-format references: LagrangeDev/lagrange-python and NapCatQQ. QQ-TEA is
loaded from the unchanged LGPL-2.1 library in vendor/lagrange_crypto.
"""
from __future__ import annotations
import hashlib
import importlib.util
import io
import ipaddress
from pathlib import Path
import re
import secrets
import socket
import struct
import urllib.error
import urllib.request
import zlib

from bridge import BridgeError, NoRedirect, ROOT
from qq_session import check_kernel, read_material, device_and_app
from wechat_cdn import protobuf, one

COMMAND = b"OidbSvcTrpcTcp.0x6D6_2"
MAX_FRAME = 2 * 1024**2


def varint(value):
    if not isinstance(value, int) or not 0 <= value < 1 << 64:
        raise BridgeError("QQ 协议整数越界")
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result) + bytes([value])


def encode(fields):
    result = b"".join(varint(n * 8 + (2 if isinstance(v, bytes) else 0)) +
                      (varint(len(v)) + v if isinstance(v, bytes) else varint(v)) for n, v in fields)
    if len(result) > MAX_FRAME:
        raise BridgeError("QQ 请求超过大小上限")
    return result


def sized(value, width=4):
    return (len(value) + width).to_bytes(width, "big") + value


def take_sized(stream):
    raw = stream.read(4)
    if len(raw) != 4:
        raise BridgeError("QQ 响应长度截断")
    length = int.from_bytes(raw, "big")
    if not 4 <= length <= MAX_FRAME:
        raise BridgeError("QQ 响应字段长度越界")
    result = stream.read(length - 4)
    if len(result) != length - 4:
        raise BridgeError("QQ 响应字段截断")
    return result


def crypto():
    spec = importlib.util.spec_from_file_location("bridge_qq_tea", ROOT / "vendor/lagrange_crypto/tea.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_request(account, group, file_id, material, guid, appid, version, sequence, tea):
    download = encode([(1, int(group)), (2, 7), (3, 102), (4, file_id.encode())])
    body = encode([(1, 0x6d6), (2, 2), (4, encode([(3, download)])), (12, 1)])
    return build_sso_request(account, body, COMMAND, material, guid, appid, version, sequence, tea)


def build_sso_request(account, body, command, material, guid, appid, version, sequence, tea):
    trace = ("00-" + secrets.token_hex(16) + "-" + secrets.token_hex(8) + "-01").encode()
    reserved = encode([(15, trace), (16, material["uid"].encode())])
    head = (struct.pack(">III", sequence, appid, 2052) + bytes.fromhex("020000000000000000000000") +
            sized(material["a2"]) + sized(command) + sized(b"") + sized(guid.hex().encode()) +
            sized(b"") + sized(version.encode(), 2) + sized(reserved))
    ciphertext = tea.qqtea_encrypt(sized(head) + sized(body), material["key"])
    return sized(struct.pack(">I", 12) + b"\x01" + sized(material["d2"]) + b"\0" + sized(account.encode()) + ciphertext)


def receive(sock, length):
    if not 0 <= length <= MAX_FRAME:
        raise BridgeError("QQ 网络响应超过上限")
    result = bytearray()
    while len(result) < length:
        block = sock.recv(length - len(result))
        if not block:
            raise BridgeError("QQ 文件请求连接提前结束")
        result.extend(block)
    return bytes(result)


def decode_sso_reply(frame, account, sequence, key, tea, command):
    if len(frame) > MAX_FRAME or len(frame) < 10:
        raise BridgeError("QQ 文件响应大小无效")
    stream = io.BytesIO(frame)
    if stream.read(6) != b"\0\0\0\x0c\x01\0" or take_sized(stream) != account.encode():
        raise BridgeError("QQ 响应协议或账号与本次请求不符")
    encrypted = stream.read()
    if len(encrypted) < 16 or len(encrypted) % 8:
        raise BridgeError("QQ 文件响应密文格式无效")
    try:
        decoded = tea.qqtea_decrypt(encrypted, key)
    except Exception:
        decoded = None
    if not decoded or len(decoded) < 12:
        raise BridgeError("QQ 文件响应会话校验失败")
    stream = io.BytesIO(decoded)
    head_size, got_sequence, code = struct.unpack(">IIi", stream.read(12))
    if got_sequence != sequence or not 12 <= head_size <= len(decoded):
        raise BridgeError("QQ 文件响应序列或头长度不符")
    take_sized(stream)  # Server wording must not enter logs or tool output.
    if code:
        raise BridgeError("QQ 文件请求认证返回 " + str(code))
    if take_sized(stream) != command:
        raise BridgeError("QQ 响应不是本次群文件下载命令")
    take_sized(stream)  # session ID
    raw = stream.read(4)
    if len(raw) != 4:
        raise BridgeError("QQ 文件响应压缩标记缺失")
    compression = int.from_bytes(raw, "big")
    take_sized(stream)
    if stream.tell() > head_size or head_size - stream.tell() > 65536:
        raise BridgeError("QQ 文件响应头格式不支持")
    # Current QQ builds append opaque header extensions. The declared header
    # boundary is authoritative; these extensions are neither used nor logged.
    stream.seek(head_size)
    data = take_sized(stream)
    if stream.read():
        raise BridgeError("QQ 文件响应存在未识别尾部")
    if compression == 1:
        try:
            decoder = zlib.decompressobj()
            data = decoder.decompress(data, MAX_FRAME + 1)
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or len(data) > MAX_FRAME:
                raise ValueError()
        except zlib.error:
            raise BridgeError("QQ 文件响应压缩内容无效") from None
        except ValueError:
            raise BridgeError("QQ 文件响应解压超过上限或不完整") from None
    elif compression == 8:
        if len(data) < 4:
            raise BridgeError("QQ 文件响应压缩内容截断")
        data = data[4:]
    elif compression != 0:
        raise BridgeError("QQ 文件响应压缩格式尚未支持")
    return data


def parse_reply(frame, account, sequence, key, tea):
    envelope = protobuf(decode_sso_reply(frame, account, sequence, key, tea, COMMAND))
    if one(envelope, 1, 0) != 0x6d6 or one(envelope, 2, 0) != 2:
        raise BridgeError("QQ 文件响应业务标识不符")
    code = one(envelope, 3, 0, 0)
    if code >= 1 << 63:
        code -= 1 << 64
    if code:
        raise BridgeError("QQ 群文件服务返回 " + str(code))
    result = protobuf(one(protobuf(one(envelope, 4, 2)), 3, 2))
    code = one(result, 1, 0, 0)
    if code >= 1 << 63:
        code -= 1 << 64
    if code:
        raise BridgeError("QQ 群文件下载返回 " + str(code) + "；文件可能已删除或过期")
    return result


def public_addresses(host, port):
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise BridgeError("QQ 文件服务未解析到公网地址")
    return addresses


def endpoint(result, digest):
    try:
        host = one(result, 5, 2).decode("ascii")
    except UnicodeError:
        raise BridgeError("QQ 文件 CDN 域名无效") from None
    token = one(result, 6, 2)
    if (not re.fullmatch(r"(?:[A-Za-z0-9-]+\.)+qq\.com", host) or len(host) > 253
            or not 1 <= len(token) <= 4096 or one(result, 9, 2).hex() != digest):
        raise BridgeError("QQ 文件下载描述与允许消息的来源校验不符")
    public_addresses(host, 443)
    return "https://" + host + "/ftn_handler/" + token.hex() + "/?fname="


def fetch_group_file(segment, request, info, scan):
    settings, chat = request["settings"], request["chat"]
    if not request.get("fetch_if_missing", True) or not settings.get("active_download", False):
        raise BridgeError("QQ 群文件未缓存，主动下载未启用或本次为 cache_only")
    file_id = str(segment.get("file_uuid") or "")
    digest = str(segment.get("md5_hex") or "").lower()
    authenticated_digest = not digest and segment.get("transport") == "qq_record_group_file" and segment.get("bus_id") == 102
    name = str(segment.get("filename") or "")
    size = int(segment.get("filesize") or 0)
    maximum = int(request.get("maximum_bytes", 100 * 1024**2))
    if (chat.get("kind") != "group" or not str(chat.get("id", "")).isdigit()
            or not re.fullmatch(r"/?[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", file_id)
            or not (re.fullmatch(r"[a-f0-9]{32}", digest) or authenticated_digest) or not 0 < size <= maximum):
        raise BridgeError("QQ 群文件的会话、文件标识、大小或 MD5 不完整")
    if (not name or len(name) > 200 or name != Path(name).name or name.endswith((".", " "))
            or re.search(r'[\\/:*?"<>|\x00-\x1f]', name)
            or name.split(".")[0].upper() in {"CON", "NUL", "AUX", "PRN", *("COM" + str(i) for i in range(1, 10)), *("LPT" + str(i) for i in range(1, 10))}):
        raise BridgeError("QQ 群文件名不适合安全保存")
    binding = check_kernel(settings, info)
    material = read_material(settings, info, scan)
    guid, appid = device_and_app(settings, material)
    tea = crypto()
    sequence = secrets.randbelow(0x7fffff) + 0x10000
    packet = build_request(settings["account"], chat["id"], file_id, material, guid, appid,
                           binding["version"], sequence, tea)
    addresses = public_addresses("msfwifi.3g.qq.com", 8080)
    try:
        # A separate socket carries only this single read request. QQ continues
        # maintaining its own online state; no register/login/heartbeat is sent.
        with socket.create_connection((addresses[0][4][0], 8080), timeout=10) as sock:
            sock.sendall(packet)
            length = int.from_bytes(receive(sock, 4), "big")
            result = parse_reply(receive(sock, length - 4), settings["account"], sequence, material["key"], tea)
        remote_digest = one(result, 9, 2).hex()
        if not re.fullmatch(r"[a-f0-9]{32}", remote_digest) or digest and remote_digest != digest:
            raise BridgeError("QQ 文件服务校验值与原始消息不符")
        digest = remote_digest
        url = endpoint(result, digest)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(url, timeout=35) as response:
            if response.status != 200:
                raise BridgeError("QQ 文件 CDN 返回非成功状态")
            body = response.read(size + 1)
    except (OSError, urllib.error.URLError):
        raise BridgeError("QQ 群文件后台请求未完成，请稍后重新查询和取回") from None
    if len(body) != size or hashlib.md5(body).hexdigest() != digest:
        raise BridgeError("QQ 下载文件与原始消息的大小或 MD5 不一致，未保存")
    check_kernel(settings, info)
    destination = Path(request["target"]) / name
    with destination.open("xb") as output:
        output.write(body)
    return {"files": [str(destination)], "media_tier": "file", "source_digest_verified": True,
            "save_method": "qq_group_file_sso_download", "transport": "qq_sso_then_https",
            "runtime_kernel": binding["version"], "digest_origin": "qq_authenticated_file_metadata" if authenticated_digest else "source_message"}
