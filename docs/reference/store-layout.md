# Store Layout

```text
sopran_data/
  raw/
  normalized/
  features/
  models/
  databases/
  registry/
  cache/
```

Dataset layout:

```text
dataset.json
schema.json
catalog.parquet
shards/
logs/
```

Catalog rows currently include:

- `path`
- `schema_version`
- `start`
- `stop`
- `row_count`
- `checksum`
- `status`

The catalog is the boundary for append, replace, and lazy scan operations.
`DatasetRecord.verify_checksums()` compares catalog checksums with the current
shard files. It audits every catalog shard by default; pass `status="complete"`
to verify only the shard set used by `scan()`.
`DatasetRecord.update_shard_status(path, status)` updates the
catalog status for one shard; allowed statuses are `pending`, `running`,
`complete`, `failed`, and `skipped`. `DatasetRecord.shards(status=...)` lists
catalog rows and `DatasetRecord.failed_shards()` returns rows marked `failed`.
`DatasetRecord.scan()` scans only rows marked `complete`; datasets with no
complete parquet shards raise `DatasetNotFoundError`.
`DatasetRecord.replace_shard(path, frame=..., time_coverage=...)` overwrites an
existing cataloged shard and updates its checksum, row count, time coverage, and
status.

Raw file sidecar layout:

```text
raw/kaguya/l2/example.dat
raw/kaguya/l2/example.dat.sopran.json
```

The sidecar manifest records the relative raw path, filename, mission, provider,
provider path, data version, download URL, acquisition time, SHA-256 checksum,
and byte size. `RawFileRecord` can compare the manifest checksum with the
current file checksum. `Store.raw_file(...)` reopens a raw file and sidecar
manifest as a `RawFileRecord`.

`dataset.json` includes dataset lifecycle metadata. `version` is the dataset
content version and defaults to `"1"`. `status` is one of `scratch`,
`candidate`, `adopted`, or `deprecated`, and defaults to `candidate`.
`created_at` is written as a UTC ISO-8601 timestamp. The manifest also includes
a `software` object with the SOPRAN package version and Python runtime version.
`source_datasets` stores input dataset IDs for derived products and is merged
without duplicates on append. `partitioning` records Parquet partition columns.
`parameters` stores JSON-serializable generation settings, and defaults to an
empty object. The manifest may also include a `provenance` object. The first
supported producer is the KAGUYA ESA1 pipeline, which records pipeline source,
stages, run mode, run ID, time range, output dataset/layer, and selected
variable. Dataset-writing KAGUYA ESA1 pipeline runs also write structured logs
under `logs/<run_id>.json` with run mode, status, start/finish timestamps,
elapsed seconds, declared stage parameters, per-stage row/shard counts, shard
rows, and total row count.
`Store.dataset_source_files(...)` resolves the manifest `source_files` list back
to raw sidecar records. `Store.verify_dataset(...)` checks both dataset shard
checksums and raw input checksums. Use
`Store.verify_dataset(..., shard_status="complete")` when a partial dataset
should be audited only for the complete shards that normal scans can read.

Registry layout:

```text
registry/
  datasets.parquet
  raw_files.parquet
```

`datasets.parquet` is rebuilt by `Store.datasets(refresh=True)` and can be
filtered with `layer`, `mission`, `instrument`, `product`, `dataset_version`,
`schema_version`, `status`, `time_range`, `created_after`, or
`created_before`. The `time_range` filter uses half-open interval overlap
against each dataset's `start` and `stop` coverage. Created-at filters use the
half-open interval `[created_after, created_before)`. Registry rows also
include `version`, `schema_version`, `status`, and `created_at` copied from each
manifest.

`raw_files.parquet` is rebuilt by `Store.raw_files(refresh=True)` from raw
sidecar manifests and can be filtered with `mission`, `provider`, `filename`,
`provider_path`, `data_version`, `acquired_after`, or `acquired_before`.
Acquired-at filters use the half-open interval `[acquired_after,
acquired_before)`. Rows include provider path, filename, version, checksum, and
acquisition time.
