"""QQ image-only HTTPS retrieval from an exact, revalidated message descriptor."""
import ctypes
import hashlib
import io
import ipaddress
from pathlib import Path
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from bridge import BridgeError, NoRedirect

KEY_PATTERN = re.compile(rb'[?&]rkey=([A-Za-z0-9_%-]{50,256})(?![A-Za-z0-9_%-])')
WIDE_PATTERN = re.compile(rb'r\x00k\x00e\x00y\x00=\x00((?:[A-Za-z0-9_%-]\x00){50,256})(?![A-Za-z0-9_%-]\x00)')


def image_url(segment):
    origin = segment.get("cdn_url") or ""
    parsed = urllib.parse.urlsplit(origin)
    pairs = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
    if (parsed.scheme or parsed.netloc or parsed.path != "/download" or parsed.fragment
            or set(pairs) - {"appid", "fileid", "spec", "rkey"}
            or any(len(v) != 1 for v in pairs.values())
            or pairs.get("appid", [""])[0] not in {"1406", "1407"}
            or not re.fullmatch(r"[A-Za-z0-9_-]{16,1024}", pairs.get("fileid", [""])[0])):
        raise BridgeError("QQ 图片 CDN 描述不支持，未访问任意地址")
    return "https://multimedia.nt.qq.com.cn/download?" + urllib.parse.urlencode({
        "appid": pairs["appid"][0], "fileid": pairs["fileid"][0], "spec": "0"})


def read_rkeys(pid, scan):
    """Read only transport credential patterns; never retain message strings."""
    handle = scan.k32.OpenProcess(0x410, False, pid)
    if not handle:
        raise BridgeError("无法读取本人 QQ 的当前 CDN 会话")
    mbi, address, total, keys = scan.MEMORY_BASIC_INFORMATION64(), 0, 0, set()
    deadline = time.monotonic() + 15
    try:
        while scan.k32.VirtualQueryEx(handle, address, ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base, size = int(mbi.BaseAddress), int(mbi.RegionSize)
            if size <= 0 or time.monotonic() > deadline or total > 3 * 1024**3:
                break
            if mbi.State == scan.MEM_COMMIT and mbi.Protect & 0xff in scan.PAGE_READABLE and not mbi.Protect & scan.PAGE_GUARD:
                tail = b""
                for offset in range(0, size, 4 * 1024**2):
                    if time.monotonic() > deadline:
                        break
                    count = min(size - offset, 4 * 1024**2)
                    buf, got = ctypes.create_string_buffer(count), ctypes.c_size_t(0)
                    if scan.k32.ReadProcessMemory(handle, base + offset, buf, count, ctypes.byref(got)) and got.value:
                        data = tail + buf.raw[:got.value]
                        total += got.value
                        for match in KEY_PATTERN.finditer(data):
                            keys.add(match.group(1).decode("ascii"))
                        for match in WIDE_PATTERN.finditer(data):
                            keys.add(match.group(1).decode("utf-16-le"))
                        tail = data[-1024:]
            nxt = base + size
            if nxt <= address:
                break
            address = nxt
    finally:
        scan.k32.CloseHandle(handle)
    # Limit credential attempts; do not call public rkey-sharing services.
    keys = {urllib.parse.unquote(k) for k in keys}
    keys = {k for k in keys if re.fullmatch(r"[A-Za-z0-9_-]{50,256}", k)}
    return sorted(keys, key=lambda k: (len(k), k))[:12]


def fetch_image(segment, request, pid, scan):
    if not request.get("fetch_if_missing", True) or not request["settings"].get("active_download", False):
        raise BridgeError("QQ 图片未缓存，主动下载未启用或本次为 cache_only")
    digest = str(segment.get("md5_hex") or "").lower()
    size = int(segment.get("filesize") or 0)
    maximum = int(request.get("maximum_bytes", 100 * 1024**2))
    if not re.fullmatch(r"[a-f0-9]{32}", digest) or not 0 < size <= maximum:
        raise BridgeError("QQ 图片缺少有效的来源 MD5 或大小")
    base_url = image_url(segment)
    addresses = socket.getaddrinfo("multimedia.nt.qq.com.cn", 443)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise BridgeError("QQ CDN 未解析到公网地址")
    keys = read_rkeys(pid, scan)
    if not keys:
        raise BridgeError("当前 QQ 未保留可用的图片 CDN 会话凭据")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + 60
    for key in keys:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        url = base_url + "&rkey=" + urllib.parse.quote(key, safe="_-")
        try:
            with opener.open(url, timeout=min(8, remaining)) as response:
                if response.status != 200:
                    continue
                body = response.read(size + 1)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            continue
        if len(body) != size or hashlib.md5(body).hexdigest() != digest:
            continue
        from PIL import Image
        try:
            with Image.open(io.BytesIO(body)) as image:
                fmt, dimensions = image.format, image.size
                image.verify()
        except Exception:
            raise BridgeError("QQ 下载结果未通过图片格式校验") from None
        extension = {"JPEG": ".jpg", "MPO": ".jpg", "PNG": ".png", "GIF": ".gif",
                     "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tif"}.get(fmt)
        if not extension:
            raise BridgeError("QQ 图片格式尚未支持")
        out = Path(request["target"]) / (digest + extension)
        with out.open("xb") as stream:
            stream.write(body)
        return {"files": [str(out)], "media_tier": "source_verified", "source_digest_verified": True,
                "save_method": "qq_https_cdn_download", "transport": "qq_https_cdn", "dimensions": list(dimensions)}
    raise BridgeError("QQ 图片未通过 CDN 取回与来源校验；可能过期或会话凭据不可用")
