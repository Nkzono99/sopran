# Configuration

SOPRAN resolves configuration from explicit arguments, session config,
environment variables, project config, user global config, and package
defaults. An analysis workspace can define `sopran.toml`. `spn.view(...)` and
shortcuts such as `spn.kaguya` and `spn.moon` discover the nearest parent
`sopran.toml` from the current directory.

```toml
[project]
artifact_root = "artifacts"

[defaults]
frame = "SSE"
cache = true

[store]
data_root = "data"
cache_root = "cache"

[backends]
frames = "spiceypy"
plot = "matplotlib"

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
| Project root | Explicit argument > session config > nearest parent `sopran.toml` > user global `[project].root` > current directory |
| Store root | Explicit argument > session config > environment variable > project `[store]` > user global `[store]` > default |
| Artifact root | Explicit argument > session config > `SOPRAN_ARTIFACT_ROOT` > project `[project]` > user global `[project]` > project root |
| Defaults | Explicit override > session config > project `[defaults]` > user global `[defaults]` > package default |
| Backend | Explicit override > session config > project `[backends]` > user global `[backends]` > `auto` |
| Case region | `[cases.<name>.region]` > `[defaults.region]` |

Normal use does not require backend selection. With `auto`, SOPRAN selects
libraries such as `spiceypy` or `spacepy` based on the operation. Pin a backend
only when a study needs it.

## Session Config

Use `spn.config.use(...)` when a notebook should change the defaults used by
`spn.kaguya`, `spn.view()`, and `spn.Store()` without editing a file.

```python
import sopran as spn

spn.config.use(store="F:/sopran_data", download="never")

time = spn.day("2008-02-01")
spn.kaguya.esa1.energy_flux.plot(time, log_color=True)

with spn.config.using(store="F:/other_data"):
    spn.kaguya.esa1.counts.load(time)
```

`spn.Store("F:/sopran_data")` only creates a store object. It does not change
the store used by `spn.kaguya`; use `spn.config.use(store=...)` for that.
Persist user defaults with `spn.config.save_user(...)`.

```python
spn.config.save_user(store="F:/sopran_data", download="missing")
```

## User Global Config

When no project directory is used, `spn.view(...)`, `spn.kaguya`, `spn.moon`,
`spn.Store()`, and `spn.Kaguya()` read user global config. Set `SOPRAN_CONFIG`
to choose the path.
Without it, SOPRAN uses the platform user config directory. If
`~/.sopran/config.toml` exists and the platform path does not, SOPRAN reads that
legacy path.

```toml
[store]
data_root = "F:/sopran_data"
cache_root = "F:/sopran_cache"

[defaults]
frame = "SSE"
cache = true
download = "missing"

[backends]
frames = "spiceypy"
plot = "matplotlib"
```

```python
import sopran as spn

view = spn.view(time=spn.day("2008-02-01"))
view.kaguya.esa1.counts.plot()

counts = spn.kaguya.esa1.counts.load(spn.day("2008-02-01"))
```

## Environment Variables

| Variable | Role |
| --- | --- |
| `SOPRAN_CONFIG` | User global config path |
| `SOPRAN_DATA_ROOT` | Default data root for `Store()` and `Project(...)` |
| `SOPRAN_CACHE_ROOT` | Default cache root. Falls back to `<data root>/cache` |
| `SOPRAN_ARTIFACT_ROOT` | Default output root for `Project.save(...)` |
| `SOPRAN_DOWNLOAD_MODE` | Mission download policy. Defaults to `missing` |
| `SOPRAN_OFFLINE` | Truthy values force the default download policy to `never` |

Explicit roots such as `spn.Store("F:/data")` take precedence over environment
variables. When `spn.Project("workspace")` creates a store automatically,
environment variables take precedence over `[store]`.
