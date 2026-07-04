# Load KAGUYA ESA1

## Prerequisites

- A `Store` root is configured.
- KAGUYA PDS3 raw files exist, or the network archive is reachable.
- Time ranges are half-open: `[start, stop)`.

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")
```

## 1. Inspect

```python
kg.esa1.counts.plan(time)
kg.esa1.select("2008-01-01").remote_files()
```

## 2. Load

```python
esa1 = kg.esa1.load(time)
counts = esa1.counts
array = counts.to_xarray()
table = esa1.to_polars("counts")
summed = esa1.to_polars("counts", reduce_look="sum")
```

`counts.to_xarray()` returns the dense `time x energy x look` array.
The current `energy` coordinate is a channel index, not physical eV.
`esa1.to_polars("counts")` keeps one row per time sample and stores `counts` as
a `pl.Array` column. Request full expansion explicitly with `layout="long"`;
for ordinary tabular output, reduce the look dimension first, for example with
`reduce_look="sum"`. The PACE fill value `65535` is converted to NaN as a
SPEDAS-compatible normalization; see `kg.esa1.guide()` for source notes and
caveats.

For an energy spectrum binned by pitch angle, load the calibration tables and
call `pitch_angle_spectrum()`. `look` is an index; it becomes a direction only
through the PACE angle calibration.

```python
cal = kg.esa1.load_calibration()
esa1 = kg.esa1.load(time, calibration=cal)
pas = esa1.pitch_angle_spectrum([1.0, 0.0, 0.0])
```

## 3. Plot

```python
counts.plot()
counts.quicklook("kaguya_esa1_counts", root="reports", y="energy", log_color=True)
pas.plot()
pas.pitch_spectrogram(log_color=True)
pas.energy_spectrogram(pitch=(0.0, 30.0), log_color=True)
```

`plot()` and `quicklook()` default to `mode="auto"`. `time x energy` arrays
become energy spectrograms; `time x energy x pitch_angle` arrays become a
two-panel pitch/time and energy/time overview. Use `plot(mode="raw")` when you
want direct xarray plotting.

## Download Policy

`Kaguya()` defaults to `download="missing"`. Missing raw files are fetched from
the DARTS public PDS3 archive and stored under `Store.raw_path("kaguya", "pds3")`.

```python
kg.esa1.counts.load(time)
```

Use `download="never"` for offline-only analysis.

```python
kg = spn.Kaguya(store=store, download="never")
```

`SOPRAN_OFFLINE=1` also forces the default policy to `never`.
