# Write Normalized Parquet

```python
esa1 = kg.esa1.load(time)

record = esa1.write_parquet(
    store,
    variable="counts",
    reduce_look="sum",
)
```

The dataset can be scanned later:

```python
frame = record.scan().collect()
```

Pipeline writes prevent accidental overwrite by default:

```python
pipe.run()
pipe.run(mode="append")
pipe.run(mode="replace")
```

Use `resume=True` when a completed catalog should be reused instead of failing
on the existing shard:

```python
result = pipe.run(resume=True)
```

For KAGUYA ESA1, the current resume behavior skips execution only when the
existing catalog is complete for the requested time range.
