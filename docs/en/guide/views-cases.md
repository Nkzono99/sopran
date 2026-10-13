# Time, Regions, And Cases

This page specifies time ranges and regions, the `View` that binds them, the `Project` workspace, and named `Case` conditions.
For the workflow first, read [Reproducible Analysis](../start/reproducible.md).

## Time ranges are half-open

A SOPRAN time range (`TimeRange`) includes its start and excludes its stop, so that concatenating daily shards
never counts a boundary sample twice.

```python
spn.period("2008-02-01T03:00", "2008-02-01T04:00")
spn.day("2008-02-01")      # 2008-02-01 00:00 up to 2008-02-02 00:00
spn.month("2008-02")
spn.year("2008")
```

ISO 8601 strings and `datetime` objects are accepted. Times without a time zone are UTC.
A `TimeRange` has `start` and `stop` (UTC `datetime`) and the strings `start_iso` and `stop_iso`.

## Regions carry their longitude convention

```python
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")

region.crosses_lon_boundary        # True (crosses 0/360)
region.contains(355, 0)            # True
region.to_lon_domain("-180_180")   # the same Region with longitudes in -180..180
```

Longitudes default to east-positive 0–360, latitudes to planetocentric. Change them with `lon_domain`, `lon_direction`, and `lat_type`.
How Moon maps use these conventions is in [Moon Maps](../data/moon/index.md).

## View

A `View` is an immutable bundle of period, region, and processing conditions.

```python
view = spn.view(
    time=spn.day("2008-02-01"),
    region=spn.Region(lon=(120, 160), lat=(-45, -10), body="moon"),
    frame="SSE",
    download="never",
)
```

| Kind | Argument | Effect |
|---|---|---|
| Selection | `time` (or `start` and `stop`) | Default time range of endpoints |
| Selection | `region` | Default region of Moon maps |
| Selection | `mission`, `instrument`, `product`, `quality` | Recorded as analysis conditions |
| Processing | `download` | Download policy of the missions |
| Processing | `spice_kernels`, `time_scale`, `backend` | Used by the `FrameContext` from `view.frame_context()` |
| Processing | `frame`, `cache` | Recorded as analysis conditions |

`view.kaguya`, `view.artemis`, `view.omni`, and `view.moon` are real `spn.Kaguya` (and so on) objects.
Methods use `view.time` when the time is omitted. Registered sources are also available as `view.source("kaguya")`.

Create a new `View` to change conditions.

```python
view.with_time("2008-02-01T03:00", "2008-02-01T04:00")
view.with_region(None)
view.with_context(frame="GSE", download="missing")
```

`spn.view(...)` uses the first `sopran.toml` found from the current directory upward as the Project settings.
The short entry points such as `spn.kaguya` do the same.

## Project

A `Project` is the working directory of an analysis topic.

```python
project = spn.Project("projects/lunar_wake")
project = spn.Project("projects/lunar_wake", store=spn.Store("/path/to/sopran_data"))
```

| Item | Meaning |
|---|---|
| `project.root` | Working directory that holds `sopran.toml` |
| `project.store` | Store in use; when omitted, resolved as in [Configuration](configuration.md) |
| `project.artifact_root` | Where `project.save()` writes |
| `project.view(...)` | A `View` with this Project's defaults |
| `project.kaguya` etc. | Mission objects without a time range |

## Case

A `Case` is a named set of analysis conditions saved in `sopran.toml`.

```toml
[defaults]
frame = "SSE"

[defaults.region]           # default for Cases without a region
body = "moon"
lon = [120, 160]
lat = [-45, -10]

[cases.wake_20080201]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"

[cases.wake_20080201.context]   # frame, cache, download, quality, time_scale
download = "never"

[cases.wake_20080201.region]
body = "moon"
lon = [130, 150]
lat = [-30, -20]
```

```python
case = project.case("wake_20080201")
case.kaguya.esa1.counts.load()
case.with_time("2008-02-01T03:00", "2008-02-01T04:00")   # returns a View
case.view                                                # a View with the Case's conditions
```

Each key resolves from the Case value, then the session settings, then the Project's `[defaults]`, then the user settings.
`download` is the exception: session settings and environment variables (such as `SOPRAN_OFFLINE`) outrank the Case value ([Configuration](configuration.md#precedence)).
`project.case(name, start=..., stop=...)` creates a Case on the spot without writing to `sopran.toml`.

`project.save_case(name, view)` appends the view's period, region, and processing conditions to `sopran.toml`
and writes the same content to `cases/<name>.json`. It stops if the Case exists. Overwriting is not implemented,
so edit `sopran.toml` to change a saved Case.

## Recording provenance

`context=` is the common argument that writes analysis conditions into figures, artifacts, and datasets.

| Call | Recorded in |
|---|---|
| `plot(..., context=case)`, `quicklook(..., context=case)` | Figure JSON |
| `project.save(array, "interim/name", context=case)` | NetCDF and a JSON with the same name |
| `write_parquet(..., context=case)`, `write_dataset(..., context=case)` | Store manifest |

`context` accepts a `Case`, a `View`, an object with `metadata()` or `to_metadata()`, or a JSON-ready dict.
A `Case` contributes its name, Project location, Store location, time range, region, and defaults.

`project.save(value, name)` writes anything with `to_xarray()` as NetCDF under `artifact_root`
and records the time range, sources, and relative path in JSON. The Project holds temporary outputs;
data reused across analyses belongs in the [Store](store.md).
