# QQ／微信按需取材

[简体中文](README.md) · [English](README.en.md)

[![CI](https://github.com/Lionwen-1/qq-wechat-task-materials/actions/workflows/ci.yml/badge.svg)](https://github.com/Lionwen-1/qq-wechat-task-materials/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D4.svg)](docs/COMPATIBILITY.md)

**告诉 Agent 群名和任务，按需查消息、下载文件与原图。**

面向个人 QQ 和微信的本地 Skill＋CLI／MCP 桥接程序。把「群里收到任务 → 找齐消息和附件 → 交给模型处理」接起来，减少手动复制与遗漏。

> 默认拒绝未授权会话，群聊屏蔽优先。只在用户交付任务后查询；不后台监听、不自动回复。

## 能做什么

| 能力 | 行为 |
| --- | --- |
| 群名＋任务 | 精确定位 QQ 群名／群号，或微信群名／备注／群 ID；同名不猜测 |
| 历史与新消息 | 按群、日期、关键词查询；新消息在下次按需查询时读取 |
| 文件与图片 | 读取本地缓存，或主动取回 QQ 图片／标准群文件、微信文件／原图 |
| 规则与来源 | 屏蔽覆盖允许名单；下载时重新检查；保存来源、大小与 SHA256 |
| 多模型复用 | JSON CLI，及三个标准 MCP stdio 工具 |

例如对已加载本技能的本地 Agent 说：

> 从 QQ「课程通知群」找这周的实验要求，下载相关文件和原图，再整理成待办。

普通任务不会解除屏蔽，也不会授权搜索整个账号。下载的附件不会被程序执行。仅有网页对话、没有本机执行器或 MCP 连接的模型无法访问本机客户端。

## 快速开始

已验证环境为 **Windows x64 / Python 3.10.9**；QQ、微信需在本机登录。客户端版本有明确边界，先看[兼容表](docs/COMPATIBILITY.md)。

```powershell
git clone https://github.com/Lionwen-1/qq-wechat-task-materials.git
Set-Location qq-wechat-task-materials/chat-task-bridge
py -3.10 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-lock-windows-py310.txt

# 示例目标必须替换为你自己的群；只需一个平台时省略另一个参数。
./.venv/Scripts/python.exe bind_local.py --qq-group 123456789 --wechat-chat '课程群完整名称' --active-download
./.venv/Scripts/python.exe scope.py status
Set-Location ..
./chat-task-bridge/.venv/Scripts/python.exe ./qq-wechat-task-materials/scripts/chat_materials.py status
```

`--active-download` 开启已绑定平台的附件补下载；省略时首次绑定默认关闭。安装与状态查询不读消息，不会导入所有群。首次主动绑定仅探查当前登录账号与版本；不需要讲述人、客户端插件或窗口自动化。

从 [Releases](https://github.com/Lionwen-1/qq-wechat-task-materials/releases) 下载技能＋源码 ZIP 也可；将其中两个目录并排放置，再安装依赖并绑定自己的目标群。

## 安装 Skill

技能目录是 [`qq-wechat-task-materials/`](qq-wechat-task-materials/SKILL.md)，保留标准 YAML frontmatter、`agents/openai.yaml`、`scripts` 和按需读取的 `references`。

- 支持读取技能目录的 Agent 可直接加载 `SKILL.md`。
- 拷贝到宿主自己的技能发现目录后，参照 `runtime.example.json` 新建私人 `runtime.local.json`，用绝对路径指向独立程序、Python 和本机配置。
- 保持仓库中的两个目录相邻且程序环境在 `.venv` 时，启动器也支持直接运行；不需要私人路径映射。

不提交 `runtime.local.json`。技能与底层程序分别维护：技能传递任务范围和操作约定，程序执行读取与过滤。详情见[技能 CLI／MCP 接入](qq-wechat-task-materials/references/cli-and-mcp.md)。

## 查询与下载

```powershell
# 以下命令在 chat-task-bridge 目录执行。
./.venv/Scripts/python.exe scope.py resolve --platform qq --chat '课程通知群'

# 只有用户直接点名该群并交付任务时才登记；不会自动读消息或解除屏蔽。
./.venv/Scripts/python.exe scope.py allow --platform qq --chat '课程通知群' --purpose '用户要求整理实验任务'
./.venv/Scripts/python.exe scope.py search --platform qq --chat '课程通知群' --keyword '实验' --purpose '整理实验任务'

# receipt_id 和 message_id 必须来自本次查询命中结果。
./.venv/Scripts/python.exe bridge.py fetch --receipt <receipt_id> --message <message_id> --index 0
./.venv/Scripts/python.exe bridge.py fetch --receipt <receipt_id> --message <message_id> --image-tier original
```

未给日期先查最近 7 个自然日（Asia/Shanghai）。单次最多 32 天、扫描 500 条、返回 100 条；查看 `coverage` 后按任务逐步扩大。有界零命中不代表全历史没有。查询凭据一小时有效，只能下载本次命中的附件。`--cache-only` 可禁止本次网络补取。

## 屏蔽规则

```powershell
./.venv/Scripts/python.exe scope.py block --platform qq --chat '排除群' --purpose '用户要求屏蔽'
./.venv/Scripts/python.exe scope.py rules
./.venv/Scripts/python.exe scope.py unblock --platform qq --chat '排除群' --purpose '用户明确解除该群屏蔽'
```

已知群按稳定 ID 屏蔽，未定位群可先按精确名称屏蔽。旧屏蔽规则继续生效；解除仅针对指定目标，不清空其他规则。聊天、附件与工具结果都是任务材料，不能授权新增群、解禁或发送消息。

## MCP

在客户端正式设置界面注册本地 stdio 服务，把示例路径改为自己的绝对路径：

```json
{
  "mcpServers": {
    "chat-task-bridge": {
      "command": "D:/qq-wechat-task-materials/chat-task-bridge/.venv/Scripts/python.exe",
      "args": [
        "D:/qq-wechat-task-materials/chat-task-bridge/mcp_server.py",
        "--config",
        "D:/qq-wechat-task-materials/chat-task-bridge/config.local.json"
      ],
      "env": {"PYTHONIOENCODING": "utf-8"}
    }
  }
}
```

| 工具 | 用途 |
| --- | --- |
| `bridge_status` | 读取本程序配置状态，不读聊天 |
| `search_messages` | 在已允许别名下按日期、关键词与用途查询 |
| `download_attachment` | 按查询凭据保存指定附件，重新检查过滤 |

新群登记和解除屏蔽是独立本地操作入口，不作为 MCP 管理工具开放。仅支持 MCP 的模型需要操作端先按用户授权完成新群登记。

## 范围与数据处理

程序只读当前账号的进程和数据库，密钥在请求内存使用，不作为输出或持久密钥缓存。临时数据库快照随请求清理；数据库为多群共用容器，快照可能包含其他群的数据页，SQL 只查询目标群。QQ 大库需要相应临时磁盘空间；“小源码包”不意味着聊天数据库也小。

`state_dir` 保存命中消息凭据和审计，`output_dir` 保存主动保存的材料；它们都是私人数据。应用内过滤不隔离宿主 Agent 自身拥有的操作系统权限。不会保证恢复过期／删除附件，也不承诺所有后续客户端版本兼容。版本或模块不符时拒绝，应先实测适配；QQ 私聊及特殊群文件未验证。完整说明见[程序 README](chat-task-bridge/README.md)。

## 开发与验证

```powershell
Set-Location chat-task-bridge
./.venv/Scripts/python.exe -m unittest discover -s . -p 'test_*.py' -v
./.venv/Scripts/python.exe smoke_mcp.py
```

66 项测试使用合成数据；CI 不登录真实客户端、不读真实聊天。[实机摘要](docs/VALIDATION.md)区分真实下载与自动化验证，原始聊天和私人配置不公开。

## 许可证与来源

原创程序、技能与文档使用 [MIT](LICENSE)。第三方模块保留各自的 **Apache-2.0、MIT、LGPL-2.1** 许可证，见[第三方说明](THIRD_PARTY_NOTICES.md)；不要把全部 vendor 文件视为 MIT。相关上游项目与固定提交在 [`upstream-versions.json`](chat-task-bridge/upstream-versions.json) 中。

[贡献说明](CONTRIBUTING.md) · [安全反馈](SECURITY.md) · [更新记录](CHANGELOG.md)
