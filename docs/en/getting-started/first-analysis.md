# First Analysis

This walkthrough uses KAGUYA ESA1 for a short inspect-load-plot flow.

```python
import sopran as spn

view = spn.view(time=spn.day("2008-01-01"), frame="SSE")
```

## Inspect First

```python
view.kaguya.esa1.counts.info()
view.kaguya.esa1.counts.plan()
view.kaguya.esa1.counts.guide()
view.kaguya.esa1.counts.guide(language="en")
```

## Load

```python
esa1 = view.kaguya.esa1.load()
esa1.info()

ds = esa1.to_xarray()
counts = esa1.to_polars("counts", reduce_look="sum")
```

## Plot Together

For spectrum-like products, `plot()` is the first quick view. The x-axis is
`time`, the y-axis is `energy` or `pitch_angle`, and color carries the product
value such as `energy_flux` or `counts`. The colorbar includes the value name
and units when available.

```python
view.kaguya.esa1.energy_flux.plot(log_color=True)
```

Use `spectrogram()` and `line()` with `stack()` when comparing multiple panels.

```python
stack = spn.stack(
    view.kaguya.esa1.counts.spectrogram(y="energy", log_color=True),
    view.kaguya.esa1.quality.line(),
)

plot_result = stack.plot()
plot_result.fig
```

Derive a new `View` when exploring another time range.

```python
zoom = view.with_time("2008-01-01T03:00:00", "2008-01-01T04:00:00")
zoom.kaguya.esa1.counts.plot()
```

## Which API?

| Goal | API |
| --- | --- |
| Inspect the data tree | `project.kaguya.esa1.counts.info()` / `schema()` |
| Change time or region interactively | `project.view(...)` / `spn.view(...)` |
| Inspect metadata and expected files | `info()` / `plan()` |
| Analyze in memory | `load()` / `to_xarray()` / `to_polars()` |
| Save a figure | `quicklook()` |
| Compare products | `spn.stack()` |
| Build ML-ready samples | `time_bins()` / `SampleTable` |
