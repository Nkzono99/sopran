# License（ライセンス）

SOPRAN 本体は Apache License 2.0 を想定しています。

SPEDAS/IDL 由来の挙動を参考にする場合でも、公開 API と実装は pure Python + Rust として
再実装し、IDL ソースのコピーを取り込まない方針です。

ライセンス確認の基本方針:

| 対象 | 方針 |
| --- | --- |
| SOPRAN の新規コード | Apache-2.0 |
| SPEDAS の挙動 | 仕様理解と parity test の参考 |
| SPEDAS のソース文面 | 直接コピーしない |
| 外部データ | provider の利用条件を dataset manifest に残す |

詳細な upstream 調査結果は `THIRD_PARTY_NOTICES.md`、設計ドラフト、または issue に分けます。
