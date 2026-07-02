# Configuration

Project configuration lives in `sopran.toml` in an analysis workspace:

```toml
[defaults]
frame = "SSE"
cache = true

[store]
data_root = "data"
cache_root = "cache"

[cases.example]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"

[cases.example.region]
body = "moon"
lon = [350, 10]
lat = [-5, 5]
lon_domain = "0_360"
```

`[cases.<name>.region]` becomes `case.region` as a `spn.Region`. Put the same
keys under `[defaults.region]` when every case should share the same region.

Environment variables:

- `SOPRAN_DATA_ROOT`: default store root.
- `SOPRAN_CACHE_ROOT`: optional cache root override.
- `SOPRAN_DOWNLOAD_MODE`: default mission download policy when not passed explicitly.
- `SOPRAN_OFFLINE`: when truthy, default mission download policy becomes `never`.

When `Project(root)` creates its own `Store`, `[store].data_root` and
`[store].cache_root` are resolved relative to the project root unless they are
absolute paths. Explicit `Store(...)` arguments and environment variables take
priority over project configuration.
