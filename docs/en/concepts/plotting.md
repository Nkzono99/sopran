# Plotting

SOPRAN treats stacked time-series visualization as part of the public model,
because analysis often compares products from different instruments.

## One-Panel Quicklook

```python
counts = kg.esa1.counts.load(time)
counts.plot()
counts.quicklook("counts_spectrum", root="reports", y="energy", log_color=True)
```

`SopranArray.plot()` and `SopranArray.quicklook()` default to `mode="auto"`.
1D arrays become line plots, 2D `time x energy` arrays become spectrograms, and
3D `time x energy x pitch_angle` arrays become a two-panel pitch/time and
energy/time overview. Use `plot(mode="raw")` for direct xarray plotting.

## Multi-Panel Plot

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    kg.esa1.quality.load(time).line(),
    art.p1.fgm.magnetic_field.load(time).lines(components="xyz"),
    wave_power.load(time).histogram(bins=50),
)

plot_result = stack.plot(backend="matplotlib")
plot_result.fig
```

## Plotting vs Feature Tables

| Goal | API |
| --- | --- |
| Compare native cadences | `PlotStack` |
| Inspect value distributions | `histogram(bins=...)` |
| Aggregate onto common bins | `time_bins()` / `SampleTable` |
| Build ML matrices | `to_feature_matrix()` |
| Save provenance | `quicklook(..., context=case)` |

Interactive backend status is tracked in [Status](../reference/status.md).
