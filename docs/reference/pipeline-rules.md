# Pipeline Rules

- Attribute access does not execute.
- Stage builders return a new `Pipeline`.
- `write()` declares an output; it does not write until `run()`.
- `quicklook()` declares preview artifacts; it does not render until `run()`.
- `run(dry_run=True)` returns a planned `PipelineResult` without executing
  stages; its plan can be inspected with `to_dict()` or `str(result)`.
- `run()` fails on existing shards unless `mode="append"` or `mode="replace"`
  is explicit.
- `run(resume=True)` may skip execution when the output catalog is already
  complete for the requested range.
- `resume=True` is mutually exclusive with `mode="append"` and
  `mode="replace"`.
- `scan()` returns a Polars `LazyFrame` when possible.
- `collect()` is a thin materialization helper over `scan().collect()`.
- `stream(partition="all")` yields one collected frame in the generic fallback.
- `stream(partition="day")` groups collected scan rows by the `time` column.
- `stream(partition="shard")` and `stream(partition="orbit")` require a mission
  backend implementation.
- `run()` returns a `PipelineResult.run_id` that identifies the execution.
- Dataset-writing pipeline backends should write manifest provenance with the
  pipeline run ID, source, stage names, run mode, time range, output target, and
  selected variable/product.
- Dataset-writing pipeline backends should write a structured log under the
  dataset `logs/` directory and expose it through `PipelineResult.log_path`.
  The log should include run mode, status, start/finish timestamps, elapsed
  seconds, declared stage parameters, per-stage row/shard counts, shard rows,
  and total row count.
- Quicklook-producing backends should write the same run ID into quicklook
  metadata so preview artifacts can be traced to the dataset-writing run.

Variable selection should use `select_variables(...)`; variable names should not
become pipeline stage methods.
