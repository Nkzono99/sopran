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

Use `only_failed=True` when a later backend should replay only failed shards:

```python
record.update_shard_status("shards/part-000.parquet", "failed")
failed = record.failed_shards()
result = pipe.run(only_failed=True)
```

The current KAGUYA ESA1 implementation records a skip log when the catalog
contains no failed shards. When failed shards exist, it reloads each failed
shard's cataloged time coverage, overwrites the same shard path, refreshes the
catalog checksum, and writes a complete run log with `replayed_shard_count`.
