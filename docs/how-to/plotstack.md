# Build A PlotStack

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    kg.esa1.quality.load(time).line(),
)

plan = stack.plan()
plot_result = stack.plot(backend="matplotlib")
figure = plot_result.fig
view = stack.explore(backend="panel")
result = stack.quicklook(
    "wake_overview",
    root="reports",
    formats=("png", "html"),
    backend="matplotlib",
)
```

For a single loaded spectral variable, use the same spectrogram route through
`SopranArray.quicklook()`:

```python
counts = kg.esa1.counts.load(time)
counts.quicklook("counts_spectrum", root="reports", y="energy", log_color=True)
```

With a project case, omit the repeated time argument and let the case provide it:

```python
stack = case.stack(
    case.kaguya.esa1.counts.spectrogram(y="energy", log_color=True),
    case.kaguya.esa1.quality.line(),
    case.artemis.p1.esa.ion_energy_flux.spectrogram(y="energy", log_color=True),
    case.artemis.p1.fgm.magnetic_field.lines(components="xyz"),
)

plot_result = stack.plot(backend="matplotlib", context=case)
figure = plot_result.fig
quicklook = stack.quicklook(
    "wake_overview",
    root="reports",
    formats=("png", "html"),
    context=case,
)
```

`PlotStack` is the SPEDAS/tplot-like route for comparing time-series products
from different instruments or missions. The current backend is Matplotlib and
is selected with `backend="matplotlib"`.
Use `log_color=True` on spectrogram items for positive-valued spectra that need
a logarithmic color scale.
Use `.lines(components="xz")` for vector products when a component subset should
stay in one panel.
`explore(backend="panel")` returns a Panel view containing the same Matplotlib
figure and metadata for notebook or browser inspection.
`plot()` returns a `PlotResult` with `fig`, `axes`, `backend`, and metadata.
The metadata includes `items`, `panel_kinds`, `panels`, and `time_axis`,
recording the panel names, panel kinds, x/y/log-color settings, shared UTC
axis, and native cadence policy used by the stack.
Pass `context=case` when the `PlotResult.metadata` should carry the case
context.
`quicklook()` writes `<name>.png`, optional `<name>.html`, and `<name>.json`.
Pass `dataset_id`, `time_range`, `frame`, and `aggregation` when the quicklook
should carry provenance into the JSON and HTML report. Pass `context=case` to
include `case.metadata()` as the quicklook context.
