# First Analysis

This walkthrough uses KAGUYA ESA1 for a short inspect-load-plot flow.

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")
```

## Inspect First

```python
kg.esa1.counts.info()
kg.esa1.counts.plan(time)
kg.esa1.counts.guide()
kg.esa1.counts.guide(language="en")
```

## Load

```python
esa1 = kg.esa1.load(time)
esa1.info()

ds = esa1.to_xarray()
counts = esa1.to_polars("counts", reduce_look="sum")
```

## Plot Together

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    kg.esa1.quality.load(time).line(),
)

plot_result = stack.plot()
plot_result.fig
```

## Which API?

| Goal | API |
| --- | --- |
| Inspect metadata and expected files | `info()` / `plan()` |
| Analyze in memory | `load()` / `to_xarray()` / `to_polars()` |
| Save a figure | `quicklook()` |
| Compare products | `spn.stack()` |
| Build ML-ready samples | `time_bins()` / `SampleTable` |
