# 查询结果与离线材料整理

## 统一查询契约

`search` / MCP `search_messages` 返回 `schema: chat-task-messages/v1`，保留原有 receipt、messages、coverage 字段；CLI 与 MCP 共用同一核心逻辑。

`scope` 给出平台、会话、日期、Asia/Shanghai、关键词和附件筛选。`coverage` 给出扫描条数、返回条数、最早观察时间、返回时间边界、截断及 `may_have_more`；`history_complete` 始终为 false。

`--attachment-kind all|any|image|file` 在当前有界扫描内筛选消息，不扩大原查询、不检索图片内文字。消息可含混合附件，原始下标不重排；仅 `matched_attachment_indices` 中的附件可下载。例如返回 `[1]` 时必须 `--index 1`，不能改成0。

## 先清点，再按需整理

```powershell
python "<本技能目录>/scripts/chat_materials.py" materials --receipt <receipt_id>
python "<本技能目录>/scripts/chat_materials.py" materials --receipt <receipt_id> --message <message_id> --write-bundle
```

第二条可重复 `--message` 选择多条；省略时使用本次查询的命中消息。显式空列表、重复／未命中 ID 拒绝。MCP 对应 `task_materials(receipt_id, message_ids?, write_bundle=false)`。

这两种模式都只读取本程序的一小时凭据和该凭据目录中的已保存材料。不会打开 QQ／微信数据库、扫描客户端进程、联网或补下载。过滤、会话及账号绑定仍重新检查，整理期间新增屏蔽会使未完成输出撤销；旧版没有账号绑定摘要的凭据必须重新查询。

预览返回 `chat-task-materials/v1`、消息、附件状态、实际图片版本及已验证 `local_file_paths`。`ready` 表示现有文件的大小／SHA256 与保存清单一致；另看 `source_digest_verified`，不能据此冒充原图或来源 MD5 已核验。

`write_bundle=true` 生成独立文件夹：

```text
bundle-.../
  materials.md
  materials.json
  assets/...
```

Markdown 中的聊天文字按字面代码块保存，附件只使用本地相对链接，不把聊天中的 HTML 或远端图片当作可执行／自动加载内容。文件名加来源标识，避免同名覆盖；JSON 保留消息 ID、时间、实际媒体版本、哈希和缺失原因，不含原始绝对路径与内部媒体凭据。

只统计选中消息中本次筛选命中的附件。`no_verified_local_copy` 可能是尚未下载、失败或校验不通过，不等于原消息没有附件。上限为500附件、200文件及最多100 MiB（也受本机更小的配置上限限制）；超出部分明确标记，不自动下载或扩大范围。需要补齐时另行选择任务必要附件调用 fetch，再清点。

## 借鉴范围

本轮借鉴 [wxq](https://github.com/vpcoderli/wxq) 的 CLI／MCP 共享服务组织、[weflow-cli](https://github.com/zhuobichen/weflow-cli/blob/master/docs/MCP.md) 的版本化消息／覆盖范围和媒体报告，以及 [im-mcp](https://github.com/stkoecn/im-mcp) 的文件／图片检索入口组织。新增实现使用现有依赖和 Python 标准库，没有复制这些项目源码、增加它们的运行环境、常驻同步或数据库索引。

窗口自动化、LLDB／注入式客户端控制、自动发送、专用登录副本和常驻监听均未集成。只减少本桥自身的并发和优先级，不修改客户端；仍不承诺任何读取任务零 CPU／磁盘开销。
