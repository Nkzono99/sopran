# Storing Data

A `Store` keeps retrieved source files, intermediate data created by SOPRAN, and analysis results you adopt under one root, separated into layers.
It is separate from the `Project` workspace, so several Projects and machines can share one Store.
Choosing its location is described in [Configuration](configuration.md), and directories and file formats in [Store Layout](../reference/store-layout.md).

```python
store = spn.Store("/path/to/sopran_data")
```

## What goes in each layer

| Layer | Contents | Created by |
|---|---|---|
| `raw` | Source files from providers, with provider names and directory structure unchanged | Downloads |
| `normalized` | Standard instrument quantities (counts, energy flux, magnetic field, …) as Parquet | Pipeline, `write_parquet` |
| `features` | Quantities derived by SOPRAN (orbit geometry, pitch-angle spectra, data availability summaries, …) | Caches, `write_parquet` |
| `models` | Calibration and model-fit results | Experimental APIs, `write_parquet` |
| `databases` | Tables adopted per user or research topic (event lists, …) | `store.database`, `store.event_catalog` |
| `cache` | Temporary files that can be regenerated | Internal |
| `registry` | Search indexes | Automatic |

Each file in `raw/` has a sidecar JSON (`<filename>.sopran.json`) with its source URL, checksum, and retrieval time.

## Caching avoids recomputation

Orbit geometry, field-line connection, LRS spectra, pitch-angle spectra, and similar products can be kept in the Store with `cache=`.

| `cache` | Behavior |
|---|---|
| `"use"` (default) | Read a result made with the same arguments if present; otherwise compute and save |
| `"refresh"` | Recompute and overwrite |
| `"never"` | Compute on the spot without saving |

Results go under the dataset in the `features` layer (or similar), in `variants/<variant_id>/` per set of conditions.
`variant_id` is derived from the arguments and the content of the input files, so results made under different conditions never get mixed up.
Results loaded with `missing="empty"` or `"warn"` while some source files were missing are incomplete and are not cached.

## Summarize data availability

Each endpoint's `coverage()` returns a daily or monthly table of observed sample counts and retrieved files.

```python
daily = spn.kaguya.esa1.counts.coverage(spn.month("2008-02"), freq="day")
```

The columns are `sample_count`, `finite_sample_count`, `sample_time_count`, `expected_remote_files`, and
`available_source_files`. The result is saved in the `features` layer as `<dataset>.coverage` and reused.
It summarizes availability only; it is not an interpreted event list.

## Browse the Store

```python
store.datasets(refresh=True)                       # every dataset (Polars)
store.datasets(layer="features", mission="kaguya")
store.raw_files(refresh=True, mission="kaguya")    # source files

lazy = store.scan_dataset("kaguya.esa1.counts", layer="normalized")   # Polars LazyFrame
frame = lazy.filter(...).collect()
```

`store.dataset(dataset_id, layer=...)` returns the dataset record (`DatasetRecord`).

| Task | Call |
|---|---|
| Read completed shards | `record.scan()` |
| Inspect shard status | `record.shards(status="failed")`, `record.failed_shards()` |
| Verify shard checksums | `record.verify_checksums()`, `record.verify_shards()` |
| Verify including input source files | `store.verify_dataset(dataset_id, layer=...)` |
| Rebuild the catalog from sidecars | `record.rebuild_catalog()`, `store.rebuild()` |

## Research-topic databases

Group adopted results per topic in the `databases` layer.

```python
db = store.database("lunar_wake", create=True)
db.register_product(name="event_table", schema=schema, description="hand-curated lunar wake events")
db.adopt_dataset(record, description="aligned context features")   # register an existing dataset without moving it
db.products()
db.product("event_table").scan()
```

`adopt_dataset` adds a dataset that lives in `features` (or another layer) to the database list without moving it.

## Event catalogs

Hand-picked events and detector output can be saved as validated tables with `event_catalog`.

```python
catalog = store.event_catalog("lunar_wake", create=True)
catalog.write_events(events, time_coverage=spn.month("2008-02"), overwrite=True)

monthly = catalog.counts(freq="month", by=("instrument",))
rates = catalog.rates(exposure, freq="day", by=("phenomenon",))
```

`events` is a table with `time_start`, `time_stop`, `mission`, `instrument`, `phenomenon`, `confidence`, `detector`,
and `detector_version` columns. `rates` divides counts by the time the detector could actually decide (`exposure_seconds`)
and keeps periods with zero events as zero. To keep unobserved periods distinct from zero events,
pass the decidable time aggregated separately as `exposure`.

## Moving to another machine

The Store stays in a form that `rsync` can copy as plain files. See [Moving A Store](store-sync.md).
