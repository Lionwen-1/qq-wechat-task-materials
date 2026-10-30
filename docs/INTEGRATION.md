# Design references / 设计取舍

2026-10-30. These projects informed the 0.6.0 review; no new third-party source or dependency was imported. Version 0.7.0 retains only ideas that reduce the cost of the current task:

| Reference | Retained idea |
| --- | --- |
| [wxq](https://github.com/vpcoderli/wxq) | Shared CLI / MCP core and attachment-kind filtering |
| [WeFlow CLI MCP contract](https://github.com/zhuobichen/weflow-cli/blob/master/docs/MCP.md) | Explicit bounded message scope and coverage |
| [im-mcp](https://github.com/stkoecn/im-mcp) | Fetch only materials relevant to the requested task |

0.7.0 removes the offline inventory / portable-bundle layer and the unused NapCat HTTP route. Search, downloads and group blocking remain in the tool; interpretation, summaries, organization and deliverables belong to the host model. The three MCP tools share the CLI implementation. No background sync, whole-account index, persistent key cache or AI backend is added.

保留低优先级、串行读取及账号／版本／来源校验。不操作QQ／微信窗口、焦点、剪贴板、登录状态或客户端优先级。仍有数据库读取开销；复用有效查询和已下载文件，忙时不自动重试。

Original vendor licenses and pinned sources remain in [third-party notices](../THIRD_PARTY_NOTICES.md). Current parameters and integration are in the [CLI / MCP reference](../qq-wechat-task-materials/references/cli-and-mcp.md).
