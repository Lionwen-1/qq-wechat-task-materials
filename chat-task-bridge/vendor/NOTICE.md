# Third-party read modules

Only the listed read modules are vendored. Their original files are unchanged.
Application wrappers select one account, suppress key persistence, constrain queries,
use request-scoped snapshots, and do not import upstream GUI/send/listener entrypoints.

- wechatauto_readonly/db.py, media.py: fanyuantaier/wechatauto-replica,
  commit 6e603974bbac3bda93d88bbd6995510ae2547f5c, Apache-2.0.
  Original license: wechatauto_readonly/LICENSE.
- qqnt_readonly/key_scan.py (upstream scripts/ntqq_key_scan.py), msg_parser.py
  (upstream scripts/ntqq_msg_parser.py): q957506633/qq-nt-export,
  commit bec1504170f99e2752793320711c5653f3803670, MIT.
  Copyright (c) 2026 qq-nt-export contributors; original license: qqnt_readonly/LICENSE.

Do not run the upstream standalone scan/export entrypoints on real accounts: some
write keys or export all chats. The bridge invokes only reviewed read functions.

wechat_cdn.py adapts the bounded inbound range protocol / verification approach
from rmqg/wechat-digest, deployment/fetch-originals.py,
commit b2a728bddf3c48dad47f92bb9beeb1fbcc4631fd, Copyright (c) 2026 rmqg, MIT.
License: wechat_digest_LICENSE. The Windows wrapper and QQ CDN adapter are local
implementations. No upstream login, send, deployment or monitoring entrypoint runs.

lagrange_crypto/tea.py is unchanged from LagrangeDev/lagrange-python,
commit 572d711c5cd23e45c02c5052d4ec0833a3392cf7,
lagrange/utils/crypto/tea.py, LGPL-2.1. Copyright remains with its upstream
contributors. License: lagrange_crypto/LICENSE. The complete module source is
included and loaded dynamically; users may modify or replace this library file.
The bridge does not import the upstream package initializer, client, login,
heartbeat, event listeners or sending APIs. Its own SSO wrapper accepts only one
fixed group-file download command with a fresh, selected-message descriptor.
