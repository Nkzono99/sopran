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
```

The v0.1 implementation uses Matplotlib. HoloViz, Datashader, Panel dashboards,
and HTML quicklooks are planned for larger interactive products.
