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

`time_bins()` is strict by default: `partial="error"` raises if the requested
range is not exactly divisible by the cadence. Use `partial="keep"` to retain a
short final bin, or `partial="drop"` to discard it:

```python
bins = spn.time_bins(time, cadence="10s", partial="keep")
```

## Time Bins And Alignment

Use `PlotStack` when you want to inspect products together without changing
their native cadence. Use `TimeBins` and `align()` when you need a feature table
for statistics or machine learning and every input can share the same sampling
rule:

```python
bins = spn.time_bins(time, cadence="10s")
features = spn.align(
    sza,
    wave_power,
    grid=bins,
    method="nearest",
    tolerance="5s",
    join="inner",
)
frame = features.to_polars()
features.write_parquet("features.parquet")
```

Use `SampleTable` when each product needs its own rule, such as nearest SZA,
bin-maximum wave power, bin-median density, or the first/last sample:

```python
features = (
    spn.SampleTable(bins)
    .add(sza, method="nearest", tolerance="5s")
    .add(wave_power, method="max")
    .add(density, method="median")
    .add(event_flag, method="last")
    .collect(join="inner")
)
frame = features.to_polars()
```

The default table layout is wide, with one feature per column. Use
`layout="long"` for a tidy `time`, `feature`, `value` table:

```python
long_frame = features.to_polars(layout="long")
features.write_parquet("features-long.parquet", layout="long")
metadata = features.metadata()
```

`metadata()` returns the columns, bin grid, alignment method, join mode, and
fill policy so the same information can be written into a dataset manifest.

The first implementation supports 1D time series and `time x component` vector
series with `nearest`, `center`, `mean`, `max`, `median`, `first`, or `last`
alignment onto regular half-open bins. `nearest` samples the bin center across
all samples, `center` samples the nearest value inside each bin, and the other
reducers aggregate samples inside `[start, stop)`. Vector series are expanded to
wide columns such as `magnetic_field_x`.

The default `join="outer"` keeps every time bin and leaves missing feature
values as null. Use `join="inner"` when a machine-learning or statistical table
should keep only bins where every feature is present.

If missing values should be explicit rather than null, pass a scalar `fill`
value with the outer join:

```python
features = spn.align(sza, wave_power, grid=bins, method="nearest", fill=-1.0)
```

Pass `quality_mask=<1D time series>` to `align()` or `SampleTable.collect()`
when a coarse quality series should filter bins before the feature table is
written. The mask is sampled at the bin center inside each bin; bins with a
mask value of 0, `False`, or no mask sample are dropped:

```python
features = (
    spn.SampleTable(bins)
    .add(sza, method="nearest", tolerance="5s")
    .add(wave_power, method="max")
    .collect(join="inner", quality_mask=quality_flag)
)
```

Coordinate frames and units are still early-stage. The design goal is to avoid
reimplementing established space-physics and planetary geometry libraries. SPICE
and SpacePy-family tools should be used for kernel-backed geometry and common
coordinate transforms where they fit.
