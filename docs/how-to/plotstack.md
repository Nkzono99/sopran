# Build A PlotStack

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy"),
    kg.esa1.quality.load(time).line(),
)

plan = stack.plan()
plot_result = stack.plot(backend="matplotlib")
figure = plot_result.fig
result = stack.quicklook(
    "wake_overview",
    root="reports",
    formats=("png", "html"),
    backend="matplotlib",
)
```

With a project case, omit the repeated time argument and let the case provide it:

```python
stack = case.stack(
    case.kaguya.esa1.counts.spectrogram(y="energy"),
    case.kaguya.esa1.quality.line(),
)

plot_result = stack.plot(backend="matplotlib")
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
`plot()` returns a `PlotResult` with `fig`, `axes`, `backend`, and metadata.
`quicklook()` writes `<name>.png`, optional `<name>.html`, and `<name>.json`.
Pass `dataset_id`, `time_range`, `frame`, and `aggregation` when the quicklook
should carry provenance into the JSON and HTML report. Pass `context=case` to
include `case.metadata()` as the quicklook context.
