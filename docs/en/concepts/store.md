# Store

`Store` owns physical data layout. It is separate from the analysis workspace
represented by `Project`.

```python
store = spn.Store("F:/sopran_data")
```

## Layers

```text
raw files -> decode -> normalized shards -> catalog.parquet -> scan()
                       -> features / databases
                       -> quicklook png/html/json
```

| Layer | Role |
| --- | --- |
| `raw` | Provider files with provider names preserved |
| `normalized` | Instrument values in Polars-friendly parquet |
| `features` | Binning, alignment, and derived metrics |
| `models` | Calibration, estimation, or learned models |
| `databases` | User-defined curated products |

## Dataset Contents

```text
dataset.json      # dataset ID, time coverage, provenance
schema.json       # variables, dims, units, frame
catalog.parquet   # shard path, start/stop, row count, checksum, status
shards/           # parquet files
```

## Common Operations

| Operation | API |
| --- | --- |
| Get a raw root | `store.raw_path("kaguya", "pds3")` |
| Write a raw sidecar | `store.register_raw_file(...)` |
| Build the raw index | `store.raw_files(refresh=True)` |
| Build the dataset index | `store.datasets(refresh=True)` |
| Scan parquet | `store.scan_dataset(dataset_id, layer=...)` |
| Check shard checksums | `record.verify_checksums()` |
| Inspect failed shards | `record.failed_shards()` |
