# Pipeline Rules

- Attribute access does not execute.
- Stage builders return a new `Pipeline`.
- `write()` declares an output; it does not write until `run()`.
- `run()` fails on existing shards unless `mode="append"` or `mode="replace"`
  is explicit.
- `scan()` returns a Polars `LazyFrame` when possible.
- `collect()` is a thin materialization helper over `scan().collect()`.

Variable selection should use `select_variables(...)`; variable names should not
become pipeline stage methods.
