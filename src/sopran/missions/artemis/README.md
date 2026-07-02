# ARTEMIS

ARTEMIS provides lunar-orbiting THEMIS probes P1 and P2 as a mission-first API.
The initial SOPRAN interface focuses on the FGM magnetic field endpoint and the
ESA ion energy flux endpoint, with store-backed normalized parquet loading as
the first backend boundary.

## Endpoints

- `p1.fgm.magnetic_field`: P1 fluxgate magnetic field vector.
- `p2.fgm.magnetic_field`: P2 fluxgate magnetic field vector.
- `p1.esa.ion_energy_flux`: P1 ESA ion differential energy flux.
- `p2.esa.ion_energy_flux`: P2 ESA ion differential energy flux.

## Examples

```python
import sopran as spn

art = spn.Artemis()
time = spn.day("2011-07-01")
plan = art.p1.fgm.magnetic_field.plan(time)
ion_plan = art.p1.esa.ion_energy_flux.plan(time)

stack = spn.stack(
    art.p1.esa.ion_energy_flux.spectrogram(time, y="energy", log_color=True),
    art.p1.fgm.magnetic_field.lines(time, components="xyz"),
)
plot_result = stack.plot()
fig = plot_result.fig
```

`art.example()`, `art.p1.fgm.example()`, `art.p1.esa.example()`, and variable
endpoint `example()` methods return short `GuidePage` snippets for notebook and
terminal use.

## Next Work

- Connect CDAWeb/HAPI discovery and raw download policy.
- Expand store-backed normalized parquet loading.
- Preserve coordinate frame, vector component, and energy-bin metadata.
