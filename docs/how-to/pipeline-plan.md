# Plan A Pipeline

Build a pipeline without executing it:

```python
pipe = (
    kg.esa1.pipeline(time)
    .download()
    .decode()
    .normalize()
    .select_variables("counts")
    .write("kaguya.esa1.counts", layer="normalized")
)

plan = pipe.plan()
result = pipe.run(dry_run=True)
```

Use `scan()` or `collect()` when the input already exists in the store:

```python
frame = (
    kg.esa1.pipeline(time)
    .from_normalized()
    .select_variables("counts")
    .collect()
)
```
