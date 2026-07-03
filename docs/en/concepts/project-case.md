# Project And Case

`Project` represents an analysis workspace. `Case` represents a specific time
range, region, and set of defaults.

```python
project = spn.Project("projects/lunar_wake", store=store)
case = project.case("wake_20080201")
```

## sopran.toml

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

dem = case.moon.dem.plan(source="kaguya.tc.dem")
shadow = case.moon.shadow.plan(dem=dem)
```

Pass `context=case` to preserve analysis provenance in plots, features, and
artifacts.
