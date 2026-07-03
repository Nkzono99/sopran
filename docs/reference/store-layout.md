# Store layout（保存構造）

`Store` は raw file と SOPRAN dataset を同じ root の下に分けて置きます。

```text
F:/sopran_data/
  raw/
  normalized/
  features/
  models/
  databases/
  cache/
  registry/
```

## raw

```text
raw/<mission>/<provider>/<provider-path>/<filename>
raw/<mission>/<provider>/<provider-path>/<filename>.sopran.json
```

Sidecar manifest には provider path、download URL、checksum、byte size、
acquired time を記録します。

## dataset

```text
normalized/kaguya/esa1/counts/
  dataset.json
  schema.json
  catalog.parquet
  logs/
  preview/
  shards/
    year=2008/month=01/day=01/part-000.parquet
```

## catalog columns

| column | 内容 |
| --- | --- |
| `path` | shard path |
| `start` / `stop` | time coverage |
| `row_count` | 行数 |
| `checksum` | shard checksum |
| `status` | `complete`, `failed`, `skipped` など |

`dataset.json` と `schema.json` が source of truth で、`registry/*.parquet` は検索用 index
です。
