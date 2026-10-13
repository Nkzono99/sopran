# Lunar Prospector

SOPRAN reads the Lunar Prospector (January 1998 to July 1999) magnetometer (MAG) and electron reflectometer (ER)
Level 1B data from the daily ASCII tables of the PDS PPI node, retrieving tables into the Store when needed.

## Entry points

- `mag.magnetic_field` (SSE), `mag.magnetic_field_sel` (SEL): 5-s magnetic field (nT).
- `mag.magnetic_field_rms`: RMS of the field within each 5-s average.
- `mag.position` (SSE), `mag.position_sel` (SEL): spacecraft position from the Moon centre (km).
- `er.electron_flux`: ~80-s omnidirectional differential electron number flux (15 energies). Energies are the `energy` coordinate.
- `er.electron_flux_3d`: 3-D electron distribution (15 energies x 88 look directions) with `theta`, `phi`, and the despun-spacecraft field as coordinates.

## Example

```python
import sopran as spn

lp = spn.lunar_prospector
time = spn.period("1998-02-01T00:00", "1998-02-01T06:00")

spn.stack(
    lp.er.electron_flux.spectrogram(time),
    lp.mag.magnetic_field.lines(time, components="xyz"),
).plot()
```

See the Lunar Prospector page of the public documentation for details.
