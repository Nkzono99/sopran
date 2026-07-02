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
features = spn.align(sza, wave_power, grid=bins, method="mean", join="inner").to_polars()
```

When each product needs a different sampling rule, use `SampleTable`:

```python
features = (
    spn.SampleTable(bins)
    .add(sza, method="nearest", tolerance="5s")
    .add(wave_power, method="max")
    .add(density, method="median")
    .collect(join="inner")
    .to_polars()
)
```

`join="outer"` keeps every bin with nulls for missing features. `join="inner"`
drops bins that do not have every requested feature. Use `fill=<value>` with
the outer join when downstream tools need explicit sentinel values instead of
nulls.

The default feature table layout is wide. `to_polars(layout="long")` returns a
tidy `time`, `feature`, `value` table, which is often easier to facet or group
in exploratory plotting tools.

Vector products such as ARTEMIS FGM are expanded to wide feature columns when
aligned, for example `magnetic_field_x`, `magnetic_field_y`, and
`magnetic_field_z`.

The v0.1 implementation uses Matplotlib. HoloViz, Datashader, Panel dashboards,
and HTML quicklooks are planned for larger interactive products. Current
`quicklook()` output is a Matplotlib PNG plus a small JSON metadata file.
