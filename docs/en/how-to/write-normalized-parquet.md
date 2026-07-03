# Write Normalized Parquet

## Checklist

- Raw files exist under `Store.raw`.
- The target variable is selected.
- The overwrite/append/dry-run policy is clear.
- The partitioning scheme is clear.

## From Loaded Data

```python
esa1 = kg.esa1.load(time)

record = esa1.write_parquet(
    store,
    variable="counts",
    reduce_look="sum",
)

frame = record.scan().collect()
```

## With Pipeline

```python
pipe = (
    kg.esa1.pipeline(spn.period("2008-01-01", "2008-01-03"))
    .decode()
    .select_variables("counts")
    .write("kaguya.esa1.counts", layer="normalized", partition="day")
)

pipe.run(dry_run=True)
result = pipe.run()
```

## Modes

| Mode | Use |
| --- | --- |
| default | Stop conservatively if a dataset exists |
| `append` | Add shards |
| `replace` | Explicitly replace output |
| `resume=True` | Reuse completed catalog state |
| `only_failed=True` | Replay failed shards |

Resume details are tracked in [Status](../reference/status.md).
