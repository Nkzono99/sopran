# KAGUYA PACE Energy Flux API Design

## Scope

KAGUYA PACE `counts` to physical `energy_flux` conversion becomes the next priority.
The first implementation targets ESA1, while keeping the API and internal seams usable
for ESA2, IMA, and IEA.

This design covers API shape, data flow, error handling, and tests. It does not require
IDL/SPEDAS parity tests.

## Chosen API

Use sibling variable endpoints as the main public API:

```python
counts = kg.esa1.counts.load(time)
flux = kg.esa1.energy_flux.load(time, calibration="auto")

kg.esa1.counts.spectrogram(time, y="energy")
kg.esa1.energy_flux.spectrogram(time, y="energy", calibration="auto")
```

`counts` is the raw decoded product. `energy_flux` is a calibrated physical product.
Both can be plotted with `spectrogram()`, but `spectrogram()` remains a plotting method,
not a calibration boundary.

Loaded instrument data also gets an explicit helper:

```python
esa1 = kg.esa1.load(time, calibration="auto")
flux = esa1.to_energy_flux()
```

This helper is useful when a caller has already loaded decoded PACE data and wants to
avoid a second read.

Pipeline uses an explicit calibration stage:

```python
(
    kg.esa1.pipeline(time)
    .decode()
    .calibrate("energy_flux", calibration="auto")
    .select_variables("energy_flux")
    .write("kaguya.esa1.energy_flux", layer="normalized")
    .run()
)
```

## Alternatives Considered

`kg.esa1.counts.energy_flux.spectrogram()` was rejected because it makes `energy_flux`
look like a display transformation attached to raw counts. In practice it is a separate
physical product with its own schema, calibration metadata, Store dataset identity, and
pipeline output.

Keeping `kg.esa1.energy_flux` as a permanent placeholder was rejected because silent
`NaN` products are easy to misuse in analysis. Placeholder behavior should be retained
only for explicit missing-calibration cases where metadata states the physical validity.

## Data Flow

ESA1 raw PBF decode continues to produce `time x energy x look` counts. Calibration
uses PACE INFO/FOV tables and record metadata to produce an `energy_flux` array with
the same dimensions. The output keeps calibrated energy coordinate metadata when
available and records calibration source and status in xarray attrs, `SopranArray`
metadata, and Store manifests.

The first implementation should use deterministic Python reference logic and synthetic
fixtures. Rust is not part of this milestone.

## Error Handling

`kg.esa1.energy_flux.load(time)` should fail clearly when calibration is required but
unavailable. The message should name the endpoint, say which calibration tables are
missing, and suggest either `calibration="auto"` or loading `counts`.

For compatibility during the transition, explicitly requested placeholder mode may
return all-NaN `energy_flux` with `physical_validity="placeholder"`, but the default
should move toward a calibrated result or actionable error.

## Testing

Tests should stay inside this package:

- synthetic PBF fixture verifies counts decode shape, time, fill handling, and values;
- synthetic INFO/FOV tables verify parser output and calibration lookup;
- synthetic counts plus calibration tables verify hand-computable `energy_flux` values;
- `kg.esa1.energy_flux.load(...).spectrogram(...)` verifies the endpoint path;
- `esa1.to_energy_flux()` verifies loaded-data helper parity with the endpoint;
- pipeline `calibrate("energy_flux")` verifies Store output, schema, manifest, and scan;
- missing calibration verifies an actionable error.

IDL/SPEDAS parity is out of scope for this milestone.

