# Validation / 验证摘要

Public summary, 2026-10-30. Raw chat records, group identifiers, source messages, configuration and downloaded materials remain private.

## Automated checks

80 tests use synthetic data and temporary fixtures: default deny, block precedence, old-receipt revocation, exact group scope, ambiguous names, dates, account checks, temporary cleanup, source digests, media redaction, QQ fixed-command / response validation, committed-WAL handling and original attachment indices. Blocks or account changes arriving during search / download prevent completed results. Unsupported legacy adapters fail before client access.

The official MCP SDK completes a local stdio handshake, discovers exactly three tools and rejects an unapproved alias. The installed Skill launcher is checked with isolated CLI / MCP fixtures and block / unblock operations. No clients are logged into or read. Local account / block configuration is checked byte-for-byte unchanged.

Reader startup lowers only the bridge child process. A real child probe rejects an invalid operation before client access; lock contention rejects a competing reader before spawning. Dependencies and vendored sources are unchanged. The inventory / bundle module and its dedicated tests were removed together in 0.7.0; query / download revocation regressions remain.

## Earlier real-client checks (0.5.x)

In the validated environment, requests were scoped to two explicitly authorized groups and bounded dates. The same samples were queried again after the client's reported upgrade, then fetched through the skill's real CLI with new receipts.

| Active retrieval | Bytes | Result |
| --- | ---: | --- |
| QQ standard group file | 82,832 | Source size / MD5 matched; SHA256 matched the previously verified same sample |
| QQ image | 105,057 | Source MD5 matched; decoded image 864×1920 |
| WeChat original image | 2,895,047 | Source size / MD5 matched; decoded image 3213×5712 |
| WeChat file | 8,394,592 | Source size / MD5 matched; SHA256 matched the previously verified same sample |

QQ and WeChat process IDs / start times and the local configuration remained unchanged during revalidation. Request-temporary directories were empty afterward. No Narrator, window automation, injection or client restart was used. Downloaded files were not executed.

These results establish compatibility for the [listed versions](COMPATIBILITY.md) and sample types, not every version, account state, file type or complete message history. Source archives are checked for private-data exclusions, file hashes and deterministic rebuilds; an extracted default configuration enables no account or group.

The 0.7.0 simplification uses isolated fixtures instead of repeating real-account reads. No zero-CPU / disk-use claim is made for database queries.
