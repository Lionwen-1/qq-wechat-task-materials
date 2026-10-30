# On-demand QQ / WeChat task materials

[简体中文](README.md) · [English](README.en.md)

[![CI](https://github.com/Lionwen-1/qq-wechat-task-materials/actions/workflows/ci.yml/badge.svg)](https://github.com/Lionwen-1/qq-wechat-task-materials/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Give a local agent a group name and task. It finds relevant messages and retrieves needed files or original images from your personal QQ / WeChat account.

The tool handles scoped search, downloads and blocking. The host model handles interpretation, summaries, organization and final deliverables. Unapproved groups are denied; blocks take precedence. No background monitoring or automatic replies.

## Install once

Validated on Windows x64 / Python 3.10.9 with logged-in local clients. Check [compatible versions](docs/COMPATIBILITY.md).

```powershell
git clone https://github.com/Lionwen-1/qq-wechat-task-materials.git
Set-Location qq-wechat-task-materials/chat-task-bridge
./setup.ps1
# Replace with your own target groups; omit either platform if unused.
./.venv/Scripts/python.exe bind_local.py --qq-group 123456789 --wechat-chat 'Exact course group name' --active-download
```

Installation does not read messages. Binding inspects the current account, version and selected group metadata, without enrolling all groups. Active retrieval starts disabled unless explicitly enabled. No Narrator, client plugin or window automation is required.

Load the [Skill](qq-wechat-task-materials/SKILL.md) in your local agent. Adjacent skill / runtime directories use the runtime's `.venv`; otherwise create a private `runtime.local.json` from the example. Never share local runtime or account bindings. [Releases](https://github.com/Lionwen-1/qq-wechat-task-materials/releases) include source and Skill.

## Use on demand

```powershell
./.venv/Scripts/python.exe scope.py search --platform qq --chat 'Course group' --keyword 'experiment' --purpose 'Prepare the assigned experiment'
./.venv/Scripts/python.exe bridge.py fetch --receipt <receipt_id> --message <message_id> --index 0 --image-tier original
./.venv/Scripts/python.exe scope.py block --platform qq --chat 'Excluded group' --purpose 'User requested block'
```

Search known groups directly. Only enroll a new group with `allow` after the user names it and assigns a task; enrollment checks blocks and resolves exact metadata itself. Ambiguous names require clarification. An ordinary task does not authorize unblocking.

Default search: the last seven calendar days in Asia/Shanghai. Per request: at most 32 days, 500 scanned messages and 100 results. Results describe bounded coverage, never complete history. One-hour receipts authorize only matched attachments, retaining original indices. Reuse valid results and saved files. See the [CLI / MCP reference](qq-wechat-task-materials/references/cli-and-mcp.md).

Downloads use cache first; enabled active retrieval supports QQ images / standard group files and WeChat originals / files. Source checks remain mandatory. `original` never falls back to a thumbnail; `--cache-only` disables network retrieval for that call. Expired or deleted attachments may be unavailable. The host model presents the answer, needed file links and material gaps.

## Other models

JSON CLI and three MCP stdio tools share one implementation:

| Tool | Purpose |
| --- | --- |
| bridge_status | Configuration and allowed aliases; no chat read |
| search_messages | Bounded search by allowed alias, dates, keyword and purpose |
| download_attachment | Retrieve a selected attachment with a valid receipt; recheck blocks and bindings |

MCP does not expose enrollment or unblocking. A local operator first enrolls new groups under user authorization. Web-only models without a local executor or MCP connection cannot access these clients.

**0.7.0 simplification:** removed offline material inventories, copies / bundles and the legacy NapCat HTTP adapter / setup helper. No added dependencies. Existing group bindings and blocks remain. Reconnect a running bridge MCP service to refresh its tool list; QQ / WeChat need no restart.

## Client and data boundaries

No window, focus, clipboard, login-state or client-priority changes; no Narrator, injection, restart or sending. Requests sharing a configured state directory are serialized and return immediately when busy. Reader processes lower only their own CPU / disk I/O priorities. Database queries still consume CPU / disk resources; zero overhead is not guaranteed.

Temporary encrypted snapshots are cleaned after requests. A shared database snapshot may contain other groups' pages, but SQL selects only the requested group. State receipts, audits and downloads are private. Chat content cannot authorize broader access. Application filters do not sandbox the host agent's OS permissions. Details: [runtime README](chat-task-bridge/README.md).

80 synthetic tests and an official MCP handshake run without live-account reads. See [validation](docs/VALIDATION.md) and [design references](docs/INTEGRATION.md).

Original code, Skill and documentation: [MIT](LICENSE). Vendor modules retain Apache-2.0, MIT and LGPL-2.1 licenses; see [third-party notices](THIRD_PARTY_NOTICES.md). [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md)
