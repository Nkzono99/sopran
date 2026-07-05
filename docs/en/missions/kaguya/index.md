# KAGUYA/SELENE

KAGUYA/SELENE is SOPRAN's first lunar mission API. Navigate mission, instrument,
and variable objects.

```python
kg = spn.Kaguya()
time = spn.day("2008-01-01")

counts = kg.ima.counts.load(time)
b = kg.lmag.magnetic_field.load(time)
bgse = kg.lmag.magnetic_field_gse.load(time)
conn = kg.lmag.magnetic_connection.load(time, cache="use")
sza = kg.orbit.sza.load(time, sun_vector=(1.0, 0.0, 0.0), cache="use")
wfc = kg.lrs.wfc.ey_power_spectral_density.load(time, cache="use")
```

## Endpoints

| Instrument | Endpoint | Use |
| --- | --- | --- |
| `esa1` / `esa2` / `ima` / `iea` | `counts` | PACE raw counts |
| `esa1` / `esa2` / `ima` / `iea` | `energy_flux` | Differential energy flux from PACE INFO tables |
| `esa1` / `esa2` / `ima` / `iea` | `energy` | PACE energy channel index |
| `esa1` / `esa2` / `ima` / `iea` | `quality` | Quality flags |
| `lmag` | `magnetic_field` | Magnetic field in the Moon Mean Earth frame |
| `lmag` | `magnetic_field_gse` | Magnetic field in the GSE frame |
| `lmag` | `magnetic_field_magnitude` | LMAG magnetic-field magnitude `|B|` |
| `lmag` | `magnetic_connection` | Local straight field-line connection to a spherical Moon |
| `lrs` | `npw_rx1`, `npw_rx2` | NPW spectra |
| `lrs` | `wfc_ey_power_spectral_density` | WFC electric-field power spectral density |
| `orbit` | `position` | MOON_ME position on the native LMAG time grid |
| `orbit` | `position_gse` | GSE position on the native LMAG time grid |
| `orbit` | `radial_distance` | Distance from the Moon center |
| `orbit` | `altitude` | Altitude above the spherical Moon radius |
| `orbit` | `subpoint` | Spherical lon/lat subpoint |
| `orbit` | `sza` | Spherical subpoint SZA for an explicit Sun direction vector |

## Derived Geometry And Time Matching

Load derived products on the native LMAG time grid for visualization.
`cache="use"` reads a matching Store variant when it already exists.
Magnetic connection returns `connected_any`, plus/minus connection flags,
footpoint lon/lat, distance, and incidence angle.

```python
frames = spn.FrameContext(spice_kernels=("kaguya.tm",))
conn = kg.lmag.magnetic_connection.load(time, cache="use")
sza = kg.orbit.sza.load(time, sun_vector=(1.0, 0.0, 0.0), cache="use")
position_gse = kg.orbit.position_gse.load(time, cache="use")
position_sse = kg.orbit.position.load(time, frame="SSE", context=frames)
conn.plot(kind="footpoint")
conn.plot(kind="altitude")
conn.plot(kind="incidence")
conn.plot(kind="distance")
```

Use `resample_like` to align derived products to another instrument's actual
time coordinate, such as a PACE spectrum.

```python
ima = kg.ima.counts.load(time)
conn_on_ima = conn.resample_like(ima, method="nearest", tolerance="2s")
```

PACE, LMAG, LRS, and LMAG-backed orbit / magnetic-connection loads accept
`missing="empty"`, `"warn"`, or `"error"` to control behavior when raw files
are absent.

Each endpoint can build a daily or monthly availability summary with
`coverage()`. The result is a Polars DataFrame with `sample_count`,
`finite_sample_count`, `sample_time_count`, `expected_remote_files`, and
`available_source_files`. With `cache="use"`, SOPRAN stores the summary under
`features/<dataset>.coverage/variants/freq_<day|month>` and reuses it later.

```python
daily = kg.esa1.counts.coverage(time, freq="day", cache="use")
monthly = kg.esa1.energy_flux.coverage(
    spn.month("2008-02"),
    freq="month",
    calibration="auto",
    cache="use",
)
```

LRS endpoints also accept `cache="use"`, `"refresh"`, or `"never"`. NPW and raw
WFC products are stored under the `normalized` layer; WFC gain, field, power
spectral density, and decoded mode products are stored under `features`, so repeated
loads over the same coverage can skip CDF decoding. `refresh` regenerates and
overwrites the target dataset for the current time range.

PACE pitch-angle products are handled from the endpoint with
`cache="use"`, `"refresh"`, or `"never"`. `cache="use"` reads a matching Store
variant when it exists; otherwise it creates one under the `features` layer.
Operation metadata is recorded under `parameters.operations` in the Store manifest.

```python
pas = kg.esa1.energy_flux.pitch_angle_spectrum(
    time,
    magnetic_field=[1.0, 0.0, 0.0],
    calibration="auto",
    pitch_bins=[0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0],
    cache="use",
)
item = kg.esa1.energy_flux.pitch_spectrogram(
    time,
    magnetic_field=[1.0, 0.0, 0.0],
    calibration="auto",
    cache="use",
    log_color=True,
)
```

## Raw Path

```text
raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/YYYYMMDD/data/IPACE_PBF1_YYMMDD_<ESA1|ESA2|IMA|IEA>_V003.dat.gz
  sln-l-lmag-3-mag-ts-v1.0/nominal/YYYYMMDD/data/MAG_TSYYYYMMDD.dat
  sln-l-lrs-5-npw-spectrum-v1.0/YYYYMMDD/data/LRS_NPW_V010_YYYYMMDD.cdf
  sln-l-lrs-4-wfc-spectrum-v1.0/YYYYMMDD/data/LRS_WFC_V010_YYYYMMDDhhmmss.cdf
```

WFC CDFs are 2-hour slots, so an odd-hour window such as 01:00-01:30 still
plans the preceding 00:00 file.

## Common Checks

```python
kg.info()
kg.ima.counts.plan(time)
kg.esa1.load_calibration(download="never")
kg.lmag.magnetic_field.lines(time, components="xyz")
kg.lmag.magnetic_field_gse.lines(time, components="xyz")
kg.lmag.magnetic_connection.plot(time, kind="footpoint")
kg.lrs.wfc.ey_power_spectral_density.spectrogram(time, y="frequency", log_color=True)
```

ESA1-specific calibration notes are in [PACE ESA1](esa1.md). Calibration and
SPEDAS parity status is tracked in [Status](../../reference/status.md).
