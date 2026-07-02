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
databases    user or project-defined logical products
cache        local cache for transient work
```

Normalized, features, and database datasets use:

```text
dataset.json
schema.json
catalog.parquet
shards/
```

`catalog.parquet` records shard path, start/stop coverage, row count, checksum,
status, and schema version. `dataset.json` records dataset ID, layer, mission,
instrument, product, schema version, dataset status, creation time, time
coverage, source dataset IDs, source files, producer, software versions, and
optional provenance. `schema.json` also records the same schema version.

`source_datasets` tracks dataset IDs that were used to build derived products.
When a dataset is appended, source dataset IDs are merged without duplicates.

`parameters` in `dataset.json` stores JSON-serializable generation settings such
as binning choices, quality masks, coordinate transform options, and feature
extraction arguments.

`Store.write_parquet_dataset(..., provenance={...})` writes a structured
provenance object into `dataset.json`. Pipeline backends should use this for the
pipeline source, stage list, mode, time range, and selected product or variable.

## Dataset Registry

`Store.datasets(refresh=True)` scans dataset manifests and writes
`registry/datasets.parquet`. Later calls read that registry unless `refresh` is
requested again:

```python
index = store.datasets(refresh=True)
kaguya_features = store.datasets(layer="features", mission="kaguya")
```

The registry records dataset ID, layer, mission, instrument, product, schema
version, dataset status, creation time, time coverage, and dataset path. It is
an index over manifests; `dataset.json`, `schema.json`, and per-dataset
`catalog.parquet` remain the source of truth.

## Database Products

User-defined products live under the `databases` layer:

```python
db = store.database("lunar_wake")
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
```
