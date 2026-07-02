# Pipeline Rules

- Attribute access does not execute.
- Stage builders return a new `Pipeline`.
- `write()` declares an output; it does not write until `run()`.
- `write(..., partition="day")` declares daily output shards. KAGUYA ESA1 writes
  Hive-style daily parquet paths and records `year`, `month`, and `day`
  partitioning in the manifest.
- `quicklook()` declares preview artifacts; it does not render until `run()`.
- `run(dry_run=True)` returns a planned `PipelineResult` without executing
  stages; its plan can be inspected with `to_dict()` or `str(result)`.
- `run(download="never"|"missing"|"always")` overrides the mission default
  download policy for that execution. KAGUYA ESA1 applies it to normal writes,
  daily partition writes, failed-shard replay, and quicklook input loading.
- `run()` fails on existing shards unless `mode="append"` or `mode="replace"`
  is explicit.
- `run(on_error="fail")` is the default error policy.
- `run(on_error="continue")` lets a backend record failed shards and return a
  partial result; KAGUYA ESA1 records missing-input load failures this way.
- `run(resume=True)` may skip execution when the output catalog is already
  complete for the requested range.
- `resume=True` is mutually exclusive with `mode="append"` and
  `mode="replace"`.
- `run(only_failed=True)` may skip execution when the existing output catalog
  contains no failed shards. KAGUYA ESA1 replays failed shards by overwriting
  the same shard path and refreshing catalog metadata.
- `only_failed=True` is mutually exclusive with `resume=True`, `mode="append"`,
  and `mode="replace"`.
- `scan()` returns a Polars `LazyFrame` when possible.
- `collect()` is a thin materialization helper over `scan().collect()`.
- `stream(partition="all")` yields one collected frame in the generic fallback.
- `stream(partition="day")` groups collected scan rows by the `time` column.
- `stream(partition="shard")` requires a mission backend; KAGUYA ESA1 yields
  complete catalog shards directly.
- `stream(partition="orbit")` requires a mission backend implementation.
- `run()` returns a `PipelineResult.run_id` that identifies the execution.
- Dataset-writing pipeline backends should write manifest provenance with the
  pipeline run ID, source, stage names, run mode, download policy, time range,
  output target, and selected variable/product.
- Dataset-writing pipeline backends should write a structured log under the
  dataset `logs/` directory and expose it through `PipelineResult.log_path`.
  The log should include run mode, download policy, status, start/finish
  timestamps, elapsed seconds, declared stage parameters, per-stage row/shard
  counts, shard rows, and total row count.
- Quicklook-producing backends should write the same run ID and download policy
  into quicklook metadata so preview artifacts can be traced to the
  dataset-writing run.

Variable selection should use `select_variables(...)`; variable names should not
become pipeline stage methods.
