# Validation / 验证摘要

Public summary, 2026-10-30. Raw chat records, group identifiers, source messages, configuration and downloaded materials remain private.

## Automated checks

96 tests use synthetic data and temporary fixtures: default deny, block precedence, old-receipt revocation, exact group scope, ambiguous names, dates, account checks, temporary cleanup, source digests, media redaction, QQ fixed-command / response validation, and committed-WAL handling. Windows directory aliases are resolved consistently with the bound database path; a different database is still rejected.

The official MCP SDK completes a real local stdio handshake, discovers exactly four tools and rejects an unapproved alias. The installed skill launcher is separately checked with isolated Unicode JSON, block / unblock operations, offline material preparation and MCP transport. These checks do not log into clients or read real chats.

0.6.0 adds coverage for versioned scope / bounded results, original attachment indices, missing or corrupt local copies, path / receipt escapes, same-name files, portable relative paths, literal Markdown content, per-call budgets and blocks / rebinds arriving during query, download or copy. Reader startup lowers only the bridge child process; a real child probe rejects an invalid operation before any client access. Shared-lock contention is rejected before spawning a reader. Dependencies and vendored sources are unchanged.

## Earlier real-client checks (0.5.x)

In the validated environment, requests were scoped to two explicitly authorized groups and bounded dates. The same samples were queried again after the client's reported upgrade, then fetched through the skill's real CLI with new receipts.

| Active retrieval | Bytes | Result |
| --- | ---: | --- |
| QQ standard group file | 82,832 | Source size / MD5 matched; SHA256 matched the previously verified same sample |
| QQ image | 105,057 | Source MD5 matched; decoded image 864×1920 |
| WeChat original image | 2,896,047 | Source size / MD5 matched; decoded image 3213×5712 |
| WeChat file | 8,396,592 | Source size / MD5 matched; SHA256 matched the previously verified same sample |

QQ and WeChat process IDs / start times and the local configuration remained unchanged during revalidation. Request-temporary directories were empty afterward. No Narrator, window automation, injection or client restart was used. Downloaded files were not executed.

These results establish compatibility for the [listed versions](COMPATIBILITY.md) and sample types, not every version, account state, file type or complete message history. Source archives are checked for private-data exclusions, file hashes and deterministic rebuilds; an extracted default configuration enables no account or group.

The 0.6.0 integration reused synthetic materials rather than running another query against those real accounts. Offline material preparation never opens client databases or the network. No claim of zero CPU / disk use is made for a real database query; serialization and scheduling reduce competition for resources.
