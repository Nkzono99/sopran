# Project And Case

`Project` represents an analysis workspace. It owns notebooks, scripts, case
configuration, and a shared `Store`.

```python
project = spn.Project("projects/lunar_wake", store=store)
case = project.case("wake_20080201")
```

`sopran.toml` can define case time ranges and defaults:

```toml
[defaults]
frame = "SSE"
cache = true

[store]
data_root = "data"
cache_root = "cache"

[cases.wake_20080201]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"

[cases.wake_20080201.region]
body = "moon"
lon = [120, 160]
lat = [-45, -10]
lon_domain = "0_360"
```

Case objects provide mission and body context:

```python
case.kaguya.esa1.counts.load()
case.artemis.p1.fgm.magnetic_field.plan()
case.moon.dem.plan(source="kaguya.tc.dem", region=case.region)
case.metadata()
```

`case.region` is `None` when no region is configured. Case-specific region
settings override `[defaults.region]`.
`case.metadata()` returns a JSON-ready snapshot of the case name, project root,
store roots, time range, default frame/cache values, defaults, and region
metadata. Use it when a plot, interim artifact, or pipeline run needs to carry
the same analysis context into provenance.

When no explicit `Store` is passed to `Project`, `[store]` paths are resolved
relative to the project root. `SOPRAN_DATA_ROOT` and `SOPRAN_CACHE_ROOT` remain
higher priority.

Use `Project.save(...)` for ad-hoc or interim artifacts that belong to the
analysis workspace rather than the shared data `Store`:

```python
quality = case.kaguya.esa1.quality.load()
artifact = project.save(quality, "interim/kaguya_esa1_quality_wake")
artifact.path
artifact.metadata_path
```

The current implementation writes xarray-compatible values as NetCDF (`.nc`)
and records a JSON metadata sidecar with name, relative path, time coverage, and
source files when available.
