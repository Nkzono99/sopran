# ARTEMIS

ARTEMIS operates THEMIS P1 (THEMIS-B) and P2 (THEMIS-C) in lunar orbit.
SOPRAN retrieves the daily Level 2 CDF files from NASA SPDF (CDAWeb) into the Store and reads FGM and ESA quantities.

## Entry points

- `p1.fgm.magnetic_field`: spin-resolution (~3 s) field vector (GSE, nT).
- `p1.esa.ion_energy_flux`, `p1.esa.electron_energy_flux`: differential energy flux.
  The energy is the per-record coordinate `energy` (`time, energy_bin`).
- `p1.esa.ion_density`, `p1.esa.ion_velocity` (GSE), `p1.esa.electron_density`: ground-processed moments.
- `p2` has the same layout. ESA accepts `mode="reduced"` (default), `"full"`, or `"burst"`.

## Example

```python
import sopran as spn

art = spn.artemis
time = spn.period("2011-07-01T06:00", "2011-07-01T08:00")

stack = spn.stack(
    art.p1.esa.ion_energy_flux.spectrogram(time),
    art.p1.fgm.magnetic_field.lines(time, components="xyz"),
)
plot_result = stack.plot()
```

`download=` (`missing`, `never`, `always`) sets the retrieval policy and `missing=` (`empty`, `warn`, `error`) the handling of days without a file.
See the ARTEMIS page of the public documentation for details.
