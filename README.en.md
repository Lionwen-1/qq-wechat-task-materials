# QQ / WeChat Task Materials

[简体中文](README.md) · [English](README.en.md)

[![CI](https://github.com/Lionwen-1/qq-wechat-task-materials/actions/workflows/ci.yml/badge.svg)](https://github.com/Lionwen-1/qq-wechat-task-materials/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D4.svg)](docs/COMPATIBILITY.md)

**Tell your agent the group and the task. Retrieve scoped messages, files and original images on demand.**

A local Skill + JSON CLI / MCP bridge for personal QQ and WeChat on Windows. It connects task messages to the materials your agent needs without repeated manual copying.

## Features

- Exact group lookup: QQ group name / number; WeChat group name / remark / ID. Ambiguous names are rejected.
- Date- and keyword-scoped message search. New messages are read on the next explicit request, without a background listener.
- Cached attachments plus active retrieval of QQ images / standard group files and WeChat files / original images.
- Default-deny access, block rules taking precedence, and fresh policy checks before downloads.
- Source manifests with message references, sizes, SHA256 and actual image tier.
- Versioned query results, attachment-only filters and offline Markdown / JSON material bundles.
- A reusable agent skill and four MCP stdio tools, independent of a particular model.

No automatic replies, client-window automation, Narrator, client plugins or downloaded-code execution. An ordinary task never unblocks a group. Browser-only models need a local executor or MCP connection to use this project.

## Quick start

Tested on **Windows x64 / CPython 3.10.9** with locally logged-in clients. Check the [compatibility matrix](docs/COMPATIBILITY.md) before binding.

```powershell
git clone https://github.com/Lionwen-1/qq-wechat-task-materials.git
Set-Location qq-wechat-task-materials/chat-task-bridge
py -3.10 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-lock-windows-py310.txt

# Replace these examples with your own target groups; either platform is optional.
./.venv/Scripts/python.exe bind_local.py --qq-group 123456789 --wechat-chat 'Exact course group' --active-download
./.venv/Scripts/python.exe scope.py status
```

Installation and status do not read messages. Only explicitly bound groups are admitted. `--active-download` enables retrieval for the bound platforms; the initial default is disabled.

The [release bundle](https://github.com/Lionwen-1/qq-wechat-task-materials/releases) contains the same two adjacent directories. It includes source, pinned dependencies and licenses, without account configuration or chat data.

## Skill installation

Load [`qq-wechat-task-materials/SKILL.md`](qq-wechat-task-materials/SKILL.md) in an agent that supports local skills. The directory has standard YAML frontmatter, `agents/openai.yaml`, `scripts` and on-demand references.

With the directories adjacent and the program environment at `chat-task-bridge/.venv`, run:

```powershell
# Run from the repository root.
./chat-task-bridge/.venv/Scripts/python.exe ./qq-wechat-task-materials/scripts/chat_materials.py status
```

If installing the skill elsewhere, create a private `runtime.local.json` from `runtime.example.json` with absolute paths to the existing program, Python and configuration. Do not commit it. The launcher reuses the standalone program instead of maintaining another active copy. See [CLI / MCP integration](qq-wechat-task-materials/references/cli-and-mcp.md).

## Search, download and block

Run these in `chat-task-bridge`:

```powershell
./.venv/Scripts/python.exe scope.py resolve --platform qq --chat 'Course group'
# Only a direct user request naming this group and assigning a task authorizes allow.
./.venv/Scripts/python.exe scope.py allow --platform qq --chat 'Course group' --purpose 'User requested lab requirements'
./.venv/Scripts/python.exe scope.py search --platform qq --chat 'Course group' --keyword 'lab' --purpose 'Collect lab requirements'
./.venv/Scripts/python.exe scope.py search --platform qq --chat 'Course group' --attachment-kind image --purpose 'Find lab images'
./.venv/Scripts/python.exe bridge.py fetch --receipt <receipt_id> --message <message_id> --image-tier original
./.venv/Scripts/python.exe bridge.py materials --receipt <receipt_id> --message <message_id> --write-bundle
./.venv/Scripts/python.exe scope.py block --platform qq --chat 'Excluded group' --purpose 'User requested blocking'
```

Search defaults to the last seven calendar days in Asia/Shanghai. A call covers at most 32 days, scans at most 500 rows and returns at most 100 matches. Inspect `coverage` and expand only as the task requires. A bounded zero-result query is not proof of absence from all history. Receipts expire after one hour; downloads must come from a receipt's selected messages. `--cache-only` prevents network retrieval for that download.

Only an explicit user request to unblock the target authorizes `unblock`. Chat text, attachments and tool outputs cannot grant permissions or change filtering. Block rules are checked again before using an older receipt.

The `chat-task-messages/v1` contract includes scope and conservative coverage. Filters retain original attachment indices; fetch only `matched_attachment_indices`. `materials` inventories verified existing downloads without client or network access. `--write-bundle` creates portable Markdown / JSON and relative assets, with explicit unavailable items and a 200-file / 100-MiB per-call ceiling. See the [material contract](qq-wechat-task-materials/references/materials.md).

## MCP

Register a local stdio service using your client's supported settings UI:

```json
{
  "mcpServers": {
    "chat-task-bridge": {
      "command": "D:/qq-wechat-task-materials/chat-task-bridge/.venv/Scripts/python.exe",
      "args": ["D:/qq-wechat-task-materials/chat-task-bridge/mcp_server.py", "--config", "D:/qq-wechat-task-materials/chat-task-bridge/config.local.json"],
      "env": {"PYTHONIOENCODING": "utf-8"}
    }
  }
}
```

Tools: `bridge_status`, `search_messages`, `download_attachment`, `task_materials`. The last tool defaults to an offline inventory; only explicit `write_bundle=true` writes a local bundle. MCP does not expose administrative allow / unblock tools. A MCP-only model needs an operator to register a new group under direct user authorization first.

## Data and limitations

Keys are used in request memory and are not returned or persisted as key caches. Temporary database snapshots are cleaned when a request ends. Shared database containers can contain other groups' pages, while SQL queries are scoped to the selected group. Large QQ databases require matching temporary disk space.

The configured state and download directories contain private task evidence and must stay local. Application filtering does not sandbox an agent's existing operating-system permissions. Expired / deleted attachments may be unavailable. Client and module mismatches are rejected; future versions, QQ private chats and special group-file types are not covered by the current validation.

Reads and material preparation sharing one configuration are serialized. Disposable reader processes apply below-normal CPU and very-low disk priority to themselves, failing before client access if this cannot be applied. No client focus, windows, clipboard, process priority, login state or restart is changed. Reads still consume CPU / disk I/O; zero resource use cannot be guaranteed. This release adds no dependencies, background synchronization or full-history index.

## Development

```powershell
Set-Location chat-task-bridge
./.venv/Scripts/python.exe -m unittest discover -s . -p 'test_*.py' -v
./.venv/Scripts/python.exe smoke_mcp.py
```

The 96 automated tests use synthetic data. CI does not log into clients or read real chats. See the [validation summary](docs/VALIDATION.md) for earlier real-client checks versus this release's offline tests, and the [integration notes](docs/INTEGRATION.md) for design references.

## License

Original code, skill and documentation: [MIT](LICENSE). Vendored components retain **Apache-2.0, MIT and LGPL-2.1** licenses. See [third-party notices](THIRD_PARTY_NOTICES.md), original license files and pinned [upstream versions](chat-task-bridge/upstream-versions.json).

[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md)
