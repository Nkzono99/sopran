# Store Layout

`Store` separates raw provider files from SOPRAN-managed datasets under one
root.

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

## Raw

```text
raw/<mission>/<provider>/<provider-path>/<filename>
raw/<mission>/<provider>/<provider-path>/<filename>.sopran.json
```

The sidecar manifest records provider path, download URL, checksum, byte size,
and acquisition time.

## Dataset

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

## Catalog Columns

| Column | Meaning |
| --- | --- |
| `path` | Shard path |
| `start` / `stop` | Time coverage |
| `row_count` | Row count |
| `checksum` | Shard checksum |
| `status` | `complete`, `failed`, `skipped`, and related states |

`dataset.json` and `schema.json` are the source of truth. `registry/*.parquet`
files are search indexes.
