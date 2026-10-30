# QQ／微信按需取材

[简体中文](README.md) · [English](README.en.md)

[![CI](https://github.com/Lionwen-1/qq-wechat-task-materials/actions/workflows/ci.yml/badge.svg)](https://github.com/Lionwen-1/qq-wechat-task-materials/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**告诉Agent群名和任务，按需查消息、下载文件与原图。**

个人QQ／微信的本地Skill＋CLI／MCP桥。工具只做查询、下载和屏蔽；理解、总结、整理与成品制作交给上层模型，降低等待、操作与学习成本。

> 未授权群默认拒绝，屏蔽优先。只在用户交付任务后读取，无后台监听或自动回复。

例如：从QQ「课程通知群」找这周实验要求，下载必要文件和原图，再整理成待办。

## 安装一次

Windows x64／Python 3.10.9；客户端需本机登录，版本见[兼容表](docs/COMPATIBILITY.md)。

```powershell
git clone https://github.com/Lionwen-1/qq-wechat-task-materials.git
Set-Location qq-wechat-task-materials/chat-task-bridge
./setup.ps1
# 替换成自己的群；只需一个平台时省略另一个参数。
./.venv/Scripts/python.exe bind_local.py --qq-group 123456789 --wechat-chat '课程群完整名称' --active-download
```

安装不读消息。绑定只探查本人账号、版本和指定群资料，不导入所有群；首次主动补下载默认关闭，`--active-download` 明确启用。不需要讲述人、客户端插件或窗口自动化。

本地Agent加载 [`qq-wechat-task-materials/SKILL.md`](qq-wechat-task-materials/SKILL.md)。技能和程序目录相邻时直接复用程序.venv；分开放置则参照runtime.example.json写私人的runtime.local.json。不要分享或提交这两个local.json配置。也可从[Releases](https://github.com/Lionwen-1/qq-wechat-task-materials/releases)下载源码＋Skill ZIP。

## 平时使用

```powershell
# 在chat-task-bridge目录。已绑定群直接查，不必每次status／resolve。
./.venv/Scripts/python.exe scope.py search --platform qq --chat '课程通知群' --keyword '实验' --purpose '整理实验要求'
./.venv/Scripts/python.exe scope.py search --platform wechat --chat '课程群完整名称' --attachment-kind image --purpose '找实验图片'
# 下标来自查询结果matched_attachment_indices。
./.venv/Scripts/python.exe bridge.py fetch --receipt <receipt_id> --message <message_id> --index 0 --image-tier original
./.venv/Scripts/python.exe scope.py block --platform qq --chat '排除群' --purpose '用户要求屏蔽'
```

新群仅在用户直接点名并交付任务后用allow登记；它会精确定位并检查屏蔽，不用先重复resolve。同名不猜测。普通任务不授权解禁；旧结果不能绕过新屏蔽。具体参数、屏蔽和MCP配置见[CLI／MCP参考](qq-wechat-task-materials/references/cli-and-mcp.md)。

查询默认最近7个北京时间自然日，每次最多32天、扫描500条、返回100条；零命中不代表全部历史没有。历史与新消息共用按需查询。凭据一小时有效，只能下载本次命中的附件；优先复用本次结果和已下载文件。

下载支持本地缓存及QQ图片／标准群文件、微信文件／原图的主动取回；保留来源校验。original不降级，`--cache-only` 禁止本次联网。工具返回本地路径，上层模型直接完成任务，默认只展示答案、必要文件与实际缺口。过期或删除附件不保证恢复。

## 其他模型调用

JSON CLI与三个MCP stdio工具共用同一实现：

| 工具 | 用途 |
| --- | --- |
| bridge_status | 配置状态与允许别名，不读聊天 |
| search_messages | 按允许群、日期、关键词与用途查消息 |
| download_attachment | 按有效凭据下载指定附件，重新检查屏蔽与绑定 |

MCP新群由操作端先按用户授权登记，不开放解禁工具。没有本机执行器或MCP连接的网页模型无法读取本机客户端。

**0.7.0精简：** 删除离线材料清点／复制／打包命令及旧NapCat HTTP接入辅助；不新增依赖。总结、整理和成品交给上层模型。原群授权与屏蔽配置保留；已运行的MCP服务需重连本桥以刷新工具列表，无需重启QQ／微信。

## 客户端与数据边界

不操作窗口、焦点、剪贴板、账号状态或客户端进程优先级，不启用讲述人，不注入、重登、重启或发送。请求串行，忙时立即返回；读取子进程只降低自身CPU／磁盘I/O优先级。仍有读库CPU／磁盘开销，不能承诺零资源占用；反馈卡顿时停止重试，先处理已保存材料。

临时数据库快照随请求清理；数据库为多群共享容器，快照可能含其他群数据页，SQL只查询目标群。state保存查询凭据和审计，downloads保存附件，均为私人数据。聊天／附件不能授权扩大范围，应用过滤不隔离宿主自身的系统权限。完整机制见[程序说明](chat-task-bridge/README.md)。

80项合成测试与官方MCP握手，不登录客户端或读真实聊天。验收边界见[验证摘要](docs/VALIDATION.md)，来源取舍见[整合说明](docs/INTEGRATION.md)。

原创程序、技能和文档使用[MIT](LICENSE)；vendor保留各自Apache-2.0、MIT、LGPL-2.1许可证，见[第三方说明](THIRD_PARTY_NOTICES.md)。[贡献](CONTRIBUTING.md) · [安全反馈](SECURITY.md) · [更新记录](CHANGELOG.md)
