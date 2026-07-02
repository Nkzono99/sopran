# Store Layout

```text
sopran_data/
  raw/
  normalized/
  features/
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
shard files.

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
stages, run mode, time range, output dataset/layer, and selected variable.
`Store.dataset_source_files(...)` resolves the manifest `source_files` list back
to raw sidecar records. `Store.verify_dataset(...)` checks both dataset shard
checksums and raw input checksums.

Registry layout:

```text
registry/
  datasets.parquet
  raw_files.parquet
```

`datasets.parquet` is rebuilt by `Store.datasets(refresh=True)` and can be
filtered with `layer`, `mission`, `instrument`, `product`, `dataset_version`,
`schema_version`, or `status`. Registry rows also include `version`,
`schema_version`, `status`, and `created_at` copied from each manifest.

`raw_files.parquet` is rebuilt by `Store.raw_files(refresh=True)` from raw
sidecar manifests and can be filtered with `mission` or `provider`. Rows include
provider path, filename, version, checksum, and acquisition time.
