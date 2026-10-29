# Changelog

## 0.5.1 — 2026-10-30

First public GitHub release. Added bilingual repository documentation, explicit MIT licensing for original work, third-party notices, private-data exclusions and Windows CI. Source bundles now include license and ignore files. Fixed QQ database identity checks comparing resolved source paths with unresolved Windows short paths / directory aliases; different databases remain rejected. 68 synthetic tests.

首次公开发布。补齐中英双语说明、原创代码 MIT 许可、第三方许可索引、隐私排除和 Windows CI；技能及程序包包含许可证。修复 QQ 数据库核验对 Windows 短路径／目录别名处理不一致的问题，仍拒绝其他数据库；68 项合成测试。

## 0.5.0 — 2026-10-30

- Reusable `qq-wechat-task-materials` skill and JSON launcher.
- Exact named-group metadata lookup, explicit per-task admission and block management.
- Seven-day default search window, bounded expansion and preserved legacy blocks.
- WeChat 4.2.0.9 validated alongside 4.1.15.56; 66 automated tests.

## 0.4.0 — 2026-10-30

- Active standard QQ group-file download through a fixed ticket request and HTTPS.
- Actual runtime-kernel and module-hash binding; read workers use reduced priority.

## 0.3.0 — 2026-10-30

- Active WeChat original-image / file and QQ image retrieval.
- Media credentials removed from model-visible results and download manifests.

## 0.2.0 — 2026-10-30

- Direct read-only QQ / WeChat adapters without Narrator or window automation.

## 0.1.0 — 2026-10-29

- Initial scoped CLI / MCP prototype. Superseded by the direct-read implementation.
