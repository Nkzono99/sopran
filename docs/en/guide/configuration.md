# Configuration

The main things to configure are where data is stored (the Store) and the download policy.
Settings come from the session, the user config file, environment variables, and the Project `sopran.toml`; explicit arguments always win.

## Choose a storage location first

With nothing configured, `spn.kaguya`, `spn.Kaguya()`, and `spn.Store()` all use `sopran_data/` under the Project root.
Without a `sopran.toml`, the Project root is the current directory, so each working directory would get its own Store.
Set the storage location first with one of these:

| Method | Scope | How |
|---|---|---|
| Session setting | The running Python process | `spn.config.use(store="/path/to/sopran_data")` |
| User config file | Every process of that user | `spn.config.save_user(store="/path/to/sopran_data")` |
| Environment variable | Processes that inherit it | `SOPRAN_DATA_ROOT=/path/to/sopran_data` |
| Project `sopran.toml` | Inside that Project | `[store] data_root = "data"` |

## Session settings

```python
import sopran as spn

spn.config.use(store="/path/to/sopran_data", download="never")

with spn.config.using(store="/path/to/other_data"):
    spn.kaguya.esa1.counts.load(time)     # another Store only inside this block

spn.config.reset()                        # clear the session settings
```

`use` and `using` accept `store` (or `data_root` and `cache_root`), `project`, `artifact_root`, `download`,
`frame`, `cache`, and `backends`. They never modify config files.

`spn.Store("/path")` only creates a Store object; it does not change the Store used by `spn.kaguya`.
Use `spn.config.use(store=...)` to change it for the short entry points.

## User config file

`spn.config.save_user(...)` saves the same arguments to the user config file. You can also edit the file directly.

| OS | Location |
|---|---|
| Windows | `%APPDATA%\sopran\config.toml` |
| macOS | `~/Library/Application Support/sopran/config.toml` |
| Linux | `$XDG_CONFIG_HOME/sopran/config.toml` (or `~/.config/sopran/config.toml`) |

`SOPRAN_CONFIG` selects a specific file. If the file above does not exist and the legacy
`~/.sopran/config.toml` does, the legacy file is read. Relative paths resolve against the config file's directory.

```toml
[store]
data_root = "/path/to/sopran_data"
cache_root = "/path/to/sopran_cache"   # defaults to <data_root>/cache

[defaults]
download = "missing"
frame = "SSE"
cache = true

[backends]
frames = "spiceypy"
plot = "matplotlib"

[project]
root = "/path/to/default_project"       # default Project for the short entry points
artifact_root = "artifacts"
```

## Project `sopran.toml`

`spn.view(...)` and the short entry points such as `spn.kaguya` use the first `sopran.toml` found from the current directory upward
as the Project settings. Relative paths resolve against the Project directory.

```toml
[project]
artifact_root = "artifacts"

[store]
data_root = "data"
cache_root = "cache"

[defaults]
frame = "SSE"
download = "never"

[defaults.region]
body = "moon"
lon = [350, 10]
lat = [-5, 5]
lon_domain = "0_360"

[backends]
frames = "spiceypy"

[cases.example]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"
```

The `[cases.*]` format is described in [Time, Regions, And Cases](views-cases.md#case).

## Environment variables

| Variable | Role |
|---|---|
| `SOPRAN_CONFIG` | Path of the user config file |
| `SOPRAN_DATA_ROOT` | Store root |
| `SOPRAN_CACHE_ROOT` | Cache root; defaults to `<Store root>/cache` |
| `SOPRAN_ARTIFACT_ROOT` | Where `project.save()` writes |
| `SOPRAN_DOWNLOAD_MODE` | Default download policy |
| `SOPRAN_OFFLINE` | When `1`, `true`, `yes`, or `on`, the default download policy becomes `never` |

## Download policy

| Value | Behavior |
|---|---|
| `missing` (default) | Retrieve only source files missing from the Store |
| `never` | No network access. Missing files raise or give empty results, depending on `missing=` |
| `always` | Retrieve again even when files exist |

Set it on mission objects (`spn.Kaguya(download=...)`), on a `View`, or per call (`load(download=...)`).
On machines without outbound network access, such as supercomputer compute nodes, set `SOPRAN_OFFLINE=1`.
Environment variables outrank config files (`sopran.toml`, user config), so the machine stays offline even when a file says
`download = "missing"`. Values set in code (arguments, `spn.config.use`) outrank environment variables.

## Precedence

Earlier entries win.

| Setting | Precedence |
|---|---|
| Store root | argument (`Store(root)`, `store=`) > session > `SOPRAN_DATA_ROOT` > Project `[store]` > user `[store]` > `<Project root>/sopran_data` |
| Cache root | `cache_root` and `SOPRAN_CACHE_ROOT` in the same order as above, otherwise `<Store root>/cache` |
| Project root (short entry points, `spn.view`, `spn.Store()`) | session `project=` > first `sopran.toml` found upward > user `[project].root` > current directory |
| Artifact root | argument > session > `SOPRAN_ARTIFACT_ROOT` > Project `[project]` > user `[project]` > Project root |
| Download | argument (`load`, mission, `View`) > session > `SOPRAN_OFFLINE` > `SOPRAN_DOWNLOAD_MODE` > Case value > Project `[defaults]` > user `[defaults]` > `missing` |
| `frame`, `cache` | argument > session > Project `[defaults]` > user `[defaults]` |
| Backends | argument > session > Project `[backends]` > user `[backends]` > automatic |
| Case region | `[cases.<name>.region]` > `[defaults.region]` |

The Store root and the download policy resolve in the same order whether you use a short entry point such as `spn.kaguya`,
an explicit object such as `spn.Kaguya()`, `spn.Store()`, or a `View` or `Case`.

You normally do not set backends. Coordinate transforms choose one from the source and target frames
([Coordinate Frames](frames.md)).

Invalid values, such as an unknown download policy or a key that should be a table, raise `ConfigError`.
