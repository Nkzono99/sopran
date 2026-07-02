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
    .quicklook("counts")
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
```

`PipelinePlan.to_dict()` gives a JSON-like execution plan with source, time
range, stage parameters, and output target. `str(pipe.run(dry_run=True))` renders
the same plan as readable text for terminal logs and notebooks.

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
```

The generic fallback supports `partition="all"` and `partition="day"` via
`scan().collect()`. Mission backends can provide `_stream_pipeline(...)` for
true shard, orbit, or provider-native streaming.

The current implementation is intentionally small. It records stage order,
prevents accidental overwrite by default, supports explicit append/replace,
uses parquet catalog shards as the storage boundary, streams collected scan
results by day, issues a `PipelineResult.run_id` for each `run()` call, skips
already complete KAGUYA ESA1 outputs with `run(resume=True)`, and can write a
Matplotlib PNG quicklook plus JSON metadata for KAGUYA ESA1 pipeline runs.
Quicklook metadata records the pipeline run ID, source, stage names, time range,
output dataset/layer, selected variable, backend, and artifact list.

KAGUYA ESA1 pipeline writes also add manifest provenance under
`dataset.json["provenance"]`, including run ID, source, stages, run mode, time
range, output dataset/layer, and selected variable.

Dataset-writing KAGUYA ESA1 runs write a structured log to
`dataset_root/logs/<run_id>.json`; the same path is returned as
`PipelineResult.log_path`. The log records run mode, status, start/finish
timestamps, elapsed seconds, plan fields, stage parameters, shard metadata, and
total row count. The `stages` field records the declared stage list, while
`stage_logs` records status, timestamps, elapsed seconds, row count, and shard
count for each declared stage.

The first resume behavior is conservative: when the existing catalog is
`complete` and the manifest time coverage contains the requested range, KAGUYA
ESA1 returns `PipelineResult.status == "skipped"` and writes a skip log. Failed
or partial shard replay is a later backend feature. `run(only_failed=True)` has
the same conservative first step: when there are no failed shards, it returns a
skipped result and records `failed_shard_count == 0` in the log.
