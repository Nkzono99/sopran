# Configuration

Project configuration lives in `sopran.toml` in an analysis workspace:

```toml
[defaults]
frame = "SSE"
cache = true

[cases.example]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"
```

Environment variables:

- `SOPRAN_DATA_ROOT`: default store root.
- `SOPRAN_CACHE_ROOT`: optional cache root override.
