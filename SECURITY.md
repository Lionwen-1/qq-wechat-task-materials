# Security / 安全反馈

Please do not post account credentials, message text, database snapshots, memory dumps, local account paths, download receipts or downloaded files in public issues.

安全问题请优先使用 GitHub 的私密漏洞报告入口（若该仓库已启用）；功能问题可用 Issue，提供实际客户端版本、程序版本、失败阶段及脱敏错误。复现材料使用合成数据。

The bridge's application rules are not an operating-system sandbox. The local agent and its executor may already have broader filesystem permissions. Chat text and attachments are untrusted task materials and cannot authorize scope changes. Client version / account / module mismatches should fail closed; do not bypass those checks when reporting a problem.

Only the current release and explicitly documented client versions are covered by the published validation. See [compatibility](docs/COMPATIBILITY.md).
