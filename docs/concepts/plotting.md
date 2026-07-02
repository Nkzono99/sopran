# Plotting

Data analysis usually needs visualization, so plotting is part of the public
model. The beginner path is explicit:

```python
counts = kg.esa1.counts.load(time)
counts.plot()
```

`PlotStack` provides a SPEDAS/tplot-like multi-panel time-series view:

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy"),
    kg.esa1.quality.load(time).line(),
)

stack.plan()
stack.plot()
stack.quicklook("wake_overview", root="reports")
```

When a `Project` case supplies the time range, variable endpoints can create
lazy plot items directly:

```python
stack = case.stack(
    case.kaguya.esa1.counts.spectrogram(y="energy"),
    case.kaguya.esa1.quality.line(),
)
```

Line panels can also plot 2D `time x component` arrays as multiple lines in
one panel, which is the intended route for vector products such as magnetic
field components.

Plotting keeps native cadence. For machine-learning tables or statistical
joins, create explicit time bins and align products separately:

```python
bins = spn.time_bins(case.time, cadence="10s")
features = spn.align(sza, wave_power, grid=bins, method="mean").to_polars()
```

The v0.1 implementation uses Matplotlib. HoloViz, Datashader, Panel dashboards,
and HTML quicklooks are planned for larger interactive products. Current
`quicklook()` output is a Matplotlib PNG plus a small JSON metadata file.
