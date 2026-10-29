# Compatibility / 兼容范围

Last checked: 2026-10-30. Windows x64, CPython 3.10.9; pinned dependencies are included as a lock file.

| Client | Tested version | Verified scope |
| --- | --- | --- |
| WeChat / 微信 | 4.1.15.56, 4.2.0.9 | Selected personal-account groups; message lookup; cached files; active original-image and standard file download |
| QQ launcher | 9.9.35.52892 | Bound local personal-account database identity |
| QQ actual loaded kernel | 9.9.36-53644 | Group lookup, scoped messages, images and standard busId=102 group files; active file path also checks module hashes |

The QQ launcher version can differ from the loaded kernel. Do not infer runtime compatibility from the launcher's file version alone.

需要本机已登录客户端。新消息通过后续按需查询读取，不后台监听。QQ 私聊、特殊群文件、超出配置上限的附件及其他客户端版本没有当前实测承诺。过期或删除附件不保证恢复。

Client updates fail closed when bindings differ. Revalidate the same account, exact target metadata, database parsing and previously authorized sample downloads before changing a binding. For a new WeChat protocol version, inspect the running client's actual protocol parameter rather than guessing a conversion from its display version. Do not clear blocks or import all groups during adaptation.

首次绑定的主动下载默认关闭，只有 `--active-download` 明确启用后才补取；`--cache-only` 或 MCP `fetch_if_missing=false` 可逐次禁止联网。
