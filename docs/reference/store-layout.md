# Store Layout

```text
sopran_data/
  raw/
  normalized/
  features/
  databases/
  registry/
  cache/
```

Dataset layout:

```text
dataset.json
schema.json
catalog.parquet
shards/
```

Catalog rows currently include:

- `path`
- `schema_version`
- `start`
- `stop`
- `row_count`
- `checksum`
- `status`

The catalog is the boundary for append, replace, and lazy scan operations.

`dataset.json` includes a `software` object with the SOPRAN package version and
Python runtime version. It may also include a `provenance` object. The first
supported producer is the KAGUYA ESA1 pipeline, which records pipeline source,
stages, run mode, time range, output dataset/layer, and selected variable.

Registry layout:

```text
registry/
  datasets.parquet
```

`datasets.parquet` is rebuilt by `Store.datasets(refresh=True)` and can be
filtered with `layer`, `mission`, `instrument`, or `product`. Registry rows also
include `schema_version` copied from each manifest.
