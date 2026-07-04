# SOPRAN Plotting Spec

Status: draft

Plotting is part of the analysis model, but the beginner path should load data
explicitly before plotting:

```python
flux = case.kaguya.esa1.energy_flux.load()
flux.plot()
```

Endpoint direct plotting is convenience only. If it loads or computes data, it
must emit plan/log/provenance.

```python
case.kaguya.esa1.energy_flux.plot()
```

Endpoint-derived PlotItems are allowed for PlotStack. In v0.1 these items are
lazy: stack construction records the endpoint and case/time context, and actual
loading happens when `stack.plot()` materializes the panel.

```python
stack = case.stack(
    case.kaguya.esa1.counts.spectrogram(y="energy"),
    case.kaguya.esa1.quality.line(),
)
```

## PlotStack

`PlotStack` is the SPEDAS/tplot-like multi-panel time-series view.

```python
stack = case.stack(
    case.kaguya.esa1.energy_flux.spectrogram(y="energy"),
    case.kaguya.orbit.altitude.line(),
    case.artemis.p1.fgm.magnetic_field.lines(components="xyz"),
)

stack.plan()
stack.plot()
stack.quicklook("wake_overview", root="reports")
```

v0.1 supports a minimal Matplotlib stack with shared UTC x-axis and PNG
quicklook export with JSON metadata. Line panels accept 1D series and 2D
`time x component` vector series. HoloViz, Datashader, Panel dashboards, and
HTML quicklooks are later milestones.
