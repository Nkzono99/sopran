# ARTEMIS

ARTEMIS is the NASA mission that has operated two THEMIS probes (P1 = THEMIS-B, P2 = THEMIS-C) in lunar orbit since 2011.
SOPRAN retrieves the daily Level 2 CDF files from NASA SPDF (CDAWeb) and reads the FGM magnetic field and the ESA energy fluxes and moments.
Reading needs `cdflib` and `xarray` (`[artemis]`).

## Variables

| Entry point (same for `p2`) | Dimensions | Units | Contents |
|---|---|---|---|
| `art.p1.fgm.magnetic_field` | `time, component` | nT | Spin-resolution (~3 s) field vector (FGS, GSE). Alias `b` |
| `art.p1.esa.ion_energy_flux` | `time, energy_bin` | eV/(cm^2 s sr eV) | Ion differential energy flux |
| `art.p1.esa.electron_energy_flux` | `time, energy_bin` | eV/(cm^2 s sr eV) | Electron differential energy flux |
| `art.p1.esa.ion_density` | `time` | cm^-3 | Ion density (ground-processed moment) |
| `art.p1.esa.ion_velocity` | `time, component` | km/s | Ion velocity (GSE) |
| `art.p1.esa.electron_density` | `time` | cm^-3 | Electron density |

The energies of the energy fluxes are the per-record coordinate `energy` (`time, energy_bin`, eV).
The L2 energy tables change from record to record, for example with the spacecraft potential correction, so SOPRAN keeps the native bins
instead of forcing one shared axis. Bins missing from a table have NaN energy and are not drawn.

```python
art = spn.artemis
time = spn.period("2011-07-01T06:00", "2011-07-01T08:00")

art.p1.fgm.magnetic_field.plan(time)          # dataset ID and source directories
b = art.p1.fgm.magnetic_field.load(time)
flux = art.p1.esa.ion_energy_flux.load(time)
flux.to_xarray().coords["energy"]             # (time, energy_bin) energy tables

spn.stack(
    art.p1.esa.ion_energy_flux.spectrogram(time),       # per-record energy axis; log color and log y
    art.p1.esa.electron_energy_flux.spectrogram(time),
    art.p1.fgm.magnetic_field.lines(time, components="xyz"),
).plot()
```

## ESA modes

ESA stores each operating mode in separate variables. `mode=` selects one; the default is the continuous `"reduced"` mode.

| `mode` | CDF variables (P1 ions) | Time resolution | Contents |
|---|---|---|---|
| `"reduced"` (default) | `thb_peir_*` | About 3 s | Continuous data with reduced angular resolution |
| `"full"` | `thb_peif_*` | About 2 min (P1 on 2011-07-01) | Data with full angular resolution |
| `"burst"` | `thb_peib_*` | Irregular | Short high-resolution intervals |

```python
art.p1.esa.ion_energy_flux.load(time, mode="full")
art.p1.esa.ion_energy_flux.spectrogram(time, mode="full")
```

## Retrieval and file layout

Source files are daily files named like `thb_l2_fgm_YYYYMMDD_vNN.cdf` under
`https://spdf.gsfc.nasa.gov/pub/data/themis/<thb|thc>/l2/<fgm|esa>/YYYY/`. The version `vNN` can increase with reprocessing,
so SOPRAN picks the newest version for the day from the yearly directory listing. Retrieved files go to the Store's
`raw/artemis/themis/<thb|thc>/l2/<fgm|esa>/YYYY/` with their source and checksum recorded. When the Store already has a file for the day,
SOPRAN does not connect unless `download="always"`.

| `download` | Behavior |
|---|---|
| `missing` (default) | Retrieve files for days that are missing |
| `never` | Never connect; missing days count as gaps |
| `always` | Recheck the listing and retrieve the newest version again |

One day is about 37 MB for FGM and about 12 MB for ESA. When the archive has no file for a day, or `download="never"` and the file is not local,
the default (`missing="empty"`) returns an empty result. `missing="warn"` warns and `missing="error"` raises `DatasetNotFoundError`.

## Interpretation notes

- Only the spin-resolution field (FGS) is read; the higher-rate `fgl` and `fgh` are not. The frame is GSE, and setting a `View` `frame`
  does not rotate it.
- ESA moments are the archive's ground-processed values; spacecraft potential correction and quality flags (`*_data_quality`) are as processed
  by the archive. The quality flags themselves are not read yet.
- Ion velocity is NaN during some intervals (for P1 on 2011-07-01, values exist only from 09:24 to 21:23 UTC).
  The archived velocity can be NaN even when density and other quantities are valid.
- Selenocentric position and the position relative to the lunar wake or the magnetosphere are not attached yet.

Source: [NASA SPDF THEMIS](https://spdf.gsfc.nasa.gov/pub/data/themis/)
