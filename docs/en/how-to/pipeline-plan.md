# Plan A Pipeline

## Checklist

- Choose the source.
- Declare stages.
- Choose the output dataset ID.
- Run `dry_run=True` first.

```python
pipe = (
    kg.esa1.counts.pipeline(time)
    .download()
    .decode()
    .normalize()
    .quicklook("counts", frame="SSE", aggregation={"mode": "native"})
    .write("kaguya.esa1.counts", layer="normalized")
)
```

## Inspect Before Running

```python
plan = pipe.plan()
dry = pipe.run(dry_run=True)

plan.to_dict()
dry.to_dict()
print(dry)
```

## Inspect After Running

```python
result = pipe.run()
result.to_dict()
```

Use `from_normalized()` when the data already exists in the store.

```python
frame = (
    kg.esa1.counts.pipeline(time)
    .from_normalized()
    .collect()
)
```
