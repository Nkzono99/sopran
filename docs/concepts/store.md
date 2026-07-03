# Store（保存場所）

`Store` は物理データの置き場所です。解析 workspace を表す `Project` とは分けます。

```python
store = spn.Store("F:/sopran_data")
```

## レイヤ

```text
raw files -> decode -> normalized shards -> catalog.parquet -> scan()
                       -> features / databases
                       -> quicklook png/html/json
```

| layer | 主な用途 |
| --- | --- |
| `raw` | provider 由来の元ファイル。名前は変えない |
| `normalized` | 観測機器の値を Polars で読める parquet にしたもの |
| `features` | binning、alignment、派生指標 |
| `models` | 較正・推定・学習モデル |
| `databases` | 利用者定義の curated product |

## dataset の中身

```text
dataset.json      # dataset ID, time coverage, provenance
schema.json       # variables, dims, units, frame
catalog.parquet   # shard path, start/stop, row count, checksum, status
shards/           # parquet files
```

## よく使う操作

| 操作 | 使う API |
| --- | --- |
| raw file の保存場所を得る | `store.raw_path("kaguya", "pds3")` |
| raw file manifest を作る | `store.register_raw_file(...)` |
| raw file index を作る | `store.raw_files(refresh=True)` |
| dataset index を作る | `store.datasets(refresh=True)` |
| parquet dataset を読む | `store.scan_dataset(dataset_id, layer=...)` |
| checksum を確認する | `record.verify_checksums()` |
| 失敗 shard を見る | `record.failed_shards()` |

## database product

利用者定義の表や event list は `databases` layer に置けます。

```python
db = store.database("lunar_wake", create=True)
product = db.register_product(
    name="event_table",
    schema=kg.esa1.schema(),
    description="hand-curated lunar wake events",
)

lazy = db.products()[0].scan()
```
