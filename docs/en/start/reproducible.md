# Reproducible Analysis

Event studies compare several instruments over the same period and region, and record the conditions once they look right.
SOPRAN uses `View` for temporary conditions, `Case` for named, saved conditions, and `Project` for the workspace that holds them.

## Bind period and region with a View

```python
import sopran as spn

view = spn.view(
    time=spn.day("2008-02-01"),
    region=spn.Region(lon=(120, 160), lat=(-45, -10), body="moon"),
    frame="SSE",
)

view.kaguya.esa1.counts.load()            # the time defaults to the view's period
view.kaguya.lmag.magnetic_field.plot()
view.moon.sza.compute(subsolar_lon_lat=(0.0, 0.0))   # the region also comes from the view
```

`view.kaguya` is a real `spn.Kaguya`; only its defaults for time, region, download policy, and SPICE kernels are bound to `view`.
`frame="SSE"` is recorded as an analysis condition. Coordinate transforms are explicit, with `transform()` from
[Coordinate Frames](../guide/frames.md).
To change only the period, derive a new `View`. The original `view` does not change.

```python
zoom = view.with_time("2008-02-01T03:00:00", "2008-02-01T04:00:00")
zoom.kaguya.esa1.counts.plot()
```

## Create a workspace with Project

A `Project` is a directory per analysis topic. It holds the `sopran.toml` settings file, saved conditions, and outputs.

```python
project = spn.Project("projects/lunar_wake")
view = project.view(time=spn.day("2008-02-01"), frame="SSE")
```

## Save a Case by name

```python
project.save_case("wake_20080201", zoom)
case = project.case("wake_20080201")

case.kaguya.esa1.counts.load()   # loads with the saved period and region
```

The conditions are appended to `projects/lunar_wake/sopran.toml`, which you can also edit by hand.

```toml
[cases.wake_20080201]
start = "2008-02-01T03:00:00Z"
stop = "2008-02-01T04:00:00Z"

[cases.wake_20080201.context]
frame = "SSE"

[cases.wake_20080201.region]
body = "moon"
lon = [120.0, 160.0]
lat = [-45.0, -10.0]
lon_domain = "0_360"
lon_direction = "east_positive"
lat_type = "planetocentric"
```

## Save conditions with the figure

Passing `context=case` to `quicklook()` records the Case name, period, region, and Store location in the figure's JSON.
Later you can tell which conditions produced a figure.

```python
stack = spn.stack(
    case.kaguya.esa1.counts.spectrogram(y="energy", log_color=True),
    case.kaguya.lmag.magnetic_field.lines(components="xyz"),
)
stack.quicklook("wake_overview", root="reports", context=case)
```

Intermediate arrays can be kept as NetCDF with `project.save(array, "interim/name", context=case)`.
Data reused across analyses belongs in the [Store](../guide/store.md), not in the Project.

## Next

That completes the basic workflow. From here, look things up as needed.

- All `View` and `Case` options and the `sopran.toml` format: [Time, Regions, And Cases](../guide/views-cases.md)
- Building multi-panel figures: [Plotting](../guide/plotting.md)
- Variables and caveats per instrument: [Data overview](../data/index.md)
