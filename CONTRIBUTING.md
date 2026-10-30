# Contributing / 贡献说明

Use Windows x64 and Python 3.13.18 for the currently validated environment. Create the program's `.venv`, install `chat-task-bridge/requirements-lock-windows-py313.txt`, then run the unit suite and `smoke_mcp.py` as described in the README. Automated tests must work without a logged-in QQ or WeChat account.

兼容性修改请区分合成测试和本人客户端实测。报告实际客户端版本、QQ 加载内核、调用阶段和脱敏错误即可；不要上传真实数据库、消息正文、账号目录、下载附件或内存转储。不得把“仅更新版本号或模块哈希”当作兼容性验证。

Keep changes scoped to the task. Preserve default-deny filtering, block precedence, per-request cleanup and credential redaction. Any new retrieval path should validate source identity, size and available message digests. Do not add background monitoring or sending to the three-tool MCP interface as part of an unrelated fix.

Third-party modules retain upstream licenses and provenance. If modifying a vendored file, document the modification and update its SHA256 inventory; do not remove copyright or license notices. Original contributions use the repository's MIT license, except where a file states otherwise.

Security regressions use synthetic credentials: TLS validation with no HTTP fallback, DPAPI/tamper checks, private ACLs, bounded cleanup, source-zone marks and minimal worker environments. Do not use live credentials in test fixtures.
