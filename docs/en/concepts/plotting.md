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
For spectrograms, the x-axis is `time`, the y-axis is `energy` or
`pitch_angle`, and color carries the product value. The colorbar label shows
the value name and units, for example `energy_flux [eV/(cm^2 s sr eV)]`.

```python
kg.esa1.energy_flux.plot(time)
kg.esa1.energy_flux.plot(
    time,
    ylim=(10.0, 10000.0),
    vmin=1.0e6,
    vmax=1.0e9,
)
```

KAGUYA PACE `energy_flux.plot()` uses a log energy axis and log color scale by
default. Generic spectrograms also accept `yscale="log"`, `ylim=(low, high)`,
`log_color=True`, `vmin=...`, and `vmax=...`.

## Rebin Before Plotting

`SopranArray.rebin(axis=..., bins=...)` aggregates any numeric coordinate axis
onto requested bin edges. The same API works for energy spectra, pitch-angle
spectra, frequency spectra, and map lon/lat axes. The default reduction is
`sum`; use `reduction="mean"` for flux-like quantities that should be averaged.

```python
flux = kg.esa1.energy_flux.load(time)
coarse = flux.rebin(axis="energy", bins=[10, 30, 100, 300, 1000], reduction="mean")
coarse.plot(log_color=True)

pas = kg.esa1.energy_flux.pitch_angle_spectrum(time, magnetic_field=[1, 0, 0])
pas.rebin(
    bins={
        "energy": [10, 100, 1000, 10000],
        "pitch_angle": [0, 30, 60, 90, 120, 150, 180],
    }
).plot()
```

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

Already rendered `plot()` results can also be passed to `spn.stack()`. This is
useful in notebooks when exploring endpoints first and turning them into panels
afterward.

```python
stack = spn.stack(
    spn.kaguya.esa1.energy_flux.plot(time, calibration="auto"),
    spn.kaguya.orbit.sza.plot(time),
)
stack.plot()
```

## Overlay Spectrum Peaks

`peak_trace(axis="energy")` returns the coordinate of the strongest energy bin
at each time. Use `overlay()` to draw that candidate trace on the same
spectrogram panel. Treat it as quicklook candidate extraction; final scientific
selection should still use explicit user-side criteria.

```python
ima = kg.ima.counts.load(time)
peak = ima.peak_trace(axis="energy", min_value=5.0)

stack = spn.stack(
    ima.spectrogram(y="energy", log_color=True).overlay(
        peak.line(name="energy_peak")
    ),
    kg.lmag.magnetic_field.load(time).lines(components="xyz"),
)
stack.plot()
```

Use `max_peaks=2` to return multiple `time x peak` traces. For arrays such as
PACE `time x energy x look`, extra axes such as `look` are summed before peak
candidates are selected.

## Customize Through The Backend

SOPRAN keeps only common options in its public plotting API. For detailed
styling, use the backend-native objects returned on `PlotResult`. With the
matplotlib backend, `PlotResult.fig` and `PlotResult.axes` are the real
matplotlib objects.

```python
result = stack.plot()
result.axes[0].set_ylim(10, 1000)
result.axes[0].tick_params(axis="x", rotation=30)
result.fig.suptitle("IMA / LMAG overview")
result.fig.tight_layout()
```

Pass `configure` when a quicklook needs those edits before files are saved.

```python
def configure(result):
    result.axes[0].set_ylim(10, 1000)
    result.axes[-1].tick_params(axis="x", rotation=30)
    result.fig.suptitle("IMA / LMAG overview")

stack.quicklook("ima_lmag", root="reports", configure=configure)
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
