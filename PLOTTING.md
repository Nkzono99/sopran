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
```

v0.1 should support a minimal Matplotlib stack with shared UTC x-axis. HoloViz,
Datashader, Panel dashboards, and HTML quicklooks are later milestones.
