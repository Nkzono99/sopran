# KAGUYA/SELENE

KAGUYA/SELENE is the first SOPRAN vertical slice. The current implementation
focuses on local public archive discovery and PACE ESA1 raw PBF decode.

## Implemented

- PACE ESA1/ESA2/IMA/IEA public PBF path planning.
- LMAG public path planning and public `MAG_TS*.dat` loading through
  `kg.lmag.load(time)`.
- Local raw cache lookup under `Store.raw_path("kaguya", "pds3")`.
- Mission default download policy via `Kaguya(download=...)`,
  `SOPRAN_DOWNLOAD_MODE`, and `SOPRAN_OFFLINE`.
- Raw downloads into the default Store cache write `<filename>.sopran.json`
  manifests with DARTS/PDS3 provider path, URL, version, checksum, byte size,
  and acquisition time.
- ESA1 typed data object with `to_xarray()`, `to_polars()`, `to_pandas()`,
  and `write_parquet()`.
- PACE FOV / INFO calibration table readers via `read_pace_fov()`,
  `read_pace_info()`, `PaceCalibration`, and `pace_calibration_remote_files()`.
- ESA1 mission API helpers `kg.esa1.calibration_files()` and
  `kg.esa1.load_calibration()`.
- Variable endpoint plotting and `PlotStack` integration.
- Pipeline run, append, replace, scan, collect, and per-run download policy
  override for ESA1 counts.
- ESA1 unknown variable errors use schema aliases to suggest canonical
  variables and next `info()` / `load()` calls.
- ESA1 missing-time errors show examples for the exact instrument or variable
  endpoint that was called.
- `example()` pages on `Kaguya`, `kg.esa1`, and ESA1 variable endpoints.
- Bilingual package guides via `kg.guide(language="ja")`,
  `kg.guide(language="en")`, and `kg.esa1.guide(language=...)`.

## Raw File Layout

```text
raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/YYYYMMDD/data/IPACE_PBF1_YYMMDD_ESA1_V003.dat.gz
```

Use `kg.esa1.select(day).remote_files()` to inspect expected public archive
paths before downloading or copying data into the store.

LMAG public files use the same raw root:

```text
raw/kaguya/pds3/
  sln-l-lmag-3-mag-ts-v1.0/nominal/YYYYMMDD/data/MAG_TSYYYYMMDD.dat
```

```python
lmag = kg.lmag.load(time)
ds = lmag.to_xarray()
ds["magnetic_field_moon_me"]
```

## Calibration Status

PACE calibration tables can be read and represented, but ESA1 `energy_flux` is
still not computed from counts in `kg.esa1.load(...).to_xarray()`. The next
step is to connect the FOV / INFO tables to energy coordinates, look-angle
coordinates, geometric factors, and SPEDAS golden tests.

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")
cal = kg.esa1.load_calibration(download="never")
cal.coverage("ESA1")
kg.esa1.load(time, calibration=cal).to_xarray().attrs["calibration"]
```
