# Build A PlotStack

## Checklist

- Choose panels.
- Use `spectrogram(y=...)` for spectra.
- Use `lines(components=...)` for vectors.
- Use `histogram(bins=...)` for value distributions.
- Use `quicklook(root=...)` to save outputs.

## From Loaded Objects

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    kg.esa1.quality.load(time).line(),
    sza.load(time).histogram(bins=36),
)

plan = stack.plan()
plot_result = stack.plot(backend="matplotlib")
figure = plot_result.fig
```

## From A Case

```python
stack = case.stack(
    case.kaguya.esa1.counts.spectrogram(y="energy", log_color=True),
    case.kaguya.esa1.quality.line(),
    case.artemis.p1.esa.ion_energy_flux.spectrogram(y="energy", log_color=True),
    case.artemis.p1.fgm.magnetic_field.lines(components="xyz"),
)

quicklook = stack.quicklook(
    "wake_overview",
    root="reports",
    formats=("png", "html"),
    context=case,
)
```

## Outputs

| Output | Contents |
| --- | --- |
| `.png` | Static quicklook |
| `.html` | Simple report with image and metadata |
| `.json` | Panels, time axis, context, provenance |
