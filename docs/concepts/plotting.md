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
plot_result = stack.plot(backend="matplotlib")
stack.quicklook("wake_overview", root="reports", backend="matplotlib")
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
aligned = spn.align(sza, wave_power, grid=bins, method="mean", join="inner")
features = aligned.to_feature_frame()
matrix = aligned.to_feature_matrix()
matrix = matrix.select("sza", "wave_power")
pandas_frame = matrix.to_pandas(include_time=True)
feature_metadata = aligned.feature_metadata()
```

When each product needs a different sampling rule, use `SampleTable`:

```python
aligned = (
    spn.SampleTable(bins)
    .add(sza, method="nearest", tolerance="5s")
    .add(wave_power, method="max")
    .add(density, method="median")
    .add(event_flag, method="last")
    .collect(join="inner")
)
features = aligned.to_feature_frame(include_time=True)
```

`join="outer"` keeps every bin with nulls for missing features. `join="inner"`
drops bins that do not have every requested feature. Use `fill=<value>` with
the outer join when downstream tools need explicit sentinel values instead of
nulls.

The default feature table layout is wide. `to_polars(layout="long")` returns a
tidy `time`, `feature`, `value` table, which is often easier to facet or group
in exploratory plotting tools.
`to_feature_frame()` returns the ML/statistics input table without the time
column by default; use `include_time=True` when the bin center should travel
with the features.
`to_feature_matrix()` returns numpy-compatible values plus feature columns,
time labels, and metadata in a small object for ML libraries.
Use `FeatureMatrix.write_npz()` when a compact local artifact is more convenient
than a Parquet feature table, and `FeatureMatrix.read_npz()` to load it again.
Use `FeatureMatrix.select()` to keep only the columns a downstream model should
see.

Vector products such as ARTEMIS FGM are expanded to wide feature columns when
aligned, for example `magnetic_field_x`, `magnetic_field_y`, and
`magnetic_field_z`.

The v0.1 implementation accepts `backend="matplotlib"`. `plot()` returns a
`PlotResult` with `fig`, `axes`, `backend`, and metadata so quicklook and
notebook workflows can share the same plot description. Current `quicklook()`
output can include a Matplotlib PNG, a static HTML report with the PNG embedded,
and a small JSON metadata file. Quicklook metadata uses standard keys such as
`dataset_id`, `time_range`, `frame`, `backend`, and `aggregation` when those are
available. HoloViz, Datashader, Panel dashboards, and interactive HTML
quicklooks are planned for larger interactive products.
