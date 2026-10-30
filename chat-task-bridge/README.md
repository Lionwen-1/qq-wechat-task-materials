# 聊天取材桥 0.7.0

按任务读取个人QQ／微信指定群消息、下载文件和图片、保留群聊屏蔽。JSON CLI和MCP共用同一实现；理解、总结、整理和成品制作由上层模型完成。

## 安装一次

已验证Windows x64、CPython 3.10.9。QQ启动器9.9.35.52892、实际内核9.9.36-53644；微信4.1.15.56／4.2.0.9。升级后绑定不符会拒绝，不能仅改版本号或哈希绕过。

```powershell
./setup.ps1
# 替换成自己的群；只用一个平台时省略另一个参数。
./.venv/Scripts/python.exe bind_local.py --qq-group 123456789 --wechat-chat '课程群完整名称' --active-download
```

安装不读消息。首次绑定只探查已登录本人账号、版本与指定群资料；不会导入所有群。首次主动下载默认关闭，`--active-download` 明确启用。本程序配置、state和downloads属于私人数据，不分享或提交。

## 按任务调用

```powershell
# 已绑定群直接查；新群先按用户直接授权执行allow，不用重复resolve。
./.venv/Scripts/python.exe scope.py search --platform qq --chat '课程通知群' --keyword '实验' --purpose '整理实验要求'
./.venv/Scripts/python.exe scope.py search --platform wechat --chat '课程群完整名称' --attachment-kind image --purpose '查实验图片'
./.venv/Scripts/python.exe bridge.py fetch --receipt <receipt_id> --message <message_id> --index 0 --image-tier original
./.venv/Scripts/python.exe scope.py block --platform qq --chat '排除群' --purpose '用户要求屏蔽'
```

scope支持status、rules、resolve、allow、block、unblock、search；bridge支持status、search、fetch。只有用户明确要求时解禁指定群。未知群默认拒绝，屏蔽优先于允许，旧查询结果也不能绕过新屏蔽。

search默认最近7个北京时间自然日，可给start/end；单次最多32天、扫描500条、返回100条。统一返回 `chat-task-messages/v1`、scope、coverage和一小时receipt。按需扩大范围，不能把有界零命中当完整历史。attachment-kind为all／any／image／file，原附件下标不重排，fetch只接受matched_attachment_indices中命中的项。账号／群绑定变化或凭据过期需重新查询。

下载优先本地缓存，启用后可主动取回QQ图片／标准群文件、微信原图／文件。默认received取原图或接收版，不用缩略图兜底；original只取原图；thumbnail取预览；best_available可降级并标记。`--cache-only` 禁止本次网络补取。过期／删除附件不保证恢复。

成功下载返回路径、大小、SHA256及source.json，记录来源和图片版本；失败标记FAILED.json。下载前后重新检查账号和屏蔽，重读指定原消息核验来源；不执行附件。没有材料清点、复制或Markdown／JSON打包命令。

## 多模型调用

配套 `qq-wechat-task-materials` Skill可让本地Agent按群名和任务调用CLI；目录相邻时直接复用程序.venv，分开时用私人runtime.local.json映射。没有本机执行器或MCP连接的网页模型无法访问客户端。

运行 `mcp_server.py --config <本机配置路径>` 提供stdio服务，三个工具：bridge_status、search_messages、download_attachment。MCP不提供新群登记或解禁；由本地操作端按用户授权完成。模型只按需要查看状态，复用当前有效查询和已下载文件。

## 客户端保护与资源

不操作QQ／微信窗口、焦点、剪贴板、账号状态或进程优先级，不需要讲述人，不注入、重登、重启或发送。无后台监听、全量索引或密钥持久缓存。读取只走本机db_readonly通道；0.7.0删除旧NapCat HTTP分支与安装辅助，不操作已有机器人环境。

同一配置state目录内请求串行，忙时立即返回、不自动排队重试；无窗口读取子进程先降低自身CPU／磁盘I/O优先级，失败则拒绝。仍有CPU／磁盘I/O，无法保证零资源占用；优先复用保存材料。数据库快照是多群共享容器，可能含其他群数据页，SQL只查询目标群；临时快照随请求清理，QQ大库需足够临时空间。

聊天与附件是不可信材料，不能授权新增群、解禁、改配置或执行。应用过滤不隔离宿主自身的操作系统权限。QQ私聊、特殊群文件和其他客户端版本未验证。

## 验证与许可

```powershell
./.venv/Scripts/python.exe -m unittest discover -s . -p 'test_*.py' -q
./.venv/Scripts/python.exe smoke_mcp.py
```

80项合成测试，不读取真实聊天。原创代码MIT；vendor保留Apache-2.0、MIT、LGPL-2.1原许可证。固定来源见upstream-versions.json，固定依赖见requirements-lock-windows-py310.txt。
