# Plan A Pipeline

Build a pipeline without executing it:

```python
pipe = (
    kg.esa1.pipeline(time)
    .download()
    .decode()
    .normalize()
    .select_variables("counts")
    .quicklook(
        "counts",
        frame="SSE",
        aggregation={"mode": "native"},
    )
    .write("kaguya.esa1.counts", layer="normalized")
)

plan = pipe.plan()
result = pipe.run(dry_run=True)
```

Inspect the plan in structured or readable form:

```python
plan.to_dict()
print(result)
```

The dry-run result does not execute pipeline stages. It reports the source,
time range, stage list, and output target.

For KAGUYA ESA1, `run()` writes quicklooks under
`<dataset>/preview/<name>.png` with a matching JSON metadata file. Use
`formats=("png", "html")` when a static HTML report should be written too.

Use `scan()` or `collect()` when the input already exists in the store:

```python
frame = (
    kg.esa1.pipeline(time)
    .from_normalized()
    .select_variables("counts")
    .collect()
)
```
