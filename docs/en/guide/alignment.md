# Time Alignment

Instruments sample at different times. Stacking them in a figure works with each instrument's own times ([Plotting](plotting.md)),
but comparing values or feeding statistics and machine learning requires aligning times explicitly.
SOPRAN offers two ways.

| Goal | Method |
|---|---|
| Attach another instrument's values to one instrument's sample times | `resample_like` |
| Build fixed-width time bins and a table of per-bin values from each instrument | `time_bins` + `SampleTable` |

## Match another instrument's times

```python
esa1 = spn.kaguya.esa1.counts.load(time)
conn = spn.kaguya.lmag.magnetic_connection.load(time)

conn_on_esa1 = conn.resample_like(esa1, method="nearest", tolerance="2s")
altitude_on_esa1 = spn.kaguya.orbit.altitude.load(time).resample_like(
    esa1, method="linear", tolerance="10s",
)
```

| `method` | Value used |
|---|---|
| `nearest` | Sample closest to the target time |
| `previous` | Last sample at or before the target time |
| `next` | First sample at or after the target time |
| `linear` | Linear interpolation between the neighboring samples |

Targets with no sample within `tolerance` become missing. For `linear` the condition applies to both neighbors,
so it never interpolates across data gaps, and it never extrapolates beyond the source.

The function form `spn.resample_like(source, target, ...)` also accepts pandas, Polars (`DataFrame`, `LazyFrame`),
and xarray objects in addition to `SopranArray`. Times are converted to UTC `datetime64[ns]` before matching.
Duplicate source times raise an error. `linear` on DataFrames interpolates numeric columns only, and pandas DataFrames with duplicate column names are rejected.

## Build time bins

```python
bins = spn.time_bins(time, cadence="10s", partial="drop")
bins.to_polars()     # index, start, stop, center, duration_seconds, is_partial
```

`partial` decides what happens when the range is not a multiple of `cadence`.

| `partial` | Behavior |
|---|---|
| `"error"` (default) | Raise an error |
| `"keep"` | Keep the short last bin |
| `"drop"` | Drop the short last bin |

Bins of unequal width, such as per-event intervals, come from explicit edges with `spn.time_bins(edges=[...])`.
Every bin is half-open, `[start, stop)`.

## Build a table of per-bin values

```python
features = (
    spn.SampleTable(bins)
    .add(sza, method="nearest", tolerance="5s")
    .add(wave_power, method="max")
    .add(density, method="median")
    .collect(join="inner")
)
```

| `method` | Value placed in the bin |
|---|---|
| `nearest` | Sample closest to the bin center (may lie outside the bin; limit with `tolerance`) |
| `center` | Sample inside the bin closest to its center |
| `mean`, `median`, `max` | Aggregate inside the bin |
| `first`, `last` | First or last sample inside the bin |

| `collect` argument | Effect |
|---|---|
| `join="outer"` (default) | Keep every bin; missing values stay missing |
| `join="inner"` | Keep only bins where every variable has a value |
| `fill=value` | Fill values left missing by `outer` |
| `quality_mask=array` | Drop bins where the quality flag is 0, False, or missing; applied before `join` and `fill` |

When every variable uses the same `method`, write `spn.align(sza, density, grid=bins, method="nearest", tolerance="5s")`.
`time × component` vectors expand into columns such as `magnetic_field_x` and `magnetic_field_y`.
Time series and vectors are supported; spectra cannot be binned directly yet.

## Using the result

| Call | Returns |
|---|---|
| `features.to_polars()` | Table with time and one column per variable; `layout="long"` for a long table |
| `features.to_feature_frame()` | Variable columns only (`include_time=True` adds time) |
| `features.to_feature_matrix()` | `FeatureMatrix` with a numeric matrix, column names, times, and provenance |
| `features.metadata()` | Record of bins, per-variable methods, and join settings |
| `features.write_dataset(store, "analysis.wake_context", context=case)` | Save in the Store's `features` layer |

`FeatureMatrix.select("sza", "wave_power")` selects columns; `write_parquet` and `write_npz` save it,
and `FeatureMatrix.read_parquet` and `read_npz` load it back.
