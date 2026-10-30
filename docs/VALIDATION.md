# Validation / 验证摘要

2026-10-31, 0.10.0. Raw chat records, account/group identifiers, credentials, configuration and downloaded samples stay private.

## Automated checks

140 synthetic tests cover group scope, blocks and account changes during operations, source checks, database/WAL handling, serialized workers and cleanup. Security regressions cover DPAPI encryption/tampering, legacy rejection, expiration, private Windows ACLs, audit redaction, minimal child environments, source-zone marks, raster formats, TLS certificate/name validation, rejection of redirects and no HTTP fallback. A two-range fixture verifies TLS connection reuse and final closure.

The official MCP SDK performs a local stdio handshake and discovers the same four tools. Installed Skill CLI/MCP checks use isolated fixtures, including query/download and revocation after a new block. Python 3.13.18, Pillow 13.0.0 and 34 hash-locked packages are used. Tests require no QQ/WeChat login.

## Real-client regression

Only the same four previously authorized message samples in the same groups and dates were queried and retrieved. No group/date expansion or attachment execution occurred.

| Sample | Bytes | Result |
| --- | ---: | --- |
| QQ standard group file | 82,832 | Source SHA256 matched; SSO then HTTPS |
| QQ image | 105,057 | Source SHA256 matched; HTTPS |
| WeChat original image | 2,895,047 | Source SHA256 matched; verified HTTPS |
| WeChat file | 8,394,592 | Source SHA256 matched; verified HTTPS |

All retrieved files have Windows Internet-zone marks. Client processes and account/group/block configuration bytes stayed unchanged. The initial per-range TLS implementation timed out on the larger file; per-download connection reuse and bounded larger ranges resolved it. Final WeChat sample operations took about six to seven seconds each in this environment, not a general performance guarantee.

## Local privacy and remaining boundaries

Local hardening affected only this tool's roots, protected ordinary-user access and removed 28 old/expired query receipts. Current receipts are protected with current-user DPAPI. This is not isolation from administrators or other programs running as the same Windows user. Saved attachments are not automatically deleted or certified virus-free. Cloud model processing is governed by the chosen host/service; Skill/MCP instructions do not create an OS sandbox.

Public source checks exclude local settings, private data and credential-shaped material, verify vendor hashes and relative Markdown links. Reproducible archives are built from the reviewed public commit; see [compatibility](COMPATIBILITY.md) for the tested client versions.

## Merged records / 合并聊天记录

0.9.0 adds read_merged_record / read-record with source-bound, per-record QQ retrieval and WeChat inline XML parsing. Tests cover nested/escaped XML, DTD rejection, media credential redaction, limits, compression, source mismatch, unseen IDs, cache-only and revocation before/during expansion. One real QQ merged record expanded successfully; original client processes and configuration stayed unchanged. No suitable WeChat merged record occurred in the existing authorized group in this bounded check, so WeChat live validation remains pending. QQ merged images and group files have now passed live retrieval, including source-digest checks and readable XLSX/DOCX structures. WeChat merged media is fixture-tested only; a live sample is still pending.
