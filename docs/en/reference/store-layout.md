# Store Layout

Directories and file formats of a Store. Usage is in [Storing Data](../guide/store.md),
and moving to another machine in [Moving A Store](../guide/store-sync.md).

```text
/path/to/sopran_data/
  raw/          source files from providers
  normalized/   standard instrument quantities
  features/     quantities derived by SOPRAN
  models/       calibration and model-fit results
  databases/    tables adopted per research topic
  cache/        regenerable temporary files (machine-local)
  registry/     search indexes (machine-local, generated)
```

## Source files

```text
raw/<mission>/<provider>/<provider path>/<filename>
raw/<mission>/<provider>/<provider path>/<filename>.sopran.json
```

The sidecar JSON records:

| Key | Contents |
|---|---|
| `path` | Path relative to the Store root |
| `filename`, `mission`, `provider`, `provider_path`, `version` | Identification at the provider |
| `download_url`, `acquired_at` | Source URL and retrieval time (UTC) |
| `checksum`, `size_bytes` | sha256 and size in bytes |

## Datasets

```text
<layer>/<dataset ID with "." replaced by "/">/
  dataset.json        manifest
  schema.json         variables, dimensions, units, frames
  catalog.parquet     shard index (rebuildable from sidecars)
  shards/             Parquet shards, each with <shard>.sopran.json
  logs/               Pipeline run records <run_id>.json
  preview/            Pipeline quicklooks
  work/               files of runs in progress (machine-local)
```

Daily shards use Hive-style paths such as `shards/year=2008/month=01/day=01/part-000.parquet`.
Results under different conditions sit under the same dataset ID in `variants/<variant_id>/`, each with the layout above.

```text
features/kaguya/lmag/magnetic_connection/variants/sphere_1737.4_both/
```

### Manifest (`dataset.json`)

| Key | Contents |
|---|---|
| `dataset_id`, `layer`, `mission`, `instrument`, `product` | Dataset identification |
| `version` | Content version (default `"1"`) |
| `schema_version` | Schema version |
| `status` | `scratch`, `candidate` (default), `adopted`, `deprecated` |
| `managed` | Whether SOPRAN creates and reuses the dataset by itself; the default target of synchronization |
| `time_coverage` | Time range of the data |
| `source_files`, `source_datasets` | Input source files (root-relative inside the Store) and input datasets |
| `provenance` | Pipeline stages, time range, download policy, run ID, analysis conditions (`context`), and so on |
| `parameters` | Settings used to create the data, such as processing history (`operations`) and alignment settings (`alignment`) |
| `partitioning` | How shards are split (for example `["year", "month", "day"]`) |
| `producer`, `software`, `created_at` | Producing process, SOPRAN and Python versions, creation time |

Parquet datasets record how schema dimensions map to table columns in `storage_layout`.

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

With `layout="array"`, only index columns such as `time` and array-valued columns are stored, and unexpanded dimensions are listed in `encoded_dims`.

### Catalog (`catalog.parquet`)

| Column | Contents |
|---|---|
| `path` | Shard path |
| `start`, `stop` | Time range of the shard |
| `row_count` | Number of rows |
| `checksum` | sha256 of the shard |
| `status` | `pending`, `running`, `complete`, `failed`, `skipped` |
| `schema_version` | Schema version |

Regular reads (`record.scan()`) read only `complete` shards.

## Sources of truth and indexes

`dataset.json`, `schema.json`, and the sidecar of each shard are the sources of truth. `catalog.parquet` and `registry/*.parquet`
are indexes rebuilt from them with `sopran-store rebuild`.

## Not synchronized

Machine-local files are never synchronized. `sopran-store excludes` prints the patterns.

```text
*.sopran-tmp*
*.sopran-bak*
/registry/
/cache/
work/
```
