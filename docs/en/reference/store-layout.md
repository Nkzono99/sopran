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

Parameterized products create `variants/<variant_id>/` below the dataset root.
For example, LMAG magnetic connection records values such as `radius_km` and
`direction` in variant metadata, allowing multiple variants to coexist under one
`dataset_id`.

```text
features/kaguya/lmag/magnetic_connection/variants/sphere_1737.4_both/
  dataset.json
  schema.json
  catalog.parquet
  shards/
```

## Catalog Columns

| Column | Meaning |
| --- | --- |
| `path` | Shard path |
| `start` / `stop` | Time coverage |
| `row_count` | Row count |
| `checksum` | Shard checksum |
| `status` | `complete`, `failed`, `skipped`, and related states |

## Dataset Manifest

Parquet datasets record `storage_layout` metadata so schema dimensions can be
mapped back to table columns.

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

When `layout="array"`, the table has index columns such as `time` plus an array
value column. Non-expanded dimensions are listed in `encoded_dims`.

`dataset.json` and `schema.json` are the source of truth. `registry/*.parquet`
files are search indexes.
