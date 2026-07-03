# KAGUYA PACE ESA1

PACE ESA1 provides electron-spectrum endpoints. Start with `counts`, then pass
data to parquet storage or PlotStack.

```python
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")

counts = kg.esa1.counts.load(time)
counts.to_xarray()
counts.to_polars()
```

## Endpoints

| Endpoint | Dims | Use |
| --- | --- | --- |
| `kg.esa1.counts` | `time, energy, look` | Raw counts and quicklooks |
| `kg.esa1.energy_flux` | `time, energy, look` | Calibrated flux target |
| `kg.esa1.quality` | `time` | Flag panel, masks, alignment |

## Quicklook

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy", log_color=True),
    kg.esa1.quality.load(time).line(),
)
stack.quicklook("kaguya_esa1", root="reports")
```

## Parquet

```python
record = (
    kg.esa1.pipeline(spn.period("2008-01-01", "2008-01-03"))
    .decode()
    .select_variables("counts")
    .write("kaguya.esa1.counts", layer="normalized", partition="day")
    .run()
)
```

Calibration tables, `energy_flux`, look-angle coordinates, and SPEDAS parity
tests are tracked in [Status](../../reference/status.md).
