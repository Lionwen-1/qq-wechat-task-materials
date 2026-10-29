"""Read one bound QQ session via MSVC RTTI. Never writes into the client.

Protocol/layout references: QQShark scan.rs (SessionForNt RTTI and fields),
qq_guid_tool/windows/README.md (Registry20 DPAPI format), WeQ sso_session.ts
(runtime app ID). This module is an independent, narrowly scoped reader.
"""
from __future__ import annotations
import ctypes
from pathlib import Path
import re
import struct
import time

from bridge import BridgeError, sha256_file

SUPPORTED_KERNELS = {"9.9.36-53644"}


def kernel_binding(settings, info):
    import psutil
    paths = {Path(m.path).resolve() for m in psutil.Process(info["pid"]).memory_maps()
             if m.path.lower().endswith("wrapper.node")}
    if len(paths) != 1:
        raise BridgeError("QQ 运行内核未唯一确定")
    wrapper = next(iter(paths))
    root = Path(settings["executable"]).resolve().parent / "versions"
    if not wrapper.is_relative_to(root) or wrapper.parent.name != "app":
        raise BridgeError("QQ 内核不在绑定安装目录中")
    major = wrapper.with_name("major.node")
    if not major.is_file():
        raise BridgeError("QQ 当前内核缺少 major.node")
    version = wrapper.parents[2].name
    return {"version": version, "wrapper_sha256": sha256_file(wrapper),
            "major_sha256": sha256_file(major)}


def check_kernel(settings, info):
    actual = kernel_binding(settings, info)
    if actual["version"] not in SUPPORTED_KERNELS:
        raise BridgeError("此 QQ 运行内核的群文件下载尚未实机验证")
    if actual != settings.get("group_file_kernel"):
        raise BridgeError("QQ 群文件内核绑定缺失或已变化，请用 bind_local.py 重新核验绑定")
    return actual


def read_material(settings, info, scan):
    """Return validated fields to this request process only; never serialize."""
    import psutil
    handle = scan.k32.OpenProcess(0x410, False, info["pid"])
    if not handle:
        raise BridgeError("无法只读访问当前 QQ 会话")

    def read(address, size):
        if not 0 < size <= 256 * 1024**2 or not 0x10000 < address < 0x800000000000:
            return b""
        buf, got = ctypes.create_string_buffer(size), ctypes.c_size_t(0)
        scan.k32.ReadProcessMemory(handle, address, buf, size, ctypes.byref(got))
        return buf.raw[:got.value]

    try:
        maps = psutil.Process(info["pid"]).memory_maps(grouped=False)
        wrappers = [m for m in maps if m.path.lower().endswith("wrapper.node")]
        if not wrappers or len({m.path.lower() for m in wrappers}) != 1:
            raise BridgeError("QQ 会话模块未唯一确定")
        base = min(int(m.addr, 16) for m in wrappers)
        dos = read(base, 4096)
        if len(dos) != 4096 or dos[:2] != b"MZ":
            raise BridgeError("QQ 模块头不支持")
        pe = struct.unpack_from("<I", dos, 0x3c)[0]
        if not 0 <= pe < 3900 or dos[pe:pe + 4] != b"PE\0\0":
            raise BridgeError("QQ 模块 PE 标识无效")
        image_size = struct.unpack_from("<I", dos, pe + 24 + 56)[0]
        if not 0 < image_size <= 256 * 1024**2:
            raise BridgeError("QQ 模块大小不支持")
        regions, address = [], 0
        mbi = scan.MEMORY_BASIC_INFORMATION64()
        while scan.k32.VirtualQueryEx(handle, address, ctypes.byref(mbi), ctypes.sizeof(mbi)):
            start, size = int(mbi.BaseAddress), int(mbi.RegionSize)
            if size <= 0:
                break
            protection = mbi.Protect & 0xff
            if mbi.State == 0x1000 and protection in {2, 4, 8, 0x20, 0x40, 0x80} and not mbi.Protect & 0x100:
                regions.append((start, size, protection, mbi.Type))
            if start + size <= address:
                break
            address = start + size
        image = bytearray(image_size)
        for start, size, _, _ in regions:
            if base <= start < base + image_size:
                data = read(start, min(size, base + image_size - start))
                image[start - base:start - base + len(data)] = data
        names = [m.start() for m in re.finditer(re.escape(b".?AVSessionForNt@nt@@\0"), image)]
        if len(names) != 1:
            raise BridgeError("QQ 会话 RTTI 标识不唯一")
        descriptor = names[0] - 16
        vtables = set()
        for match in re.finditer(re.escape(struct.pack("<I", descriptor)), image):
            locator = match.start() - 12
            if locator < 0 or locator % 4 or locator + 24 > len(image):
                continue
            signature, offset, _, typ, _, self_rva = struct.unpack_from("<6I", image, locator)
            if signature != 1 or offset != 0 or typ != descriptor or self_rva != locator:
                continue
            for ref in re.finditer(re.escape(struct.pack("<Q", base + locator)), image):
                table = ref.start() + 8
                if table % 8 or table + 8 > len(image):
                    continue
                function = struct.unpack_from("<Q", image, table)[0]
                if any(s <= function < s + n and prot in (0x20, 0x40, 0x80) for s, n, prot, _ in regions):
                    vtables.add(base + table)
        if not 0 < len(vtables) <= 8:
            raise BridgeError("QQ 会话虚表未唯一定位")
        patterns = [struct.pack("<Q", value) for value in vtables]
        deadline, scanned = time.monotonic() + 15, 0
        for start, size, prot, kind in regions:
            if kind != 0x20000 or prot not in (4, 0x40) or size > 256 * 1024**2:
                continue
            for offset in range(0, size, 1024**2):
                if time.monotonic() > deadline or scanned > 2 * 1024**3:
                    raise BridgeError("QQ 会话只读定位超时")
                chunk = read(start + offset, min(1024**2, size - offset))
                scanned += len(chunk)
                for pattern in patterns:
                    for match in re.finditer(re.escape(pattern), chunk):
                        instance = start + offset + match.start()
                        if instance % 8:
                            continue
                        material = decode_fields(read, instance)
                        if material:
                            material["wrapper"] = Path(wrappers[0].path)
                            return material
        raise BridgeError("当前 QQ 没有完整且可校验的会话凭据")
    finally:
        scan.k32.CloseHandle(handle)


def decode_fields(read, instance):
    # QByteArray layouts observed in QQ's MSVC builds. All three fields must
    # agree on a layout; the current .36 build uses length+8 / pointer+16.
    candidates = []
    for length_offset, pointer_offset in ((0, 8), (8, 16)):
        fields = []
        for offset in (0x158, 0x170, 0x188):
            meta = read(instance + offset, 24)
            if len(meta) != 24:
                break
            length = struct.unpack_from("<Q", meta, length_offset)[0]
            pointer = struct.unpack_from("<Q", meta, pointer_offset)[0]
            if not 0 < length <= 4096 or length % 2:
                break
            value = read(pointer, length)
            if len(value) != length or not re.fullmatch(rb"[0-9a-fA-F]+", value):
                break
            fields.append(bytes.fromhex(value.decode()))
        if len(fields) == 3 and len(fields[2]) == 16 and len(fields[0]) >= 64 and len(fields[1]) >= 64:
            candidates.append(fields)
    if len(candidates) != 1:
        return None
    uids = set()
    for offset in range(8, 0x400, 8):
        meta = read(instance + offset, 24)
        if len(meta) != 24:
            continue
        for lo, po in ((0, 8), (8, 16)):
            if struct.unpack_from("<Q", meta, lo)[0] == 24:
                value = read(struct.unpack_from("<Q", meta, po)[0], 24)
                if re.fullmatch(rb"u_[A-Za-z0-9_-]{22}", value):
                    uids.add(value.decode())
    if len(uids) != 1:
        return None
    a2, d2, key = candidates[0]
    return {"a2": a2, "d2": d2, "key": key, "uid": next(iter(uids))}


def device_and_app(settings, material):
    import win32crypt
    root = Path(settings["db_path"]).resolve().parents[3]
    path = root / "nt_qq/global/nt_data/msf/Registry20"
    if not path.is_file() or not 0 < path.stat().st_size <= 8192:
        raise BridgeError("当前 QQ 设备标识缓存不可用，未创建新设备身份")
    try:
        plain = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 1)[1]
    except Exception:
        raise BridgeError("当前用户无法读取 QQ 设备标识缓存") from None
    if len(plain) != 20 or int.from_bytes(plain[:4], "big") != 20:
        raise BridgeError("QQ 设备标识格式不支持")
    guid = bytes(b ^ 0xef for b in plain[4:])
    path = material["wrapper"].with_name("major.node")
    appids = {int(v) for v in re.findall(rb"QQAppId/([0-9]{9})", path.read_bytes())}
    if len(appids) != 1:
        raise BridgeError("当前 QQ 构建的 App ID 未唯一确定")
    return guid, next(iter(appids))
