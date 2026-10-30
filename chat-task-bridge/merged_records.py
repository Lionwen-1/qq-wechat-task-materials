"""Bounded, credential-free views of merged records. No client or network access."""
import json
import re
from xml.etree import ElementTree as ET

MAX_XML = 2 * 1024**2
MAX_ITEMS = 200
MAX_TEXT = 128 * 1024
MAX_DEPTH = 4


def xml(text):
    body = re.sub(r"^[A-Za-z0-9_@.-]+:\r?\n", "", text, count=1)
    if len(body) > MAX_XML or re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", body, re.I):
        return None
    try:
        return ET.fromstring(body)
    except (ET.ParseError, RecursionError):
        return None


def view(title=""):
    return {"title": title[:1000], "messages": [], "complete": True, "limitations": [],
            "sender_identity": "as_reported_in_forward", "attachments_downloadable": False}


def limit(result, reason):
    result["complete"] = False
    if reason not in result["limitations"]:
        result["limitations"].append(reason)


def append(result, sender, stamp, kind, text, depth=0):
    used = sum(len(m["text"]) for m in result["messages"])
    if len(result["messages"]) >= MAX_ITEMS or used >= MAX_TEXT:
        limit(result, "content_limit")
        return False
    remaining = MAX_TEXT - used
    if len(text) > remaining:
        limit(result, "content_limit")
    result["messages"].append({"sender": str(sender or "unknown")[:200], "time": str(stamp or "")[:100],
                               "kind": kind, "text": text[:remaining], "depth": depth})
    return True


def render(result):
    return "[合并聊天记录] " + result["title"] + "\n" + "\n".join(
        (m["sender"] + (" " + m["time"] if m["time"] else "") + ": " + m["text"]) for m in result["messages"])


def wechat_record(text):
    root = xml(text)
    app = root.find(".//appmsg") if root is not None else None
    if app is None or app.findtext("type") != "19":
        return None
    result = view(app.findtext("title") or "")
    record = app.find("recorditem")
    if record is None:
        limit(result, "record_body_missing")
        return result

    def walk(container, depth):
        if depth > MAX_DEPTH:
            limit(result, "nesting_limit")
            return
        if container.find("datalist") is None:
            parsed = xml(container.text or "")
            if parsed is None:
                # Some clients embed the element instead of CDATA.
                parsed = container.find("recordinfo")
                if parsed is None:
                    parsed = container.find("recordxml")
            container = parsed
        if container is None:
            limit(result, "record_body_invalid")
            return
        items = container.findall("./datalist/dataitem")
        datalist = container.find("datalist")
        declared = datalist.get("count") if datalist is not None else None
        if declared and declared.isdigit() and int(declared) != len(items):
            limit(result, "declared_count_mismatch")
        if not items:
            limit(result, "record_body_missing")
        for item in items:
            typ = item.get("datatype") or item.findtext("datatype") or ""
            sender = item.findtext("sourcename") or item.findtext("dataitemsource/sourcename") or "unknown"
            stamp = item.findtext("sourcetime") or item.findtext("dataitemsource/sourcetime") or ""
            kind = {"1": "text", "2": "image", "3": "voice", "4": "video", "5": "link", "8": "file", "17": "forward"}.get(typ, "unsupported")
            if kind == "text":
                content = item.findtext("datadesc") or item.findtext("datatitle") or ""
            else:
                label = {"image": "图片", "voice": "语音", "video": "视频", "file": "文件", "link": "链接", "forward": "合并聊天记录"}.get(kind, "未支持的消息")
                content = "[" + label + "] " + (item.findtext("datatitle") or "")
            if not append(result, sender, stamp, kind, content, depth):
                break
            if kind == "unsupported":
                limit(result, "unsupported_message_type")
            if kind == "forward":
                nested = item.find("recordxml")
                if nested is None:
                    limit(result, "nested_record_missing")
                else:
                    walk(nested, depth + 1)
    walk(record, 0)
    return result


def qq_card(segments):
    """Recognize actual forwards, not every QQ app card. Keep resource IDs private."""
    for segment in segments:
        legacy = segment.get("legacy_fwd_xml")
        if legacy:
            root = xml(legacy)
            if root is not None and root.get("m_resid"):
                preview = [e.text or "" for e in root.findall("./item/title")]
                return {"title": "聊天记录", "preview": "\n".join(preview)[:4000],
                        "_resid": root.get("m_resid")}
        meta = segment.get("fwd_meta")
        if not meta or len(meta) > MAX_XML:
            continue
        try:
            data = json.loads(meta)
        except (ValueError, RecursionError):
            continue
        if not isinstance(data, dict) or data.get("app") != "com.tencent.multimsg":
            continue
        meta = data.get("meta")
        detail = meta.get("detail") if isinstance(meta, dict) else None
        if not isinstance(detail, dict):
            continue
        news = detail.get("news", [])
        preview = "\n".join(n.get("text", "") for n in news[:20] if isinstance(n, dict) and isinstance(n.get("text"), str)) if isinstance(news, list) else ""
        title = detail.get("summary") or detail.get("title") or "聊天记录"
        return {"title": str(title)[:1000], "preview": preview[:4000], "_resid": detail.get("resid") or segment.get("fwd_token")}
    return None
