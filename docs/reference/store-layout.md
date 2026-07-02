# Store Layout

```text
sopran_data/
  raw/
  normalized/
  features/
  databases/
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
- `start`
- `stop`
- `row_count`
- `checksum`
- `status`

The catalog is the boundary for append, replace, and lazy scan operations.
