# Coordinate Frames

Vector quantities (magnetic field, position) carry their frame in the schema. For example, LMAG `magnetic_field` is in `MOON_ME`
and `magnetic_field_gse` in `GSE`. Transforms to other frames are explicit with `transform()`, and the conditions used,
such as SPICE kernels, are collected in a `FrameContext` and kept as provenance.

## Transform

```python
# pass kernels (here a meta-kernel) that define both the source and target frames
frames = spn.FrameContext(spice_kernels=("kernels/kaguya.tm",))

b = spn.kaguya.lmag.magnetic_field.load(time)        # MOON_ME
b_sc = b.transform("SELENE_M_SPACECRAFT", context=frames)
b_sc.metadata["operations"]                           # record of source, target, backend, and kernels
```

Arrays of three-component vectors with times can be transformed directly.

```python
frames.transform_vectors(
    [[1.0, 0.0, 0.0]],
    times=["2008-01-01T00:00:00"],
    source_frame="MOON_ME",
    target_frame="SELENE_M_SPACECRAFT",
)
```

From a `View`, `view.frame_context()` uses the SPICE kernels, time scale, and backend set on the view.

## Transform rules

- A transform to the same frame is recorded as an identity transform.
- Transforms between different frames currently use `spiceypy` (SPICE). Pass a leap-second kernel and the frame kernels and
  ephemerides that define both frames in `spice_kernels`. If something is missing, SOPRAN stops with `FrameTransformError` instead of guessing.
  `SSE` and `GSE` are not in NAIF's generic kernels, so they need a frame kernel that defines them.
- Transforms among `GSE`, `GSM`, and `SM` are planned to use `spacepy` and are not implemented.
  `frames.plan("GSE", "GSM")` reports `status` `"planned"`, and attempting the transform raises `FrameTransformError`.

`frames.plan(source, target)` returns the selected backend and status (`applied`, `implemented`, `planned`) without running anything.
`frames.metadata()` separates the backends installed in the environment (`available_backends`) from those SOPRAN treats as implemented (`implemented_backends`).

You normally do not choose a backend. Fix one only when the research requires it, with `FrameContext(default_backend="spiceypy")`
or `project.view(..., backend={"frames": "spiceypy"})`.

## Getting SPICE kernels

When KAGUYA `orbit.sza` gets no kernels and the download policy is not `never`, it fetches NAIF generic kernels
(leap seconds, lunar frames, DE421) into the Store's `raw/spice/kernels/`.
For other transforms, prepare the kernels and pass them to `FrameContext`.
Kernels including KAGUYA attitude are available from `sopran.missions.kaguya.selene_spice_kernels(store, time)`.

## Common frames

| Name | Meaning |
|---|---|
| `MOON_ME` | Moon-fixed Mean Earth/Polar Axis frame |
| `SSE` | Moon-centered Selenocentric Solar Ecliptic frame |
| `GSE` | Earth-centered Geocentric Solar Ecliptic frame |
| `GSM` | Earth-centered Geocentric Solar Magnetospheric frame |
| `SELENE_M_SPACECRAFT` | KAGUYA (SELENE) spacecraft frame; the reference for PACE viewing directions |
