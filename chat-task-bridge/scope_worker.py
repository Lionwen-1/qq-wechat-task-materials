"""Exact group metadata lookup. This worker never opens a message database."""
import contextlib
import io
import json
from pathlib import Path
import sys

from bridge import BridgeError


def qq_groups(conn, target):
    if target.isdigit():
        rows = conn.execute('SELECT "60001" id,"60007" name FROM group_list WHERE "60001" IN (?,?) LIMIT 3',
                            (target, int(target))).fetchall()
    else:
        rows = conn.execute('SELECT "60001" id,"60007" name FROM group_list WHERE "60007"=? LIMIT 3',
                            (target,)).fetchall()
    return [{"platform": "qq", "kind": "group", "id": str(r["id"]),
             "name": r["name"] or "QQ群" + str(r["id"]), "remark": ""} for r in rows]


def wechat_groups(conn, target):
    rows = conn.execute("SELECT username,nick_name,remark FROM contact WHERE (username=? OR nick_name=? OR remark=?) AND username LIKE '%@chatroom' LIMIT 3",
                        (target, target, target)).fetchall()
    return [{"platform": "wechat", "kind": "group", "id": r["username"],
             "name": r["nick_name"] or r["remark"] or r["username"], "remark": r["remark"] or ""} for r in rows]


def resolve(request):
    target = request.get("target", "")
    if request.get("operation") != "resolve_group" or not isinstance(target, str) or not 0 < len(target) <= 256 or "\0" in target:
        raise BridgeError("必须给出一个精确群名、群号或群备注名")
    settings, platform, scratch = request["settings"], request["chat"]["platform"], Path(request["scratch"])
    if platform == "qq":
        from qq_db_worker import identity, open_db
        info = identity(settings)
        source = Path(info["source"]).with_name("group_info.db")
        with contextlib.closing(open_db(settings, dict(info, source=str(source)), scratch)) as conn:
            rows = qq_groups(conn, target)
        if identity(settings) != info:
            raise BridgeError("QQ 账号在群名定位期间变化")
    elif platform == "wechat":
        from wechat_identity import inspect_identity
        from wechat_db_worker import load_read_modules, create_reader
        info = inspect_identity(settings)
        module, _ = load_read_modules()
        db = create_reader(request, module, info, scratch)
        rels = [rel for rel, path, size in db._db_files if Path(path).name == "contact.db"]
        if len(rels) != 1:
            raise BridgeError("微信联系人库未唯一确定")
        with contextlib.closing(db._open(rels[0])) as conn:
            rows = wechat_groups(conn, target)
        db._keys.clear()
        if inspect_identity(settings) != info:
            raise BridgeError("微信账号在群名定位期间变化")
    else:
        raise BridgeError("不支持的平台")
    return {"groups": rows, "metadata_only": True, "message_database_opened": False}


def main():
    try:
        request = json.load(sys.stdin)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = resolve(request)
        payload = {"ok": True, "result": result}
    except BridgeError as exc:
        payload = {"ok": False, "error": str(exc)}
    except Exception as exc:
        payload = {"ok": False, "error": "群名定位失败：" + type(exc).__name__}
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
