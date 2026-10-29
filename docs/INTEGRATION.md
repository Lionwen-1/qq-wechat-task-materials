# Lightweight integration / 轻量整合

Reviewed 2026-10-30. This release borrows design ideas; it does not install or copy new source from these projects.

| Reference | Integrated here | Boundary |
| --- | --- | --- |
| [wxq](https://github.com/vpcoderli/wxq) | Shared core behavior for CLI / MCP; attachment-kind filtering | Existing bounded group query remains authoritative; no all-account search or persistent key / database cache added |
| [WeFlow CLI MCP contract](https://github.com/zhuobichen/weflow-cli/blob/master/docs/MCP.md) | Versioned message scope / coverage; portable media links and explicit unavailable-material reporting | Own schemas and independently written implementation; no AI backend, knowledge base, daemon or remote model calls |
| [im-mcp](https://github.com/stkoecn/im-mcp) | Material / image inventory organized around the current task | Uses only this receipt's verified downloads; no initial full-database index, background sync or key-file extraction tool |

CLI and MCP return `chat-task-messages/v1`; existing fields remain, with explicit scope, returned time bounds, `may_have_more` and preserved attachment indices. Material preparation returns `chat-task-materials/v1`, reads only an unexpired scoped receipt and its saved files, and optionally creates a portable Markdown / JSON folder. It does not download missing assets. Block / binding changes revoke all three stages: reading, downloading and preparing materials.

读取与整理在同一配置下串行；忙时返回，不常驻排队。读取子进程无窗口、先校验自身低 CPU／very-low I/O 优先级，失败则不访问客户端。不改变 QQ／微信的焦点、剪贴板、进程优先级、账号状态，不注入、重登、重启或发送。仍有 CPU／磁盘开销，不能以此承诺“绝对零影响”；用户反馈卡顿时应停止重试并优先处理已保存材料。

The existing pinned dependencies and vendored modules are unchanged. No NapCat / alternate client instance, UI automation, LLDB / injection, monitoring service, cross-task database cache or full-text index is added. Custom-license source from wechat-use and the broader automation stacks were not imported. Attribution and original vendor licenses remain in [third-party notices](../THIRD_PARTY_NOTICES.md).

See the [skill material reference](../qq-wechat-task-materials/references/materials.md) for limits, original indices, local paths, receipt expiry and precise interpretation of coverage. The new functionality is verified with synthetic task materials; no new real-account message reads are used as acceptance tests.
