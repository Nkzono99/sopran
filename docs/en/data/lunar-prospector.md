# Lunar Prospector

Lunar Prospector (LP) was a NASA lunar orbiter from January 1998 to July 1999, carrying a magnetometer (MAG) and an electron reflectometer (ER).
Its ER observations are the origin of electron reflectometry, which estimates the surface magnetic field from how many electrons the
crustal field reflects. SOPRAN reads the daily ASCII tables of the PDS PPI Level 1B data (volumes LP_1201 to LP_1204, 1998-01-16 to 1999-07-29).

## Variables

| Entry point | Dimensions | Units | Contents |
|---|---|---|---|
| `lp.mag.magnetic_field` | `time, component` | nT | 5-s average field (SSE). Alias `b` |
| `lp.mag.magnetic_field_sel` | `time, component` | nT | The same field in SEL |
| `lp.mag.magnetic_field_rms` | `time` | nT | RMS of the field within each 5-s average |
| `lp.mag.position` | `time, component` | km | Spacecraft position from the Moon centre (SSE) |
| `lp.mag.position_sel` | `time, component` | km | The same position in SEL |
| `lp.er.electron_flux` | `time, energy_bin` | 1/(cm^2 s sr eV) | ~80-s (16-spin) omnidirectional differential electron number flux; 15 energies |
| `lp.er.electron_flux_3d` | `time, energy_bin, look` | 1/(cm^2 s sr eV) | 3-D electron distribution; 15 energies x 88 look directions |

Here `lp = spn.lunar_prospector`. Frames follow the PDS labels.

| Frame | Definition |
|---|---|
| SSE (selenocentric solar ecliptic) | X points from the Moon to the Sun; Z is parallel to the northward normal of the ecliptic |
| SEL (selenographic) | Z along the lunar spin axis, X toward 0 degrees longitude; Cartesian |

The ER files name the columns `EFLUX`, but the unit is `CM**-2 * S**-1 * SR**-1 * eV**-1`, a differential number flux.
SOPRAN treats it as a number flux, as the unit says, and names it `electron_flux`.

```python
lp = spn.lunar_prospector
time = spn.period("1998-02-01T00:00", "1998-02-01T06:00")

spn.stack(
    lp.er.electron_flux.spectrogram(time),
    lp.er.electron_flux_3d.spectrogram(time),     # averaged over look directions
    lp.mag.magnetic_field.lines(time, components="xyz"),
).plot()
```

## Energy tables

ER energies are the per-record coordinate `energy` (`time, energy_bin`, eV).
There are two tables (16.7 keV to 39 eV, and 15.9 keV to 7 eV), switched four times from March 1999 on.
SOPRAN picks the table in effect for each record from the switch times in `E_BINS.TAB`. `E_BINS.TAB` is identical in every volume
and is retrieved once.

## 3-D distributions

The `time` of `electron_flux_3d` is the spectrum time (one spectrum per 16 spins); the 15 rows (energies) of the file are gathered into one spectrum.
Per-row values stay as coordinates:

| Coordinate | Dimensions | Contents |
|---|---|---|
| `energy` | `time, energy_bin` | Energy of the row (eV) |
| `record_time` | `time, energy_bin` | Time of the row |
| `theta` | `look` | Detector elevation (deg), fixed values from `THETA.TAB` |
| `phi` | `time, energy_bin, look` | Azimuth (deg) as published; not wrapped to 0–360 degrees (values such as 450 occur) |
| `bx_despun`, `by_despun`, `bz_despun` | `time, energy_bin` | Field in despun spacecraft coordinates (nT) |

Spectra with fewer than 15 rows get NaN for the missing energies.
Pitch angles are not computed yet; they will be added after checking the sign conventions of the look directions (`theta`, `phi`)
against the particle direction in the LP literature.

`spectrogram()` averages the 3-D distribution over look directions before drawing (`reduction="mean"` by default). Pass `reduction="sum"` to add them instead.

## Retrieval and file layout

Source files are `MAyymmdd.TAB`, `ELyymmdd.TAB`, and `3Dyymmdd.TAB` under
`https://pds-ppi.igpp.ucla.edu/volume/<volume>/DATA/<MAG|ER_LO_TS|ER_3DIST>/<YY_MMMON>/`; the volume follows from the date.
Retrieved files go to the Store's `raw/lunar_prospector/pds3/` with the same layout, with their source and checksum recorded.

| Data | Size per day |
|---|---|
| MAG | About 2.6 MB |
| ER (omnidirectional) | About 0.2 MB |
| ER (3-D) | About 24 MB |

Days outside the mission and days without a file at the archive (404) are gaps. The default (`missing="empty"`) returns an empty result,
`missing="warn"` warns, and `missing="error"` raises `DatasetNotFoundError`. Loading only days outside the mission retrieves nothing.

## Interpretation notes

- Missing values use the labels' `MISSING_CONSTANT` (field `999.999`, position `999999.99`, flux `9.999E-99`, and so on) and become NaN.
  Observed zero fluxes stay zero.
- The field and ER values are calibrated by the archive. SOPRAN applies no spacecraft potential correction or background removal to ER.
- The high-rate ER (`ER_HI_TS`, ~5 s, two energies) and the higher-level data (LP_2001) are not read yet.

Source: [PDS PPI Lunar Prospector MAG/ER Level 1B](https://pds-ppi.igpp.ucla.edu/volume/LP_1201/AAREADME.HTM)
