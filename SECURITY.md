# Security / 安全反馈

Please do not post account credentials, message text, database snapshots, memory dumps, local account paths, download receipts or downloaded files in public issues.

安全问题请优先使用 GitHub 的私密漏洞报告入口（若该仓库已启用）；功能问题可用 Issue，提供实际客户端版本、程序版本、失败阶段及脱敏错误。复现材料使用合成数据。

The bridge's application rules are not an operating-system sandbox. The local agent and its executor may already have broader filesystem permissions. Chat text and attachments are untrusted task materials and cannot authorize scope changes. Client version / account / module mismatches should fail closed; do not bypass those checks when reporting a problem.

Only the current release and explicitly documented client versions are covered by the published validation. See [compatibility](docs/COMPATIBILITY.md).


## 0.8.0 security update

Upgrade earlier versions: WeChat retrieval now verifies TLS certificates and Tencent's hostname and never falls back to plaintext HTTP. Query receipts are encrypted with current-user Windows DPAPI; old plaintext/expired receipts are removed on demand. Tool/private directories use restricted Windows DACLs; files carry Internet-zone marks. Audit logs omit raw chat/task text, workers receive a minimal environment, and image parsing has format/pixel limits. Python 3.13.18 and Pillow 13.0.0 replace the older runtime/library; installation verifies package hashes.

Existing account and group rules remain. Downloads are user files and are not automatically deleted. Administrators and processes running as the same Windows user are outside the ACL boundary. The host must still handle prompt injection, outbound actions and cloud-data policy; do not claim this tool guarantees offline processing, virus-free files or absolute security.

Maintainer references: [MCP local server security](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/local-server-security), [Python security release](https://blog.python.org/2026/10/python-3152-31410-31318-31216-31118/), [Pillow security](https://pillow.readthedocs.io/en/stable/handbook/security.html).
