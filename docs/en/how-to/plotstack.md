# Build A PlotStack

## Checklist

- Choose panels.
- Use `spectrogram(y=...)` for spectra.
- Use `lines(components=...)` for vectors.
- Use `histogram(bins=...)` for value distributions.
- Use `quicklook(root=...)` to save outputs.

## From Loaded Objects

```python
sza = kg.orbit.sza.load(time, cache="use")

stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    kg.esa1.quality.load(time).line(),
    sza.histogram(bins=36),
)

plan = stack.plan()
plot_result = stack.plot(backend="matplotlib")
figure = plot_result.fig
```

## Overlay Spectrum Peaks

```python
ima = kg.ima.counts.load(time)
peak = ima.peak_trace(axis="energy", min_value=5.0)

stack = spn.stack(
    ima.spectrogram(y="energy", log_color=True).overlay(
        peak.line(name="energy_peak")
    ),
    kg.lmag.magnetic_field.load(time).lines(components="xyz"),
)

plot_result = stack.plot(backend="matplotlib")
```

## Customize With Matplotlib Before Saving

```python
def configure(result):
    result.axes[0].set_ylim(10, 1000)
    result.axes[-1].tick_params(axis="x", rotation=30)
    result.fig.tight_layout()

quicklook = stack.quicklook(
    "ima_lmag_overview",
    root="reports",
    formats=("png", "html"),
    configure=configure,
)
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
