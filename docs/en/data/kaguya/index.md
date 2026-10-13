# KAGUYA/SELENE

KAGUYA/SELENE is the JAXA spacecraft that orbited the Moon from 2007 to 2009. SOPRAN reads plasma, magnetic field, and radio observations,
and the accompanying orbit geometry, from the PDS3 archive published by JAXA DARTS.

```python
import sopran as spn

kg = spn.kaguya          # or spn.Kaguya(store=..., download=...)
time = spn.day("2008-01-01")

flux = kg.esa1.energy_flux.load(time)
b = kg.lmag.magnetic_field.load(time)
wfc = kg.lrs.wfc.ey_power_spectral_density.load(time)
```

## Instruments and variables

| Entry point | Instrument | Main variables | Page |
|---|---|---|---|
| `kg.esa1`, `kg.esa2` | PACE ESA-S1/S2 (electrons) | `counts`, `energy_flux`, `quality` | [PACE](pace.md) |
| `kg.ima`, `kg.iea` | PACE IMA/IEA (ions) | `counts`, `energy_flux`, `quality` | [PACE](pace.md) |
| `kg.lmag` | LMAG (magnetometer) | `magnetic_field`, `magnetic_field_gse`, `magnetic_field_magnitude`, `magnetic_connection` | [LMAG And Orbit](lmag-orbit.md) |
| `kg.orbit` | Orbit geometry (computed from positions in LMAG files) | `position`, `altitude`, `subpoint`, `sza`, … | [LMAG And Orbit](lmag-orbit.md) |
| `kg.lrs` | LRS (NPW, WFC) | `npw.rx1`, `wfc.ey_power_spectral_density`, … | [LRS](lrs.md) |

Dimensions and units of every variable are listed in [Schemas](../../reference/schemas.md).
`kg.info()` lists the instruments, and `kg.guide()` shows the bundled description.

## Retrieving and placing source files

With `download="missing"` (default), source files missing from the Store are retrieved from the DARTS public archive
and placed under `raw/kaguya/pds3/` with the provider's directory structure.

```text
raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/YYYYMMDD/data/IPACE_PBF1_YYMMDD_<ESA1|ESA2|IMA|IEA>_V003.dat.gz
  sln-l-lmag-3-mag-ts-v1.0/nominal/YYYYMMDD/data/MAG_TSYYYYMMDD.dat
  sln-l-lrs-5-npw-spectrum-v1.0/YYYYMMDD/data/LRS_NPW_V010_YYYYMMDD.cdf
  sln-l-lrs-4-wfc-spectrum-v1.0/YYYYMMDD/data/LRS_WFC_V010_YYYYMMDDhhmmss.cdf
```

To use an archive you already have, place it under this directory with the same structure, or point
`spn.Kaguya(data_root=...)` at the archive root. Check the files needed before loading with `plan(time)`.

```python
kg.esa1.counts.plan(time)                         # source files needed
kg.esa1.select("2008-01-01").remote_files()       # paths at the provider
```

PACE calibration tables come from the same distribution as SPEDAS, and SPICE kernels from NAIF and DARTS.
See [PACE](pace.md) and [Coordinate Frames](../../guide/frames.md).

## Common arguments

KAGUYA endpoints take `download`, `missing` (default `"empty"`), and, for derived products, `cache`.
Their meanings are in the [data overview](../index.md#common-arguments).

## Checking data availability

Before analyzing long periods, `coverage()` shows daily or monthly sample counts and retrieved files.

```python
daily = kg.esa1.counts.coverage(spn.month("2008-02"), freq="day")
```

The columns are explained in [Storing Data](../../guide/store.md#summarize-data-availability).
