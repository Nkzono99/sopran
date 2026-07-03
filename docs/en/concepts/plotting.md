# Plotting

SOPRAN treats stacked time-series visualization as part of the public model,
because analysis often compares products from different instruments.

## One-Panel Quicklook

```python
counts = kg.esa1.counts.load(time)
counts.quicklook("counts_spectrum", root="reports", y="energy", log_color=True)
```

## Multi-Panel Plot

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    kg.esa1.quality.load(time).line(),
    art.p1.fgm.magnetic_field.load(time).lines(components="xyz"),
)

plot_result = stack.plot(backend="matplotlib")
plot_result.fig
```

## Plotting vs Feature Tables

| Goal | API |
| --- | --- |
| Compare native cadences | `PlotStack` |
| Aggregate onto common bins | `time_bins()` / `SampleTable` |
| Build ML matrices | `to_feature_matrix()` |
| Save provenance | `quicklook(..., context=case)` |

Interactive backend status is tracked in [Status](../reference/status.md).
