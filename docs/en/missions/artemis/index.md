# ARTEMIS

ARTEMIS exposes THEMIS P1/P2 as lunar-neighborhood mission objects.

```python
art = spn.Artemis()
time = spn.day("2011-07-01")

plan = art.p1.fgm.magnetic_field.plan(time)
ion = art.p1.esa.ion_energy_flux
```

## Endpoints

| Probe | Instrument | Endpoint | Plot |
| --- | --- | --- | --- |
| `p1` / `p2` | `fgm` | `magnetic_field` | `.lines(components="xyz")` |
| `p1` / `p2` | `esa` | `ion_energy_flux` | `.spectrogram(y="energy")` |

## PlotStack

```python
stack = spn.stack(
    art.p1.esa.ion_energy_flux.spectrogram(time, y="energy", log_color=True),
    art.p1.fgm.magnetic_field.lines(time, components="xyz"),
)
plot_result = stack.plot()
```

## Store

ARTEMIS endpoints currently read normalized parquet when available in `Store`.

```python
lazy = store.scan_dataset("artemis.p1.fgm.magnetic_field", layer="normalized")
frame = lazy.collect()
```

Raw discovery, CDAWeb/HAPI, and CDF download status is tracked in
[Status](../../reference/status.md).
