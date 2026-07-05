# Store

`Store` owns physical data layout. It is separate from the analysis workspace
represented by `Project`.

```python
store = spn.Store("F:/sopran_data")
```

## Root Resolution

When `Store()` receives no explicit root, it reads environment variables.

| Item | Resolution order |
| --- | --- |
| Data root | Explicit argument > `SOPRAN_DATA_ROOT` > `sopran_data` |
| Cache root | Explicit argument > `SOPRAN_CACHE_ROOT` > `<data root>/cache` |

```powershell
$env:SOPRAN_DATA_ROOT = "F:/sopran_data"
$env:SOPRAN_CACHE_ROOT = "F:/sopran_cache"
```

When a store is created through `Project("workspace")`, environment variables take
precedence over `[store]` in `sopran.toml`.

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

## Database Products And Event Catalogs

User-defined tables and curated event lists live in the `databases` layer.
Stable or hand-curated phenomena can use `event_catalog()`. `write_events()`
stores rows with columns such as `time_start`, `time_stop`, `phenomenon`, and
`detector`; `counts()` aggregates event rows by day or month.

```python
catalog = store.event_catalog("lunar_wake", create=True)
catalog.write_events(events, time_coverage=spn.month("2008-02"), overwrite=True)
monthly = catalog.counts(freq="month", by=("instrument",))
```

Use endpoint `coverage()` for data availability and finite sample counts. This
is not an interpreted event catalog; it is an availability summary stored in
the `features` layer.

```python
coverage = kg.esa1.energy_flux.coverage(time, freq="day", cache="use")
```
