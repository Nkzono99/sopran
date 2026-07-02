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
and status. `dataset.json` records dataset ID, layer, mission, instrument,
product, time coverage, source files, producer, and optional provenance.

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

The registry records dataset ID, layer, mission, instrument, product, time
coverage, and dataset path. It is an index over manifests; `dataset.json`,
`schema.json`, and per-dataset `catalog.parquet` remain the source of truth.

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
