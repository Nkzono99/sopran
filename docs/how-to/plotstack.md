# Build A PlotStack

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy"),
    kg.esa1.quality.load(time).line(),
)

plan = stack.plan()
figure = stack.plot()
result = stack.quicklook("wake_overview", root="reports")
```

With a project case, omit the repeated time argument and let the case provide it:

```python
stack = case.stack(
    case.kaguya.esa1.counts.spectrogram(y="energy"),
    case.kaguya.esa1.quality.line(),
)

figure = stack.plot()
```

`PlotStack` is the SPEDAS/tplot-like route for comparing time-series products
from different instruments or missions. The current backend is Matplotlib.
`quicklook()` writes `<name>.png` and `<name>.json`.
