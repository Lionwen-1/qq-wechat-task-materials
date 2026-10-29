# Third-party notices / 第三方许可说明

The MIT license at repository root covers original bridge code, the skill and documentation. It does **not** replace the licenses of vendored files. Their original notices, license texts and complete distributed module source are included.

| Component | Source / pinned revision | License | Included files |
| --- | --- | --- | --- |
| WeChat read modules | [wechatauto-replica](https://github.com/fanyuantaier/wechatauto-replica/tree/6e603974bbac3bda93d88bbd6995510ae2547f5c) | Apache-2.0 | `chat-task-bridge/vendor/wechatauto_readonly/` |
| QQ key / message parsing | [qq-nt-export](https://github.com/q957506633/qq-nt-export/tree/bec1504170f99e2752793320711c5653f3803670) | MIT | `chat-task-bridge/vendor/qqnt_readonly/` |
| WeChat CDN protocol adaptation | [wechat-digest](https://github.com/rmqg/wechat-digest/blob/b2a728bddf3c48dad47f92bb9beeb1fbcc4631fd/deployment/fetch-originals.py) | MIT | `wechat_cdn.py` adaptation and `vendor/wechat_digest_LICENSE` |
| Independent QQ-TEA module | [lagrange-python](https://github.com/LagrangeDev/lagrange-python/blob/572d711c5cd23e45c02c5052d4ec0833a3392cf7/lagrange/utils/crypto/tea.py) | LGPL-2.1 | `chat-task-bridge/vendor/lagrange_crypto/` |

The QQ-TEA source is included unchanged and dynamically loaded as an independent module. It can be modified or replaced; no upstream client initializer, login or event listener is imported. No compiled client or proprietary QQ / WeChat binary is distributed.

Detailed file attribution: [`vendor/NOTICE.md`](chat-task-bridge/vendor/NOTICE.md). Integrity inventory: [`vendor/SHA256SUMS.json`](chat-task-bridge/vendor/SHA256SUMS.json). Other public protocol / layout references and all pinned revisions: [`upstream-versions.json`](chat-task-bridge/upstream-versions.json).

Pinned Python dependencies are installed separately and retain their own distribution licenses. QQ, WeChat and their names / marks belong to their respective owners; this is an independent project.
