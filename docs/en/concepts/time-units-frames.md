# Time, Units, And Frames

SOPRAN public APIs use half-open UTC intervals: `[start, stop)`.

```python
time = spn.period("2008-02-01", "2008-02-02")
day = spn.day("2008-02-01")
month = spn.month("2008-02")
```

## TimeBins

```python
bins = spn.time_bins(time, cadence="10s", partial="drop")
bins.to_polars()
bins.metadata()
```

| `partial` | Behavior |
| --- | --- |
| `"error"` | Raise when a tail bin is incomplete |
| `"keep"` | Keep the short tail bin |
| `"drop"` | Keep complete bins only |
| `"custom"` | Use explicit bin edges |

## Alignment

```python
features = (
    spn.SampleTable(bins)
    .add(sza, method="nearest", tolerance="5s")
    .add(wave_power, method="max")
    .add(density, method="median")
    .collect(join="inner")
)

matrix = features.to_feature_matrix().select("sza", "wave_power")
```

## FrameContext

```python
frames = spn.FrameContext(
    spice_kernels=("kernels/naif0012.tls",),
    time_scale="utc",
)

b = kg.lmag.magnetic_field.load(time)
b_moon = b.transform("MOON_ME", context=frames)
```

Identity transforms record provenance without requiring SPICE. Non-identity
3-component vector transforms are delegated to `spiceypy`. For frames such as
`SELENE_M_SPACECRAFT`, `MOON_ME`, `SSE`, and `GSE`, pass the required time and
frame kernels through `FrameContext(spice_kernels=...)`. Missing kernels are not
guessed; SOPRAN raises `FrameTransformError`.

```python
vectors_in_spacecraft = frames.transform_vectors(
    [[1.0, 0.0, 0.0]],
    times=["2008-01-01T00:00:00"],
    source_frame="MOON_ME",
    target_frame="SELENE_M_SPACECRAFT",
)
```

SPICE and SpacePy backend status is tracked in [Status](../reference/status.md).
