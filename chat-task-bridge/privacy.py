"""Small Windows privacy controls; no daemon, account changes or client writes."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys
import time
import warnings

RECEIPT_TTL = 3600
PRIVATE_FORMAT = "chat-task-receipt/dpapi-v1"
ENTROPY = b"chat-task-bridge/receipt/v1"


class PrivacyError(ValueError):
    pass


def require_safe_runtime():
    from importlib.metadata import version
    if sys.version_info[:2] != (3, 13) or sys.version_info[:3] < (3, 13, 18):
        raise PrivacyError("请使用已验证的Python 3.13.18或3.13分支更新安全版本，未读取客户端")
    installed = tuple(map(int, re.match(r"(\d+)\.(\d+)\.(\d+)", version("pillow")).groups()))
    if installed < (13, 0, 0):
        raise PrivacyError("图片库需要安全更新，请重新安装固定依赖，未读取客户端")


def reject_reparse(path):
    """Do not apply privacy changes or writes through links / junctions."""
    path = Path(path).absolute()
    for node in (path, *path.parents):
        if node.exists() and node.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise PrivacyError("取材目录含链接或联接，未通过该路径读写私人材料")
    return path


def _protect_path(path):
    """Protected DACL: current user, SYSTEM and local administrators only."""
    import win32api
    import win32con
    import win32security as security
    import ntsecuritycon

    path = reject_reparse(path)
    if not path.exists():
        raise PrivacyError("需要保护的路径不存在")
    token = security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        user = security.GetTokenInformation(token, security.TokenUser)[0]
    finally:
        token.Close()
    allowed = [user, security.CreateWellKnownSid(security.WinLocalSystemSid),
               security.CreateWellKnownSid(security.WinBuiltinAdministratorsSid)]
    current = security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT, security.DACL_SECURITY_INFORMATION)
    dacl = current.GetSecurityDescriptorDacl()
    # Avoid repeatedly propagating permissions through a populated download tree.
    flags = security.OBJECT_INHERIT_ACE | security.CONTAINER_INHERIT_ACE if path.is_dir() else 0
    if (current.GetSecurityDescriptorControl()[0] & security.SE_DACL_PROTECTED and dacl is not None
            and dacl.GetAceCount() == 3
            and {str(dacl.GetAce(i)[2]) for i in range(3)} == {str(sid) for sid in allowed}
            and all(dacl.GetAce(i)[0][0] == security.ACCESS_ALLOWED_ACE_TYPE
                    and dacl.GetAce(i)[0][1] == flags
                    and dacl.GetAce(i)[1] == ntsecuritycon.FILE_ALL_ACCESS
                    and dacl.GetAce(i)[2] in allowed for i in range(3))):
        return
    acl = security.ACL()
    for sid in allowed:
        acl.AddAccessAllowedAceEx(security.ACL_REVISION, flags, ntsecuritycon.FILE_ALL_ACCESS, sid)
    security.SetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
        security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION, None, None, acl, None)


def protect_path(path):
    try:
        _protect_path(path)
    except PrivacyError:
        raise
    except Exception:
        raise PrivacyError("无法保护取材路径权限，已停止读取私人材料") from None


def private_directory(path):
    path = reject_reparse(path)
    path.mkdir(parents=True, exist_ok=True)
    protect_path(path)
    return path


def write_receipt(path, value):
    import win32crypt
    path = reject_reparse(path)
    private_directory(path.parent)
    plain = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = win32crypt.CryptProtectData(plain, "Chat task receipt", ENTROPY, None, None, 1)
    envelope = {"format": PRIVATE_FORMAT, "sealed": base64.b64encode(ciphertext).decode("ascii")}
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(envelope, stream)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_receipt(path):
    import win32crypt
    path = reject_reparse(path)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise PrivacyError("查询凭据超过上限，请重新查询")
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if envelope.get("format") != PRIVATE_FORMAT:
        raise PrivacyError("旧版明文查询凭据已停用，请按当前任务重新查询")
    try:
        sealed = base64.b64decode(envelope["sealed"], validate=True)
        _, plain = win32crypt.CryptUnprotectData(sealed, ENTROPY, None, None, 1)
        return json.loads(plain)
    except Exception:
        raise PrivacyError("查询凭据损坏或不属于当前Windows用户，请重新查询") from None


def cleanup_receipts(directory, now=None):
    """On-demand expiry, based on file time; never read stored message text."""
    directory = reject_reparse(directory)
    if not directory.is_dir():
        return 0
    now = time.time() if now is None else now
    removed = 0
    for path in directory.iterdir():
        if re.fullmatch(r"[a-f0-9]{32}\.json", path.name) and not path.is_symlink():
            reject_reparse(path)
            if path.is_file():
                with path.open("rb") as stream:
                    sealed = PRIVATE_FORMAT.encode() in stream.read(128)
                if not sealed or now - path.stat().st_mtime > RECEIPT_TTL:
                    path.unlink()
                    removed += 1
    return removed


def mark_download(path):
    path = reject_reparse(path)
    # Windows recognizes the source zone when a user later opens the attachment.
    with open(str(path) + ":Zone.Identifier", "w", encoding="ascii") as stream:
        stream.write("[ZoneTransfer]\nZoneId=3\n")


def worker_environment():
    names = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
             "PROGRAMDATA", "USERNAME", "USERDOMAIN", "HOMEDRIVE", "HOMEPATH"}
    result = {k: v for k, v in os.environ.items() if k.upper() in names}
    result.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    return result


def verify_image(source):
    """Parse only supported raster formats; never load EPS or external decoders."""
    from PIL import Image
    formats = ["JPEG", "PNG", "GIF", "WEBP", "BMP", "TIFF"]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source, formats=formats) as image:
                if min(image.size) <= 0 or image.width * image.height > 40_000_000:
                    raise PrivacyError("图片像素超过安全上限")
                result = image.format, image.size
                image.verify()
                return result
    except PrivacyError:
        raise
    except Exception:
        raise PrivacyError("图片格式不支持或未通过安全校验") from None


def cleanup_scratch(state):
    """Caller must hold the state lock; remove only this bridge's abandoned work."""
    state = reject_reparse(state).resolve()
    if state == Path(state.anchor):
        raise PrivacyError("不能把磁盘根目录作为临时取材目录")
    for path in state.glob("wx-request-*"):
        reject_reparse(path)
        target = path.resolve()
        if target.parent != state or not re.fullmatch(r"wx-request-[a-z0-9_]+", path.name):
            raise PrivacyError("临时取材路径超出清理范围")
        if target.is_dir():
            shutil.rmtree(target)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    protect_path(root)
    if sys.prefix != sys.base_prefix:
        protect_path(Path(sys.prefix).resolve())
    skill = root.parent / "qq-wechat-task-materials"
    if (skill / "SKILL.md").is_file():
        protect_path(skill)
    print("已保护本工具的程序、运行环境和相邻技能目录。")
