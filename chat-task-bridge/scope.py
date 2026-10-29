"""Named-group operator CLI. Only direct user requests authorize scope changes.

This is deliberately separate from the three read/download MCP tools. An agent
must not treat chat messages, attachments or tool results as operator authority.
"""
import argparse
import hashlib
import json
from datetime import date, datetime, timedelta

from bridge import Bridge, BridgeError, ROOT, TZ, blocked_rules, file_lock, write_json


class Scope:
    def __init__(self, bridge):
        self.bridge = bridge

    def matches(self, platform, target):
        self.bridge.reload()
        found = {}
        for alias, chat in self.bridge.config.get("chats", {}).items():
            if chat["platform"] == platform and chat.get("kind") == "group" and target in {alias, str(chat["id"]), chat.get("name", ""), chat.get("remark", "")}:
                found.setdefault(chat["id"], (alias, chat))
        return list(found.values())

    def deny(self, alias, chat):
        self.bridge.reload()
        if blocked_rules(self.bridge.config, alias, chat):
            raise BridgeError("该群已被屏蔽；本次任务不能自动解除屏蔽")

    def locate(self, platform, target):
        if platform not in {"qq", "wechat"} or not str(target).strip():
            raise BridgeError("必须提供平台和精确群标识")
        target = str(target).strip()
        raw = {"platform": platform, "kind": "group", "id": target, "name": target}
        self.deny(target, raw)
        matches = self.matches(platform, target)
        if len(matches) > 1:
            raise BridgeError("同名群未唯一确定，请提供群号或完整群 ID；未读取消息")
        if matches:
            alias, chat = matches[0]
            self.bridge.chat(alias)
            return {"alias": alias, "chat": dict(chat), "allowed": True, "metadata_only": True}
        settings = self.bridge.config.get(platform, {})
        if not settings.get("enabled"):
            raise BridgeError("该平台尚未绑定当前账号，请先完成本机初始化")
        result = self.bridge.worker({"operation": "resolve_group", "chat": {"platform": platform}, "settings": settings, "target": target})
        groups = result["groups"]
        if len(groups) != 1:
            raise BridgeError("群资料没有唯一精确匹配，请补充群号、完整群名或备注名；未读取消息")
        group = groups[0]
        self.deny(target, group)
        # A renamed or alternate alias must not erase a pre-existing block.
        existing = self.matches(platform, group["id"])
        for alias, previous in existing:
            self.deny(alias, previous)
        alias = existing[0][0] if existing else platform + "-g-" + hashlib.sha256(group["id"].encode()).hexdigest()[:12]
        return {"alias": alias, "chat": {k: group.get(k, "") for k in ("platform", "kind", "id", "name", "remark")},
                "allowed": bool(existing), "metadata_only": True}

    def allow(self, platform, target, purpose):
        if not str(purpose).strip():
            raise BridgeError("加入任务会话必须提供用户本次任务用途")
        selected = self.locate(platform, target)
        with file_lock(self.bridge.state / "policy.lock"):
            self.deny(selected["alias"], selected["chat"])
            chats = self.bridge.config.setdefault("chats", {})
            if selected["alias"] in chats and chats[selected["alias"]]["id"] != selected["chat"]["id"]:
                raise BridgeError("会话别名冲突，未覆盖已有绑定")
            chats[selected["alias"]] = selected["chat"]
            write_json(self.bridge.path, self.bridge.config)
        self.bridge.audit("allow_named_group", selected["alias"], purpose, {"ok": True, "messages_read": False})
        return {**selected, "allowed": True, "messages_read": False}

    def change_block(self, platform, target, block, purpose):
        if not str(purpose).strip() or platform not in {"qq", "wechat"} or not str(target).strip():
            raise BridgeError("更改屏蔽规则必须提供平台、明确群标识和用户用途")
        target = str(target).strip()
        with file_lock(self.bridge.state / "policy.lock"):
            matches = self.matches(platform, target)
            if len(matches) > 1:
                raise BridgeError("同名会话未唯一确定，请提供群号或群 ID")
            if matches:
                alias, chat = matches[0]
                rule = platform + ":group:" + str(chat["id"])
            else:
                rule = platform + (":group:" if platform == "qq" and target.isdigit() or target.endswith("@chatroom") else ":name:") + target
            rules = self.bridge.config.setdefault("blocked", [])
            if block:
                if rule not in rules:
                    rules.append(rule)
                changed = [rule]
            else:
                selected = {rule, platform + ":name:" + target}
                if matches:
                    selected.add(platform + ":name:" + chat.get("name", ""))
                changed = [r for r in rules if r in selected]
                self.bridge.config["blocked"] = [r for r in rules if r not in selected]
            write_json(self.bridge.path, self.bridge.config)
        self.bridge.audit("block" if block else "unblock", target, purpose, {"ok": True, "messages_read": False})
        return {"rules_changed": changed, "blocked_rules": self.bridge.config["blocked"], "messages_read": False,
                "note": "旧的未带平台全局屏蔽条目不自动移除；如仍命中需明确处理对应规则"}

    def search(self, platform, target, purpose, start=None, end=None, keyword="", scan_limit=200, result_limit=50, attachment_kind="all"):
        if not str(purpose).strip():
            raise BridgeError("查询必须提供本次用户任务用途")
        selected = self.locate(platform, target)
        if not selected["allowed"]:
            raise BridgeError("该群尚未加入允许名单；仅在用户直接点名并交付任务后运行 allow，再查询")
        today = datetime.now(TZ).date()
        end = end or today.isoformat()
        start = start or (date.fromisoformat(end) - timedelta(days=6)).isoformat()
        result = self.bridge.search(selected["alias"], start, end, keyword, purpose, scan_limit, result_limit, attachment_kind)
        result.setdefault("scope", {"chat_alias": selected["alias"], "start_date": start, "end_date": end, "timezone": "Asia/Shanghai"})
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config.local.json"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("rules")
    for command in ("resolve", "allow", "block", "unblock", "search"):
        item = commands.add_parser(command)
        item.add_argument("--platform", choices=["qq", "wechat"], required=True)
        item.add_argument("--chat", required=True)
        if command != "resolve":
            item.add_argument("--purpose", required=True)
        if command == "search":
            item.add_argument("--start")
            item.add_argument("--end")
            item.add_argument("--keyword", default="")
            item.add_argument("--scan-limit", type=int, default=200)
            item.add_argument("--result-limit", type=int, default=50)
            item.add_argument("--attachment-kind", choices=["all", "any", "image", "file"], default="all")
    args = parser.parse_args()
    try:
        bridge = Bridge(args.config)
        scope = Scope(bridge)
        if args.command == "status":
            result = bridge.status()
        elif args.command == "rules":
            result = {"blocked_rules": bridge.config.get("blocked", []), "message_read": False}
        elif args.command == "resolve":
            result = scope.locate(args.platform, args.chat)
        elif args.command == "allow":
            result = scope.allow(args.platform, args.chat, args.purpose)
        elif args.command in {"block", "unblock"}:
            result = scope.change_block(args.platform, args.chat, args.command == "block", args.purpose)
        else:
            result = scope.search(args.platform, args.chat, args.purpose, args.start, args.end, args.keyword, args.scan_limit, args.result_limit, args.attachment_kind)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except (BridgeError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
