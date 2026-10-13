# Batch Pipelines

Use `Pipeline` to retrieve and decode days to months of data and save it to the Store as daily Parquet shards.
For a single day in a notebook, `load()` and `write_parquet()` are enough ([Working With Arrays](arrays.md)).

!!! note "Supported sources"
    Only KAGUYA PACE (`esa1`, `esa2`, `ima`, `iea`) currently has a `Pipeline` execution backend.
    Calling `run()`, `scan()`, or `stream()` on endpoints without one, such as LRS, raises `PipelineError`.

## Arrange stages

A `Pipeline` is created from an endpoint's `pipeline(time)`; add stages and execute with `run()` at the end.
Adding stages runs nothing.

```python
time = spn.period("2008-01-01", "2008-01-04")

pipe = (
    spn.kaguya.esa1.energy_flux.pipeline(time)
    .calibrate(calibration="auto")
    .quicklook("esa1_energy_flux")
    .write("kaguya.esa1.energy_flux", layer="normalized", partition="day")
)
```

| Stage | Meaning |
|---|---|
| `download()`, `decode()`, `normalize()` | Make source retrieval, decoding, and normalization explicit |
| `calibrate(...)` | Apply calibration (PACE `energy_flux`) |
| `select_variables(...)` | Choose several variables of an instrument (when built from the instrument's `pipeline()`) |
| `quicklook(name, ...)` | After saving, write PNG and JSON to the dataset's `preview/` |
| `write(dataset_id, layer=..., partition="day")` | Set the output; `partition="day"` writes daily shards |
| `from_normalized()` | Read a dataset already saved in the Store instead of source files |

## Check before running

```python
pipe.plan()                    # inputs, stages, output
result = pipe.run(dry_run=True)
print(result)                  # same result format, nothing executed
```

## Run

```python
result = pipe.run()
result.to_dict()               # status, run ID, output dataset, log path
```

To protect existing datasets, a run stops by default if the output already exists.

| Argument | Behavior |
|---|---|
| `mode="create"` (default) | Stop if the output exists |
| `mode="append"` | Add shards |
| `mode="replace"` | Replace; not supported with PACE daily shards |
| `resume=True` | Reuse completed ranges; do nothing if the whole range is complete |
| `only_failed=True` | Rebuild only failed shards |
| `on_error="continue"` | Continue after a shard fails and record it as `failed` (default `"fail"` stops) |
| `download="never"` | Change the download policy for this run only |

Every run gets a run ID, and the dataset's `logs/<run_id>.json` records start and end times, row counts, and shard counts per stage.
The manifest's provenance also holds the stage list, time range, download policy, and run ID.

## Read saved data

```python
lazy = spn.kaguya.esa1.counts.pipeline(time).from_normalized().scan()      # Polars LazyFrame
frame = spn.kaguya.esa1.counts.pipeline(time).from_normalized().collect()

for day_frame in pipe.stream(partition="day"):
    process(day_frame)
```

`stream` supports `"all"` and `"day"`, and for PACE also `"shard"` for each saved shard.

## Heavy full-period computations

Heavy processing over the full mission, such as model fits, uses separate CLIs designed around daily shards, resuming, and parallel runs.
See [ER Full-Period Batch](../experimental/er-batch.md) for an example.
Adding `Pipeline` support to a new data source is described in [Adding A Data Source](../development/extending.md).
