# KAGUYA PACE ESA1

PACE ESA1 provides electron-spectrum endpoints. Start with `counts`, then pass
data to parquet storage or PlotStack.

```python
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")

counts = kg.esa1.counts.load(time)
flux = kg.esa1.energy_flux.load(time, calibration="auto")
counts.to_xarray()
counts.to_polars()
```

## Endpoints

| Endpoint | Dims | Use |
| --- | --- | --- |
| `kg.esa1.counts` | `time, energy, look` | Raw counts and quicklooks |
| `kg.esa1.energy_flux` | `time, energy, look` | Counts calibrated to energy flux with INFO tables |
| `kg.esa1.quality` | `time` | Flag panel, masks, alignment |

`energy_flux` uses the Python reference formula
`counts / (integ_t * gfactor * efficiency)`, with default `efficiency=0.6`.
If INFO calibration tables are unavailable,
`kg.esa1.energy_flux.load(...)` raises an actionable error. The `energy`
coordinate is currently still mostly a channel index. Use `missing="empty"`,
`"warn"`, or `"error"` to control behavior when raw files are unavailable.

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
    kg.esa1.energy_flux.pipeline(spn.period("2008-01-01", "2008-01-03"))
    .calibrate(calibration="auto")
    .write("kaguya.esa1.energy_flux", layer="normalized", partition="day")
    .run()
)
```

Raw counts storage does not use the calibration stage.

```python
record = (
    kg.esa1.counts.pipeline(spn.period("2008-01-01", "2008-01-03"))
    .write("kaguya.esa1.counts", layer="normalized", partition="day")
    .run()
)
```

Look-angle coordinates and longer validation status are tracked in
[Status](../../reference/status.md).
