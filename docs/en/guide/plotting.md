# Plotting

SOPRAN figures come in two forms: `plot()` for a quick look at one array, and `PlotStack` for several instruments stacked on a shared time axis.
Both use Matplotlib and label axes and colorbars with variable names and units. Plotting needs the `viz` extra.

## Look at one array

```python
flux = spn.kaguya.esa1.energy_flux.load(time)
result = flux.plot()
```

`plot()` picks the figure type from the dimensions (`mode="auto"`).

| Dimensions | Default figure |
|---|---|
| `time` only | Line |
| `time × energy × pitch_angle` | Two panels: pitch angle vs time and energy vs time |
| Any other two or more (`time × energy`, `time × energy × look`, …) | Spectrogram: time on x, a coordinate such as `energy` on y, value as color. Extra dimensions are reduced with `reduction` (default `"sum"`) |

Pass `mode="line"`, `"spectrogram"`, `"pitch"`, or `"energy"` to fix the type.
Use `mode="raw"` for xarray's own `plot()`.
Plot vectors such as the magnetic field as component lines with `lines(components="xyz")`, described below.

Adjust the visible range and scales with:

| Argument | Example |
|---|---|
| y range and scale | `ylim=(10, 10000)`, `yscale="log"` |
| color range and log color | `vmin=1e6`, `vmax=1e9`, `log_color=True` |
| coordinate on y | `y="energy"` |

Quantities spanning many decades, such as energy flux, use logarithmic color and energy axes by default, as set in the schema (`log_scale`, `log_dims`).
PACE `energy_flux` and ARTEMIS `ion_energy_flux` and `electron_energy_flux` carry these hints today. Pass `yscale="linear"` and `log_color=False` for linear scales.
The defaults are the same for array `plot()`, `quicklook()`, and `spectrogram()` and for the endpoint call `spn.kaguya.esa1.energy_flux.plot(time)`.

## Stack several instruments

Build multi-panel figures sharing the time axis with `spn.stack()`. This corresponds to SPEDAS `tplot`.

```python
stack = spn.stack(
    spn.kaguya.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    spn.kaguya.lmag.magnetic_field.load(time).lines(components="xyz"),
    spn.kaguya.orbit.altitude.load(time, cache="use").line(),
)
result = stack.plot()
```

Array methods create the panels.

| Method | Panel |
|---|---|
| `spectrogram(y=...)` | Spectrogram; also takes `log_color`, `ylim`, `vmin`, `vmax` |
| `line()` | One-dimensional time series |
| `lines(components="xyz")` | Vector components; `components="xz"` selects a subset |
| `histogram(bins=50)` | Value distribution |
| `pitch_spectrogram()`, `energy_spectrogram(pitch=(0, 30))` | Cuts through a pitch-angle spectrum |

Each panel keeps its instrument's own sample times; nothing is interpolated in time. To compare values at common times,
use the methods in [Time Alignment](alignment.md).

Endpoints also provide `spectrogram()` and friends. Those panels load data when `stack.plot()` runs.

```python
view = spn.view(time=time)
stack = spn.stack(
    view.kaguya.esa1.energy_flux.spectrogram(y="energy"),
    view.kaguya.lmag.magnetic_field.lines(components="xyz"),
)
stack.plan()     # check what will be loaded before running
```

Results from `plot()` can also be passed to `spn.stack()`, so figures tried one by one in a notebook can be combined later.

## Overlay spectral peaks

`peak_trace(axis="energy")` returns, for each time, the energy where the value peaks.
`overlay()` draws it on top of a spectrogram.

```python
ima = spn.kaguya.ima.counts.load(time)
peak = ima.peak_trace(axis="energy", min_value=5.0)

spn.stack(
    ima.spectrogram(y="energy", log_color=True).overlay(peak.line(name="energy_peak")),
).plot()
```

Use `max_peaks=2` for several peaks and `method="prominence"` to select by prominence.
Extra dimensions such as `look` are summed first by default. This is a candidate extraction for visual inspection;
define and verify your own criteria before using peaks in an analysis.

## Fine-tune with Matplotlib

The `PlotResult` from `plot()` exposes Matplotlib's `fig` and `axes`.

```python
result = stack.plot()
result.axes[0].set_ylim(10, 1000)
result.fig.suptitle("IMA / LMAG")
```

To apply the same changes before saving, pass a function as `configure`.

```python
def configure(result):
    result.axes[-1].tick_params(axis="x", rotation=30)
    result.fig.tight_layout()

stack.quicklook("ima_lmag", root="reports", configure=configure)
```

## Save figures

`quicklook(name, root=...)` saves the figure together with how it was made. Both `SopranArray` and `PlotStack` provide it.

| `formats` | Files |
|---|---|
| `("png",)` (default) | PNG and a JSON with the same name |
| `("png", "html")` | Also a simple HTML page with the image and the record |

The JSON records panel types, axes and color settings, time range, frame, and processing history.
Passing `context=view` or `context=case` records those analysis conditions as well ([Time, Regions, And Cases](views-cases.md)).

For interactive inspection in a browser, `stack.explore()` builds a Panel app.
