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
```

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
results by day, and can write a Matplotlib PNG quicklook plus JSON metadata for
KAGUYA ESA1 pipeline runs. Quicklook metadata records the pipeline source,
stage names, time range, output dataset/layer, selected variable, backend, and
artifact list.

KAGUYA ESA1 pipeline writes also add manifest provenance under
`dataset.json["provenance"]`, including source, stages, run mode, time range,
output dataset/layer, and selected variable.
