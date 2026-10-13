# ライセンスと移植

SOPRANの独自のコードとドキュメントはApache License 2.0で公開しています（`LICENSE`、`NOTICE`）。
プロジェクトのメタデータ、`LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md`の内容はそろえて保ちます。

## SPEDASの挙動を移すとき

SOPRANはKAGUYAなどの処理で、IDLのSPEDASの挙動を参考にしています。現在、SPEDASやPySPEDASのソースはコピーしていません。

| 対象 | 方針 |
|---|---|
| SOPRANの新しいコード | Apache-2.0 |
| SPEDASの挙動 | 仕様を理解する材料と、一致を確かめるテストの基準に使う |
| MITライセンスのSPEDAS・PySPEDASのルーチン | 移植してよい。コピーや派生を含む部分には元の著作権表示とMITの許諾文を残し、`SPDX-License-Identifier: Apache-2.0 AND MIT`と出典を書く |
| GPLやNASA Open Source Agreementの外部コンポーネント | 別にライセンスを確認するまでコアのパッケージへコピーしない |
| 外部のデータ | 配布元の利用条件をデータセットのマニフェストに残す |

移植したファイルには、元のルーチン、元のコミットまたは版、そしてクリーンな再実装・挙動を合わせた書き直し・直訳のどれかを書きます。
可能な限り、公開の機器仕様・論文・golden testからPythonとRustで実装し直します。SPEDASと比べたときは、
比べたSPEDASの版とルーチンのパスを記録します。第三者のコードの断片は、公開APIを変えずに監査・置換・削除できるよう分けて置きます。

調査の結果と方針の詳細は`THIRD_PARTY_NOTICES.md`にあります。
