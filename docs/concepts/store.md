# Store

`Store` owns physical data layout. It is separate from the analysis workspace
managed by `Project`.

```python
store = spn.Store("F:/sopran_data")
```

The main layers are:

```text
raw          provider files, naming preserved
normalized   decoded instrument quantities in scan-friendly formats
features     derived analysis products
models       learned models and calibration-derived artifacts
databases    user or project-defined logical products
cache        local cache for transient work
```

Normalized, features, models, and database datasets use:

```text
dataset.json
schema.json
catalog.parquet
shards/
```

`catalog.parquet` records shard path, start/stop coverage, row count, checksum,
status, and schema version. `dataset.json` records dataset ID, layer, mission,
instrument, product, dataset content version, schema version, dataset status,
creation time, time coverage, source dataset IDs, source files, producer,
software versions, partitioning, and optional provenance. `schema.json` also
records the same schema version.

`source_datasets` tracks dataset IDs that were used to build derived products.
When a dataset is appended, source dataset IDs are merged without duplicates.

`parameters` in `dataset.json` stores JSON-serializable generation settings such
as binning choices, quality masks, coordinate transform options, and feature
extraction arguments.

`partitioning` records Parquet partition columns such as `year`, `month`, and
`day`. `version` is the dataset content version and defaults to `"1"`.

`Store.write_parquet_dataset(..., provenance={...})` writes a structured
provenance object into `dataset.json`. Pipeline backends should use this for the
pipeline source, stage list, mode, time range, and selected product or variable.
For a single loaded variable, prefer `SopranArray.write_parquet(store, ...)`.
It delegates to `Store.write_parquet_dataset(...)` while carrying the loaded
array's `VariableSchema`, time coverage, source files, and table conversion.
Pass `context=case`, `context=loaded`, or a plain metadata mapping when the
dataset manifest should record the analysis case or loaded-object provenance.
`DatasetRecord.verify_checksums()` compares catalog checksums with current shard
files. By default it audits every catalog shard; use
`DatasetRecord.verify_checksums(status="complete")` to verify the same shard set
that `scan()` reads.
`DatasetRecord.update_shard_status(path, status)` updates a catalog shard status
to `pending`, `running`, `complete`, `failed`, or `skipped`.
`DatasetRecord.shards(status=...)` lists catalog shards, and
`DatasetRecord.failed_shards()` returns the failed subset for resume and audit
workflows.
`DatasetRecord.scan()` reads only `complete` catalog shards so failed or skipped
shards remain visible for audit without breaking normal analysis scans.
`DatasetRecord.replace_shard(path, frame=..., time_coverage=...)` overwrites one
cataloged shard and refreshes its checksum, row count, time coverage, and status.
`Store.dataset_source_files(...)` resolves `dataset.json["source_files"]` into
`RawFileRecord` objects so raw input checksums can be verified.
`Store.verify_dataset(...)` checks both dataset shard checksums and raw input
checksums for a dataset. Pass `shard_status="complete"` to restrict the shard
checksum audit to the same complete shard set used by `scan()`.

Raw files are not renamed by SOPRAN. `Store.register_raw_file(...)` writes a
sidecar manifest next to the raw file, named `<filename>.sopran.json`, with the
relative raw path, filename, mission, provider, provider path, data version,
download URL, acquisition time, checksum, and byte size.
The returned `RawFileRecord` can verify that the current file still matches the
recorded checksum.

`Store.raw_files(refresh=True)` scans those sidecars and writes
`registry/raw_files.parquet`. It can be filtered by `mission`, `provider`,
`filename`, `provider_path`, `data_version`, `acquired_after`, or
`acquired_before`. The acquired-at filters use `[acquired_after,
acquired_before)`.
Use `Store.raw_file(...)` to reopen a `RawFileRecord` from a raw path and its
sidecar manifest.

## Dataset Registry

`Store.datasets(refresh=True)` scans dataset manifests and writes
`registry/datasets.parquet`. Later calls read that registry unless `refresh` is
requested again:

```python
index = store.datasets(refresh=True)
kaguya_features = store.datasets(layer="features", mission="kaguya")
adopted = store.datasets(status="adopted")
versioned = store.datasets(dataset_version="2026.07", schema_version="0.1")
overlapping = store.datasets(time_range=spn.period("2008-02-01", "2008-02-02"))
recent = store.datasets(
    created_after="2026-07-02T00:00:00Z",
    created_before="2026-07-03T00:00:00Z",
)
```

The registry records dataset ID, layer, mission, instrument, product, schema
version, dataset content version, dataset status, creation time, time coverage,
and dataset path. A `time_range` filter returns datasets whose time coverage
overlaps the requested half-open interval. `created_after` and
`created_before` filter manifest creation times as `[created_after,
created_before)`. It is an index over manifests; `dataset.json`, `schema.json`,
and per-dataset `catalog.parquet` remain the source of truth.

## Database Products

User-defined products live under the `databases` layer:

```python
db = store.database("lunar_wake", create=True)
product = db.register_product(
    name="event_table",
    schema=kg.esa1.schema(),
    description="hand-curated lunar wake events",
)

pipe.write(db.product("event_table"))
```

Registered products can be listed later from `database.json`:

```python
products = db.products()
products[0].name
products[0].dataset_id
products[0].info()
products[0].manifest()
products[0].schema()
lazy = products[0].scan()
```

Writing an alignment result directly to `db.product("wake_context")` also
registers that product in `database.json`:

```python
features.write_dataset(
    db.product("wake_context"),
    description="aligned wake context features",
)
```

When a reusable feature table is already stored in the `features` layer, keep
the physical dataset there and adopt it into a project database as a reference:

```python
features = aligned.write_dataset(store, "analysis.wake_context", context=case)
db.adopt_dataset(features, description="aligned wake context features")
lazy = db.products()[0].scan()
```

The feature dataset manifest records the alignment parameters and, when
`context=case` is passed, the project case metadata that produced the table.
