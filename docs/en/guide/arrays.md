# Working With Arrays

An endpoint's `load()` returns a `SopranArray`: an `xarray.DataArray` with the variable name, schema (dimensions, units, frame),
time range, source files, and processing history attached. This page covers selecting, reducing, rebinning, converting to tables, and saving.
Plotting is in [Plotting](plotting.md), and matching another instrument's times is in [Time Alignment](alignment.md).

## Inspect the contents

```python
flux = spn.kaguya.esa1.energy_flux.load(time)

flux.info()       # name, dimensions, time range, units
flux.schema       # VariableSchema (dimensions, units, frame, aliases)
flux.trange       # loaded time range (TimeRange)
flux.files        # source files
flux.metadata     # type, name, time range, schema, sources, and processing history
flux.xr           # the underlying xarray.DataArray
```

`metadata` is JSON-ready and is used as provenance whenever figures or Store datasets are saved.

## Select and reduce

Common xarray operations are available on `SopranArray` directly. They return a `SopranArray`, and the schema's dimensions follow the result.

```python
band = flux.isel(energy=slice(4, 12)).mean("energy")
positive = flux.where(flux.xr > 0)
hour = flux.sel(time=slice("2008-02-01T03:00", "2008-02-01T04:00"))
```

Use `resample` to average in time.

```python
ten_min = flux.resample(time="10min").mean()     # mean, sum, median, max, first, last
```

For anything else, drop to xarray through `flux.xr`. The result is a plain `DataArray` without units or sources.

## Rebin

`rebin` re-aggregates any axis with numeric coordinates onto given bin edges. The same call works for energy,
pitch angle, frequency, and map longitude or latitude.

```python
coarse = flux.rebin(axis="energy", bins=[10, 30, 100, 300, 1000], reduction="mean")

# several axes at once with a mapping (pas is a pitch-angle spectrum)
pas.rebin(bins={
    "energy": [10, 100, 1000, 10000],
    "pitch_angle": [0, 30, 60, 90, 120, 150, 180],
})
```

`reduction` defaults to `"sum"`. Counts add up; use `"mean"` for quantities such as flux that should be averaged.
`"median"`, `"min"`, `"max"`, and `"count"` are also available.

## Processing history

`rebin`, `resample`, `peak_trace`, `resample_like`, and `transform` append the operation and its arguments to
`metadata["operations"]`.

```python
coarse.metadata["operations"]
# [{'operation': 'rebin', 'parameters': {'axis': 'energy', 'bins': [10.0, ...], 'reduction': 'mean'}}]
```

The history is carried into `quicklook()` records and into the Store manifest (`parameters.operations`) written by `write_parquet()`.
`sel`, `isel`, `mean`, and `where` update the dimensions but do not add history entries.

## Convert to tables

| Call | Returns |
|---|---|
| `to_xarray()` | `xarray.DataArray` |
| `to_polars(layout=...)` | `polars.DataFrame` |
| `to_pandas(layout=...)` | `pandas.DataFrame` |

`layout` sets the table shape.

| `layout` | Shape |
|---|---|
| `"auto"` (default) | `"array"` for three or more dimensions, otherwise `"long"` |
| `"array"` | One row per time; the remaining dimensions go into one `pl.Array` column |
| `"long"` | Fully expanded long table with one column per dimension coordinate |

`"long"` has one row per element, so a full day of PACE `time × energy × look` becomes very large.
By default more than ten million rows raise an error. Change the limit with `max_rows`, or lift it with `allow_large=True`.
For instrument-level PACE results, `esa1.to_polars("counts", reduce_look="sum")` sums over `look` first.

## Save to Parquet

Save one array as a Store dataset with `write_parquet`.

```python
record = coarse.write_parquet(store, dataset_id="analysis.esa1.coarse_flux", layer="features")
record.scan().collect()
```

A manifest, schema, and catalog are written with it, and `store.scan_dataset(...)` reads it back.
Writing stops if the dataset exists; pass `overwrite=True` to replace or `append=True` to add.
For long periods saved per day, [Batch Pipelines](pipeline.md) fits better.
Which Store layer to use is described in [Storing Data](store.md).
