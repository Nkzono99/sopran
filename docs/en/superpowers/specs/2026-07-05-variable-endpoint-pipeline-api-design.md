# Variable Endpoint Pipeline API Design

## Decision

`pipeline()` remains explicit. It marks the boundary from interactive endpoint loading
into lazy batch work with side effects, provenance, shard handling, and resumability.

The main batch API starts from a variable endpoint:

```python
(
    kg.esa1.energy_flux.pipeline(time)
    .calibrate(calibration="auto")
    .write("kaguya.esa1.energy_flux", layer="normalized")
    .run()
)
```

Raw products can also start from their endpoint:

```python
(
    kg.esa1.counts.pipeline(time)
    .write("kaguya.esa1.counts", layer="normalized")
    .run()
)
```

The older instrument-level pipeline remains supported for explicit multi-variable or
instrument-wide flows:

```python
kg.esa1.pipeline(time).decode().select_variables("counts")
```

## Rationale

`esa1.counts.calibrate().map().write()` hides the transition from endpoint discovery to
lazy batch execution. It also makes `energy_flux` look like a display transformation on
counts, even though it is a separate product with its own schema, dataset ID, and
provenance.

An explicit `pipeline()` call follows the same principle as Java streams: the user opts
into lazy staged execution before chaining transformations. Starting from the variable
endpoint keeps the API close to the product identity while preserving that boundary.

## Semantics

`VariableEndpoint.pipeline(time)` creates a `Pipeline` with:

- `source` equal to the endpoint dataset ID, such as `kaguya.esa1.energy_flux`;
- `context` still set to the owning instrument backend;
- a default selected variable equal to the endpoint name.

`Pipeline.calibrate()` may omit its `name` when a default selected variable exists. For
`kg.esa1.energy_flux.pipeline(time).calibrate(calibration="auto")`, the stage is stored
as `calibrate(name="energy_flux", calibration="auto")`.

`write(...)` does not start execution. `.run()`, `.scan()`, `.collect()`, and `.stream()`
remain execution boundaries.

