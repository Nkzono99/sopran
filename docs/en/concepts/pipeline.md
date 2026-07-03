# Pipeline

`Pipeline` is a lazy batch API for download, decode, normalize, quicklook, and
parquet writes.

```text
source -> download -> decode -> normalize -> select -> quicklook -> write
```

```python
pipe = (
    kg.esa1.pipeline(time)
    .download()
    .decode()
    .normalize()
    .select_variables("counts")
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
    kg.esa1.pipeline(time)
    .from_normalized()
    .select_variables("counts")
    .collect()
)
```

Backend coverage is tracked in [Status](../reference/status.md).
