# Project, View, And Case

SOPRAN separates the data tree from analysis context.

| Object | Role |
| --- | --- |
| `Store` | Physical storage for raw files, download cache, normalized parquet, features, and registries |
| `Project` | Analysis environment: selected `Store`, artifact root, defaults, and project config |
| `View` | Temporary lens with time, region, frame, cache, and backend overrides |
| `Case` | A saved `View` for a named event, figure, or reproducible workflow |

The `Project` data tree shows what data exist.

```python
project = spn.Project("projects/lunar_wake", store=store)

project.kaguya.esa1.counts.info()
project.kaguya.esa1.counts.schema()
```

## Explore Through A View

Use `View` while changing time ranges interactively.

```python
view = project.view(time=spn.day("2008-02-01"), frame="SSE")
view.kaguya.esa1.counts.plot()

zoom = view.with_time("2008-02-01T03:00:00", "2008-02-01T04:00:00")
zoom.kaguya.esa1.counts.plot()
```

`View` keeps `selection` separate from execution `context`.

| Layer | Examples | Meaning |
| --- | --- | --- |
| selection | `time`, `region`, `mission`, `instrument`, `product`, `quality` | What to extract |
| context | `frame`, `cache`, `download`, `backends`, `spice_kernels`, `time_scale` | How to process it |

Backends default to `auto`. SOPRAN chooses libraries such as `spiceypy` or
`spacepy` where appropriate. Pin a backend only when a study needs it.

## Cases And sopran.toml

Save a useful `View` as a named `Case`.

```python
project.save_case("wake_20080201", zoom)
case = project.case("wake_20080201")
```

```toml
[defaults]
frame = "SSE"
cache = true

[cases.wake_20080201]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"

[cases.wake_20080201.region]
body = "moon"
lon = [120, 160]
lat = [-45, -10]
lon_domain = "0_360"
```

## Use Through A Case

```python
case.kaguya.esa1.counts.load()
case.artemis.p1.fgm.magnetic_field.plan()

dem = case.moon.dem.plan(source="lro.lola.dem_118m")
shadow = case.moon.shadow.plan(dem=dem)
```

For a temporary time change from a saved case, derive a `View`.

```python
case.with_time("2008-02-01T03:00:00", "2008-02-01T04:00:00").kaguya.esa1.counts.plot()
```

Pass `context=case` or `context=view` to preserve analysis provenance in plots,
features, and artifacts.
