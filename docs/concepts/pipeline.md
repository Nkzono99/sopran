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

The current implementation is intentionally small. It records stage order,
prevents accidental overwrite by default, supports explicit append/replace,
and uses parquet catalog shards as the storage boundary.
