# Pipeline

`Pipeline` is a lazy batch API for download, decode, normalize, quicklook, and
parquet writes.

```text
source -> download -> decode -> normalize -> select -> quicklook -> write
```

```python
pipe = (
    kg.esa1.counts.pipeline(time)
    .download()
    .decode()
    .normalize()
    .quicklook("counts", frame="SSE")
    .write("kaguya.esa1.counts", layer="normalized")
)
```

## Execution

| Call | Purpose |
| --- | --- |
| `pipe.plan()` | Inspect the execution plan |
| `pipe.run(dry_run=True)` | Check output shape without executing |
| `pipe.run()` | Execute |
| `pipe.run(mode="append")` | Append shards |
| `pipe.run(mode="replace")` | Explicitly replace output |
| `pipe.run(resume=True)` | Reuse completed shards |

```python
plan = pipe.plan()
result = pipe.run(dry_run=True)
print(result)
```

## Read From Store

```python
frame = (
    kg.esa1.counts.pipeline(time)
    .from_normalized()
    .collect()
)
```

## Execution Backend

Build a `Pipeline` from a data endpoint with `pipeline(time)`. Its source's
`PipelineBackend` executes scan, stream and run. KAGUYA PACE (`kg.esa1` and the
other sensors) has a backend, implemented in `sopran.missions.kaguya.pipeline`.
Endpoints without one (such as LRS) and hand-built pipelines raise `PipelineError`
when executed. A new source subclasses `PipelineBackend` and overrides only the
operations it supports; `stream(partition="all" | "day")` falls back to
`scan_pipeline`.

Backend coverage is tracked in [Status](../reference/status.md).
