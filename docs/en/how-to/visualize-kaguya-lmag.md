# Visualize KAGUYA LMAG Geometry

This is the shortest path for inspecting LMAG-native magnetic field, orbit, and
lunar-surface magnetic connection products.

## Prerequisites

- KAGUYA LMAG raw files exist under `Store.raw_path("kaguya", "pds3")`, or
  `download="missing"` can fetch them.
- Use `missing="empty"`, `"warn"`, or `"error"` to control behavior when raw
  files are absent.

## Inspect The LMAG Time Grid

```python
import sopran as spn

store = spn.Store("data/store")
kg = spn.Kaguya(store=store, download="never")
time = spn.day("2008-01-01")

b = kg.lmag.magnetic_field.load(time)
bmag = kg.lmag.bmag.load(time)
altitude = kg.orbit.altitude.load(time, cache="use")
subpoint = kg.orbit.subpoint.load(time, cache="use")
```

```python
spn.stack(
    bmag.lines(),
    altitude.lines(),
).plot()
```

## Plot Surface Connection

```python
conn = kg.lmag.magnetic_connection.load(time, cache="use")

conn.plot(kind="footpoint")
conn.plot(kind="incidence")
conn.plot(kind="distance")
```

`conn.to_xarray()` contains `connected_any`, plus/minus connection flags,
footpoint lon/lat, connection distance, and incidence angle.

## Match ESA1 Or Other Time Grids

```python
esa1 = kg.esa1.counts.load(time, missing="warn")
conn_on_esa1 = conn.resample_like(esa1, method="nearest", tolerance="2s")
altitude_on_esa1 = altitude.resample_like(esa1, method="linear", tolerance="10s")
```

`cache="use"` reads a matching Store variant when it exists. If raw files are
absent or only partly available and `missing="empty"` / `"warn"` returns
incomplete data, that derived product is not written to the Store cache.
