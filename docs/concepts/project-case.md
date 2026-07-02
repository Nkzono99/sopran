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
```

`case.region` is `None` when no region is configured. Case-specific region
settings override `[defaults.region]`.
