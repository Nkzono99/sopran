# Pipeline Rules

- Attribute access does not execute.
- Stage builders return a new `Pipeline`.
- `write()` declares an output; it does not write until `run()`.
- `quicklook()` declares preview artifacts; it does not render until `run()`.
- `run()` fails on existing shards unless `mode="append"` or `mode="replace"`
  is explicit.
- `scan()` returns a Polars `LazyFrame` when possible.
- `collect()` is a thin materialization helper over `scan().collect()`.
- `stream(partition="all")` yields one collected frame in the generic fallback.
- `stream(partition="day")` groups collected scan rows by the `time` column.
- `stream(partition="shard")` and `stream(partition="orbit")` require a mission
  backend implementation.
- Dataset-writing pipeline backends should write manifest provenance with the
  pipeline source, stage names, run mode, time range, output target, and selected
  variable/product.

Variable selection should use `select_variables(...)`; variable names should not
become pipeline stage methods.
