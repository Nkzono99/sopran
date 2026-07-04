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

Parameterized product は dataset root の下に `variants/<variant_id>/` を作ります。
たとえば LMAG magnetic connection は `radius_km` や `direction` を variant metadata に
記録し、別 variant を同じ `dataset_id` の下で共存させます。

```text
features/kaguya/lmag/magnetic_connection/variants/sphere_1737.4_both/
  dataset.json
  schema.json
  catalog.parquet
  shards/
```

## catalog columns

| column | 内容 |
| --- | --- |
| `path` | shard path |
| `start` / `stop` | time coverage |
| `row_count` | 行数 |
| `checksum` | shard checksum |
| `status` | `complete`, `failed`, `skipped` など |

## dataset manifest

Parquet dataset には `storage_layout` を記録します。これは schema の dims と実際の
table columns の対応を読むための metadata です。

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

`layout="array"` の場合は、`time` などの index column と配列値 column だけを持ち、
未展開の次元は `encoded_dims` に入ります。

`dataset.json` と `schema.json` が source of truth で、`registry/*.parquet` は検索用 index
です。
