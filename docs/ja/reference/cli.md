# コマンドライン

SOPRANをインストールすると、次のコマンドが使えます。どれも`python -m <モジュール>`の形でも呼べます。

| コマンド | モジュール | 用途 |
|---|---|---|
| `sopran-store` | `sopran.core.sync` | Storeの同期・検証・索引の作り直し |
| `sopran-env-check` | `sopran.env_check` | ソースからビルドするための環境の確認 |
| `sopran-schema-docs` | `sopran.schema_docs` | スキーマのリファレンスの生成 |
| — | `sopran.experimental.kaguya.er_batch` | ERの全期間バッチ（[ER全期間バッチ](../experimental/er-batch.md)） |

## sopran-store

```text
sopran-store [--data-root DATA_ROOT] {sync-list,verify,rebuild,excludes} ...
```

`--data-root`を省くと、[設定](../guide/configuration.md)に従うStoreを使います。

| サブコマンド | 動作 | オプション |
|---|---|---|
| `sync-list` | `rsync --files-from`に渡すファイルの一覧を標準出力に書く。既定は`managed`のデータセットだけ | `--dataset ID`（IDかその先頭部分）、`--layer`、`--variant`、`--all`（managedでないものも含める）、`--raw PREFIX`（`raw/`の下を加える） |
| `verify` | シャードをカタログと付属JSONに照らして確かめる | `--dataset`、`--layer`、`--variant`、`--all` |
| `rebuild` | 付属JSONからカタログと索引を作り直す。付属JSONの無い古いデータセットには作る | `--layer` |
| `excludes` | 同期しないファイルのパターンを書く（`rsync --exclude-from`用） | |

手順の例は[Storeを別マシンへ運ぶ](../guide/store-sync.md)にあります。

## sopran-env-check

```text
sopran-env-check [--native]
```

ソースからインストールするのに必要なものがそろっているかを確かめます。`--native`は、Rust拡張`sopran._native`をビルドするための
Rustのツールチェーンと、WindowsではMSVCのビルドツールを確かめます。

## sopran-schema-docs

```text
sopran-schema-docs [--check] [--language {ja,en}] [path]
```

コードのスキーマ定義から[スキーマ](schemas.md)のページを生成します。`path`の既定は`docs/ja/reference/schemas.md`です。
`--check`は書き込まずに、ファイルが最新でなければ0以外で終わります（CIで使います）。

```bash
python -m sopran.schema_docs docs/ja/reference/schemas.md
python -m sopran.schema_docs --language en docs/en/reference/schemas.md
```
