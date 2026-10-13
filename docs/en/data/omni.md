# OMNI

NASA OMNI2 combines near-Earth solar wind, interplanetary magnetic field, and geomagnetic indices into hourly values.
SOPRAN reads those hourly values so they can serve as upstream conditions for observations around the Moon.
Yearly text files are retrieved from NASA SPDF when missing and kept in the Store.

Loading needs `xarray` and plotting needs `matplotlib` (both in `[kaguya,viz]`).

```python
import sopran as spn

time = spn.day("2008-05-01")

data = spn.omni.load(time)
data.to_dataframe()          # pandas table of scalar variables indexed by UTC time
data.to_xarray()             # xarray.Dataset that also holds the GSE field vector
data["bz_gsm"]               # SopranArray

spn.omni.pressure.plot(time)
spn.omni.variable("alpha_proton_ratio").plot(time)
```

From a `View`, use `view.omni.pressure.plot()`. For an independent Store and download policy, use
`spn.Omni(store=spn.Store("/path/to/sopran_data"), download="never")`.

## Variables

| Name | Units | Meaning |
|---|---|---|
| `pressure` | nPa | Published solar wind dynamic pressure; not recomputed from density and speed |
| `speed` | km/s | Solar wind speed |
| `density`, `temperature` | cm^-3, K | Proton density and temperature |
| `magnetic_field` | nT | Mean field vector (GSE x/y/z) |
| `b_magnitude` | nT | Mean of the field magnitude; differs from the magnitude of the mean vector |
| `bx_gse`, `by_gse`, `bz_gse` | nT | GSE components |
| `by_gsm`, `bz_gsm` | nT | GSM components |
| `beta`, `alfven_mach`, `magnetosonic_mach` | 1 | Plasma beta and Mach numbers |
| `alpha_proton_ratio` | 1 | Alpha-to-proton number density ratio |
| `electric_field` | mV/m | Published convection electric field index (computed from speed and GSM Bz) |
| `kp` | 1 | Kp index; the file's Kp×10 multiplied by 0.1 |
| `dst`, `ae`, `al`, `au` | nT | Geomagnetic activity indices |
| `imf_spacecraft_id`, `plasma_spacecraft_id` | 1 | IDs of the source spacecraft |
| `imf_sample_count`, `plasma_sample_count` | 1 | Number of samples behind each hourly average |

Common variables have endpoints such as `spn.omni.pressure`; every scalar variable is available through `spn.omni.variable(name)`.

## Matching observation times

```python
upstream = spn.omni.at([
    "2008-05-01T00:10:00Z",
    "2008-05-01T00:59:59Z",
    "2008-05-01T01:00:00Z",
])
```

`at()` returns the hour that contains each time. Above, the first two map to 00:00–01:00 and the last to 01:00–02:00.
Order and duplicates of the input are preserved, with no interpolation or forward filling. The `source_time` column is the matched hour label.
If the hourly record itself is missing the row is `NaT`; if the record exists but a variable holds its fill value, that variable is `NaN`.
Times without a time zone are UTC, and `NaT` input is rejected.

`load(start, stop)` selects hour labels in the half-open interval `[start, stop)`. Starting at 00:30 excludes the 00:00 label;
use `at()` for the upstream conditions at 00:30. Missing values are detected with the official per-variable fill values, and missing hours are never filled in.

## Retrieval

| `download` | Behavior |
|---|---|
| `missing` (default) | Retrieve only years not yet present |
| `never` | No network access; raises `FileNotFoundError` when files are missing |
| `always` | Retrieve again; also used to update the current year |

Downloads use a timeout and a temporary file, and the content and year are verified before the file is replaced. On failure the previous file stays.
Newly retrieved files have their checksum recorded in the Store registry. They live at `raw/omni/omni2_YYYY.dat`.

## 5-minute (HRO) data and the velocity vector

`spn.omni.hro` reads the 5-minute values from the monthly CDAWeb CDF files (`omni_hro_5min_YYYYMM01_v01.cdf`).
They include the solar-wind velocity vector `velocity` (GSE, km/s), absent from the hourly files, and the `bsn_x` and
`timeshift` NASA used for the time shift. Reading needs `cdflib` (in `[kaguya]`). Files live under `raw/omni/hro_5min/YYYY/`.

```python
hro = spn.omni.hro.load(spn.period("2008-04-01", "2008-04-03"))
hro.to_dataframe()                     # vx_gse, vy_gse, vz_gse, speed, density, pressure, bsn_x, ...
hro.velocity                           # SopranArray (time, component) in GSE
hro.at(["2008-04-02T08:34:00Z"], tolerance_seconds=600)   # nearest sample, no interpolation
```

The published $V_y$ has the Earth orbital aberration removed. Add `OMNI_ABERRATION_CORRECTION_KM_S` ($+29.8\,\mathrm{km/s}$)
once when the geocentric flow direction is needed. Times remain the arrival at the bow-shock nose; propagation to the Moon is
handled by the [dHT frame](../experimental/dht.md).

## Interpretation notes

- OMNI describes near-Earth upstream conditions, not a direct measurement of the solar wind at the Moon.
  Additional time shifts to the Moon and whether the Moon is inside the magnetosphere are not handled by this API.
- GSE and GSM values are returned as they are; setting a `View` `frame` does not rotate them.
- 1-minute data, and the full variable sets of the hourly and 5-minute products, are not supported.

Sources: [NASA OMNI specification](https://omniweb.gsfc.nasa.gov/html/ow_data.html),
[NASA SPDF public files](https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/)
