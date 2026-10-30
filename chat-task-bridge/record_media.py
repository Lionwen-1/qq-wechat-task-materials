"""Source-bound merged-record media; fixed QQ endpoints, verified HTTPS only."""
import hashlib
import io
from pathlib import Path
import re
import secrets
import socket
import urllib.error
import urllib.parse
import urllib.request

from bridge import BridgeError, NoRedirect
from privacy import verify_image
from qq_group_file import (build_sso_request, crypto, decode_sso_reply, encode,
                           public_addresses, receive)
from qq_session import check_kernel, device_and_app, read_material
from wechat_cdn import one, protobuf

PRIVATE_FILE_COMMAND = b"OidbSvcTrpcTcp.0xe37_1200"


def safe_name(value):
    if (not isinstance(value, str) or not value or len(value) > 200 or value != Path(value).name
            or value.endswith((".", " ")) or re.search(r'[\\/:*?"<>|\x00-\x1f]', value)
            or value.split('.')[0].upper() in {"CON", "NUL", "AUX", "PRN", *("COM" + str(i) for i in range(1, 10)), *("LPT" + str(i) for i in range(1, 10))}):
        raise BridgeError("附件文件名不适合安全保存")
    return value


def source_limits(descriptor, request):
    digest = str(descriptor.get("md5_hex") or descriptor.get("md5") or "").lower()
    size = int(descriptor.get("filesize") or descriptor.get("size") or 0)
    maximum = int(request.get("maximum_bytes", 100 * 1024**2))
    if not re.fullmatch(r"[a-f0-9]{32}", digest) or not 0 < size <= maximum:
        raise BridgeError("合并记录附件缺少有效的来源大小或MD5，或超过上限")
    return digest, size


def network_allowed(request):
    if not request.get("fetch_if_missing", True) or not request["settings"].get("active_download", False):
        raise BridgeError("合并记录附件未缓存；主动下载未启用或本次为cache_only")


def save_bytes(body, descriptor, request, kind, method):
    digest, size = source_limits(descriptor, request)
    if len(body) != size or hashlib.md5(body).hexdigest() != digest:
        raise BridgeError("合并记录附件与来源大小或MD5不一致，未保存")
    result = {"media_tier": "source_verified", "source_digest_verified": True, "save_method": method, "transport": "qq_https_cdn"}
    if kind == "image":
        fmt, dimensions = verify_image(io.BytesIO(body))
        extension = {"JPEG": ".jpg", "MPO": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tif"}.get(fmt)
        if not extension:
            raise BridgeError("合并图片格式不支持")
        name = digest + extension
        result["dimensions"] = list(dimensions)
    else:
        name = safe_name(descriptor.get("filename"))
    out = Path(request["target"]) / name
    with out.open("xb") as stream:
        stream.write(body)
    return {"files": [str(out)], **result}


def get_https(url, size):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in {None, 443}
            or parsed.fragment or not parsed.hostname or not re.fullmatch(r"(?:[A-Za-z0-9-]+\.)+(?:qq\.com|qpic\.cn)", parsed.hostname)):
        raise BridgeError("合并附件端点不符合已验证HTTPS范围")
    public_addresses(parsed.hostname, 443)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(url, timeout=30) as response:
            if response.status != 200:
                raise BridgeError("合并附件服务返回非成功状态")
            return response.read(size + 1)
    except (OSError, urllib.error.URLError):
        raise BridgeError("合并附件安全下载未完成；可能已过期或不可用") from None


def fetch_qq_legacy_image(descriptor, request):
    digest, size = source_limits(descriptor, request)
    network_allowed(request)
    if request.get("image_tier") == "thumbnail":
        raise BridgeError("合并记录未提供可校验的缩略图；可请求原图")
    # Construct from the source digest, never use a URL supplied by message text.
    url = "https://gchat.qpic.cn/gchatpic_new/0/0-0-" + digest.upper() + "/0"
    return save_bytes(get_https(url, size), descriptor, request, "image", "qq_merged_image_https")


def private_endpoint(result):
    host = one(result, 20, 2).decode("ascii")
    path = one(result, 50, 2).decode("ascii")
    if (not re.fullmatch(r"(?:[A-Za-z0-9-]+\.)+qq\.com", host) or not path.startswith("/ftn_handler/")
            or path.startswith("//") or any(ord(c) < 33 or ord(c) > 126 for c in path) or "#" in path or "\\" in path):
        raise BridgeError("合并文件服务端点不符合已验证范围")
    return "https://" + host + path + ("&" if "?" in path else "?") + "isthumb=0"


def fetch_qq_private_file(descriptor, request, info, scan):
    digest, size = source_limits(descriptor, request)
    safe_name(descriptor.get("filename"))
    network_allowed(request)
    uuid, file_hash = descriptor.get("file_uuid", ""), descriptor.get("file_hash", "")
    if not all(isinstance(v, str) and 0 < len(v) <= 1024 and not re.search(r"[\s\x00-\x1f]", v) for v in (uuid, file_hash)):
        raise BridgeError("合并文件缺少来源UUID或Hash")
    settings = request["settings"]
    binding = check_kernel(settings, info)
    material = read_material(settings, info, scan)
    guid, appid = device_and_app(settings, material)
    inner = encode([(1, 1200), (2, 1), (14, encode([(10, material["uid"].encode()), (20, uuid.encode()), (30, 2), (60, file_hash.encode()), (601, 0)])),
                    (101, 3), (102, 103), (200, 1), (99999, b"\xc0\x85\x2c\x01")])
    body = encode([(1, 0xe37), (2, 1200), (4, inner), (12, 0)])
    tea, sequence = crypto(), secrets.randbelow(0x7fffff) + 0x10000
    packet = build_sso_request(settings["account"], body, PRIVATE_FILE_COMMAND, material, guid, appid, binding["version"], sequence, tea)
    address = public_addresses("msfwifi.3g.qq.com", 8080)[0][4][0]
    try:
        with socket.create_connection((address, 8080), timeout=15) as sock:
            sock.sendall(packet)
            length = int.from_bytes(receive(sock, 4), "big")
            envelope = protobuf(decode_sso_reply(receive(sock, length - 4), settings["account"], sequence, material["key"], tea, PRIVATE_FILE_COMMAND))
    except OSError:
        raise BridgeError("合并文件下载描述未能安全取回") from None
    if one(envelope, 1, 0) != 0xe37 or one(envelope, 2, 0) != 1200 or one(envelope, 3, 0, 0):
        raise BridgeError("合并文件响应业务或状态校验失败")
    response = protobuf(one(envelope, 4, 2))
    result = protobuf(one(protobuf(one(response, 14, 2)), 30, 2))
    url = private_endpoint(result)
    body = get_https(url, size)
    check_kernel(settings, info)
    return save_bytes(body, descriptor, request, "file", "qq_merged_private_file_https")
