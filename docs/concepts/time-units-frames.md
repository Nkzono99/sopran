# Time, Units, And Frames

SOPRAN public APIs use half-open UTC ranges:

```python
time = spn.period("2008-02-01", "2008-02-02")
day = spn.day("2008-02-01")
month = spn.month("2008-02")
year = spn.year("2008")
```

The interval is `[start, stop)`. This avoids double-counting records at
boundaries when appending daily or monthly shards.

## Time Bins And Alignment

Use `PlotStack` when you want to inspect products together without changing
their native cadence. Use `TimeBins` and `align()` when you need a feature table
for statistics or machine learning and every input can share the same sampling
rule:

```python
bins = spn.time_bins(time, cadence="10s")
features = spn.align(sza, wave_power, grid=bins, method="nearest", tolerance="5s")
frame = features.to_polars()
features.write_parquet("features.parquet")
```

Use `SampleTable` when each product needs its own rule, such as nearest SZA and
bin-mean wave power:

```python
features = (
    spn.SampleTable(bins)
    .add(sza, method="nearest", tolerance="5s")
    .add(wave_power, method="mean")
    .collect()
)
frame = features.to_polars()
```

The first implementation supports 1D time series and `time x component` vector
series with `nearest` or `mean` alignment onto regular half-open bins. Vector
series are expanded to wide columns such as `magnetic_field_x`.

Coordinate frames and units are still early-stage. The design goal is to avoid
reimplementing established space-physics and planetary geometry libraries. SPICE
and SpacePy-family tools should be used for kernel-backed geometry and common
coordinate transforms where they fit.
