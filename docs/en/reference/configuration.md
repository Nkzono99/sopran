# Configuration

An analysis workspace can define `sopran.toml`.

```toml
[project]
artifact_root = "artifacts"

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

## Priority

| Setting | Priority |
| --- | --- |
| Store root | Explicit argument > environment variable > `[store]` > default |
| Artifact root | Explicit argument > `SOPRAN_ARTIFACT_ROOT` > `[project]` > project root |
| Case region | `[cases.<name>.region]` > `[defaults.region]` |

## Environment Variables

| Variable | Role |
| --- | --- |
| `SOPRAN_DATA_ROOT` | Default data root for `Store()` |
| `SOPRAN_CACHE_ROOT` | Cache root |
| `SOPRAN_ARTIFACT_ROOT` | Default output root for `Project.save(...)` |
| `SOPRAN_DOWNLOAD_MODE` | Mission download policy |
| `SOPRAN_OFFLINE` | Truthy values force the default download policy to `never` |
