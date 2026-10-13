# Storeのファイル構造

Storeのディレクトリとファイルの形式です。使い方は[Storeにデータを保存する](../guide/store.md)、
別の計算機への移動は[Storeを別マシンへ運ぶ](../guide/store-sync.md)にあります。

```text
/path/to/sopran_data/
  raw/          配布元の元ファイル
  normalized/   機器の標準的な物理量
  features/     SOPRANが計算した派生量
  models/       校正・モデル当てはめの結果
  databases/    研究テーマごとに採用した表
  cache/        再生成できる一時ファイル（計算機ごと）
  registry/     検索用の索引（計算機ごと、自動生成）
```

## 元ファイル

```text
raw/<mission>/<provider>/<配布元のパス>/<ファイル名>
raw/<mission>/<provider>/<配布元のパス>/<ファイル名>.sopran.json
```

付属JSONには次を記録します。

| キー | 内容 |
|---|---|
| `path` | Storeのルートからの相対パス |
| `filename`、`mission`、`provider`、`provider_path`、`version` | 配布元での識別 |
| `download_url`、`acquired_at` | 取得元と取得日時（UTC） |
| `checksum`、`size_bytes` | sha256とバイト数 |

## データセット

```text
<layer>/<データセットIDの「.」を「/」にしたパス>/
  dataset.json        マニフェスト
  schema.json         変数・次元・単位・座標系
  catalog.parquet     シャードの索引（付属JSONから作り直せる）
  shards/             Parquetのシャードと、それぞれの <shard>.sopran.json
  logs/               Pipelineの実行記録 <run_id>.json
  preview/            Pipelineのクイックルック
  work/               実行途中のファイル（計算機ごと）
```

日別に分けたシャードは`shards/year=2008/month=01/day=01/part-000.parquet`のようなHive形式のパスです。
計算条件の違う結果は、同じデータセットIDの下の`variants/<variant_id>/`に、上と同じ構成で並べます。

```text
features/kaguya/lmag/magnetic_connection/variants/sphere_1737.4_both/
```

### マニフェスト（`dataset.json`）

| キー | 内容 |
|---|---|
| `dataset_id`、`layer`、`mission`、`instrument`、`product` | データセットの識別 |
| `version` | 内容の版（既定`"1"`） |
| `schema_version` | スキーマの版 |
| `status` | `scratch`、`candidate`（既定）、`adopted`、`deprecated` |
| `managed` | SOPRANが自動で作り再利用するデータセットか。同期の既定の対象になる |
| `time_coverage` | データの期間 |
| `source_files`、`source_datasets` | 入力の元ファイル（Store内はルートからの相対パス）と入力データセット |
| `provenance` | 来歴。Pipelineの段・期間・ダウンロード方針・run ID、解析条件（`context`）など |
| `parameters` | 生成に使った設定。処理履歴（`operations`）、時刻合わせの設定（`alignment`）など |
| `partitioning` | シャードの分け方（例：`["year", "month", "day"]`） |
| `producer`、`software`、`created_at` | 作った処理、SOPRANとPythonの版、作成日時 |

Parquetのデータセットは、スキーマの次元と表の列の対応を`storage_layout`に記録します。

```json
{
  "storage_layout": {
    "format": "parquet",
    "layout": "long",
    "index_columns": ["time", "energy", "look"],
    "value_columns": ["counts"],
    "encoded_dims": []
  }
}
```

`layout="array"`では、`time`などの索引列と配列値の列だけを持ち、展開していない次元を`encoded_dims`に入れます。

### カタログ（`catalog.parquet`）

| 列 | 内容 |
|---|---|
| `path` | シャードのパス |
| `start`、`stop` | シャードの期間 |
| `row_count` | 行数 |
| `checksum` | シャードのsha256 |
| `status` | `pending`、`running`、`complete`、`failed`、`skipped` |
| `schema_version` | スキーマの版 |

通常の読み込み（`record.scan()`）は`complete`のシャードだけを読みます。

## 正本と索引

`dataset.json`・`schema.json`と各シャードの付属JSONが正本です。`catalog.parquet`と`registry/*.parquet`は
そこから作り直せる索引で、`sopran-store rebuild`で再生成できます。

## 同期の対象外

計算機ごとのファイルは同期しません。パターンは`sopran-store excludes`で表示できます。

```text
*.sopran-tmp*
*.sopran-bak*
/registry/
/cache/
work/
```
