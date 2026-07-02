# Pipeline

Pipeline is the advanced batch and storage API. It is used for raw download,
decode, normalization, parquet generation, feature generation, database
products, quicklook generation, and future Rust backend stages.

```python
pipe = (
    kg.esa1.pipeline(time)
    .download()
    .decode()
    .normalize()
    .select_variables("counts")
    .quicklook(
        "counts",
        frame="SSE",
        aggregation={"mode": "native"},
    )
    .write("kaguya.esa1.counts", layer="normalized")
)
```

Stages are lazy until an execution method is called:

```python
pipe.plan()
pipe.run(dry_run=True)
pipe.run()
pipe.run(mode="append")
pipe.run(mode="replace")
pipe.run(resume=True)
pipe.run(download="never")
pipe.run(download="always")
```

`PipelinePlan.to_dict()` gives a JSON-like execution plan with source, time
range, stage parameters, and output target. `PipelineResult.to_dict()` also
includes JSON-ready output summaries, including dataset roots, manifest paths
and manifests, or quicklook artifact paths, formats, metadata paths, and
metadata when available.
`str(pipe.run(dry_run=True))` renders the same plan as readable text for
terminal logs and notebooks.

Read existing normalized data with Polars:

```python
lazy = (
    kg.esa1.pipeline(time)
    .from_normalized()
    .select_variables("counts")
    .scan()
)

frame = lazy.collect()
```

Stream scanned data in chunks when downstream code should work incrementally:

```python
for day_frame in pipe.stream(partition="day"):
    process(day_frame)

for shard_frame in pipe.stream(partition="shard"):
    process(shard_frame)
```

The generic fallback supports `partition="all"` and `partition="day"` via
`scan().collect()`. Mission backends can provide `_stream_pipeline(...)` for
true shard, orbit, or provider-native streaming. KAGUYA ESA1 streams catalog
shards directly for `partition="shard"`.

The current implementation is intentionally small. It records stage order,
prevents accidental overwrite by default, supports explicit append/replace,
uses parquet catalog shards as the storage boundary, streams collected scan
results by day, streams KAGUYA ESA1 catalog shards, issues a
`PipelineResult.run_id` for each `run()` call, skips
already complete KAGUYA ESA1 outputs with `run(resume=True)`, records failed
KAGUYA ESA1 shards with `run(on_error="continue")`, writes daily KAGUYA ESA1
parquet shards with `write(..., partition="day")`, accepts
`run(download="never"|"missing"|"always")` to override the mission download
policy for that execution, and can write Matplotlib
PNG/HTML quicklooks plus JSON metadata for KAGUYA ESA1 pipeline runs.
Quicklook metadata records the pipeline run ID, source, stage names, time range,
output dataset/layer, selected variable, backend, artifact list, and optional
`frame` / `aggregation` values declared in the quicklook stage.

KAGUYA ESA1 pipeline writes also add manifest provenance under
`dataset.json["provenance"]`, including run ID, source, stages, run mode, time
range, output dataset/layer, and selected variable.

`write(..., partition="day")` stores KAGUYA ESA1 output under Hive-style paths
such as `shards/year=2008/month=01/day=01/part-000.parquet` and records
`["year", "month", "day"]` in `dataset.json["partitioning"]`.

Dataset-writing KAGUYA ESA1 runs write a structured log to
`dataset_root/logs/<run_id>.json`; the same path is returned as
`PipelineResult.log_path`. The log records run mode, status, start/finish
timestamps, elapsed seconds, plan fields, stage parameters, shard metadata, and
total row count. The `stages` field records the declared stage list, while
`stage_logs` records status, timestamps, elapsed seconds, row count, and shard
count for each declared stage.

The first resume behavior is conservative: when the existing catalog is
`complete` and the manifest time coverage contains the requested range, KAGUYA
ESA1 returns `PipelineResult.status == "skipped"` and writes a skip log.
`run(only_failed=True)` skips when there are no failed shards. When failed
shards exist, KAGUYA ESA1 reloads each failed shard's cataloged time coverage,
overwrites the same shard path, refreshes the catalog checksum, and records
`replayed_shard_count` in the complete run log. Partial shard detection and
repartitioning are later backend features.

`run(on_error="continue")` currently records KAGUYA ESA1 load/write setup
failures, such as missing local raw files in offline mode, as a failed catalog
shard. The structured log uses `status == "partial"`, includes `on_error`, and
records each error with its stage, exception type, and message.
Normal `scan()` calls read only complete shards, so partial results can be
inspected and later replayed without corrupting downstream analysis.
