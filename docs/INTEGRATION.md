# Design references / 设计取舍

2026-10-30. These projects informed the 0.6.0 review; no new third-party source or dependency was imported. Version 0.7.0 retains only ideas that reduce the cost of the current task:

| Reference | Retained idea |
| --- | --- |
| [wxq](https://github.com/vpcoderli/wxq) | Shared CLI / MCP core and attachment-kind filtering |
| [WeFlow CLI MCP contract](https://github.com/zhuobichen/weflow-cli/blob/master/docs/MCP.md) | Explicit bounded message scope and coverage |
| [im-mcp](https://github.com/stkoecn/im-mcp) | Fetch only materials relevant to the requested task |

0.7.0 removes the offline inventory / portable-bundle layer and the unused NapCat HTTP route. Search, downloads and group blocking remain in the tool; interpretation, summaries, organization and deliverables belong to the host model. The MCP tools share the CLI implementation. No background sync, whole-account index, persistent key cache or AI backend is added.

保留低优先级、串行读取及账号／版本／来源校验。不操作QQ／微信窗口、焦点、剪贴板、登录状态或客户端优先级。仍有数据库读取开销；复用有效查询和已下载文件，忙时不自动重试。

Original vendor licenses and pinned sources remain in [third-party notices](../THIRD_PARTY_NOTICES.md). Current parameters and integration are in the [CLI / MCP reference](../qq-wechat-task-materials/references/cli-and-mcp.md).

0.8.0 keeps that scope while adding standard-library TLS connection reuse and Windows privacy controls via the existing pywin32 dependency. No new package, daemon, full-account index or AI backend is introduced; Pillow and the Python runtime are upgraded for security.

## Merged records (0.9.0)

Use read_merged_record(receipt_id, message_id, fetch_if_missing=true), or bridge.py read-record --receipt ... --message .... Reuse WeChat merged_record.state=inline bodies already in search results; QQ preview_only requires a per-record read. QQ keyword search covers previews, not remote bodies. Check complete and limitations, including missing bodies, unsupported/nested remote messages and size/item/depth limits. complete describes the parsed message list, not media/OCR contents. For files/images, use the returned derived receipt_id, inner message id and matched_attachment_indices with download_attachment. The query receipt stays unchanged; the new encrypted receipt inherits its expiry and policy. Normal message attachment downloads are unchanged. Forwarded identities are self-reported. No arbitrary resource IDs/URLs, original-group lookup, or automatic recursive network calls.
