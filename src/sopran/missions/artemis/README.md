# ARTEMIS

ARTEMIS provides lunar-orbiting THEMIS probes P1 and P2 as a mission-first API.
The initial SOPRAN interface focuses on the FGM magnetic field endpoint and
keeps the loader as an explicit future backend.

## Endpoints

- `p1.fgm.magnetic_field`: P1 fluxgate magnetic field vector.
- `p2.fgm.magnetic_field`: P2 fluxgate magnetic field vector.

## Examples

```python
import sopran as spn

art = spn.Artemis()
time = spn.day("2011-07-01")
plan = art.p1.fgm.magnetic_field.plan(time)

item = art.p1.fgm.magnetic_field.line(time)
fig = spn.stack(item).plot()
```

## Next Work

- Connect CDAWeb/HAPI discovery and raw download policy.
- Expand store-backed normalized parquet loading.
- Preserve coordinate frame and vector component metadata.
