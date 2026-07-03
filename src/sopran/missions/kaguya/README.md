# KAGUYA/SELENE

KAGUYA/SELENE support is the first SOPRAN vertical slice. The current
implementation focuses on local public archive discovery and PACE ESA1 raw PBF
decode.

## Implemented

- PACE ESA1/ESA2/IMA/IEA public PBF path planning.
- LMAG public path planning and public `MAG_TS*.dat` loading through
  `kg.lmag.load(time)`.
- Local raw cache lookup under `Store.raw_path("kaguya", "pds3")`.
- PACE FOV / INFO calibration table readers and `kg.esa1.load_calibration()`.
- ESA1 typed data object with `to_xarray()`, `to_polars()`, and
  `write_parquet()`.
- Minimal Matplotlib `PlotStack` integration through top-level
  `sopran.stack()`.

## Raw File Layout

Keep provider paths under the raw KAGUYA PDS3 root:

```text
raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/YYYYMMDD/data/IPACE_PBF1_YYMMDD_ESA1_V003.dat.gz
  sln-l-lmag-3-mag-ts-v1.0/nominal/YYYYMMDD/data/MAG_TSYYYYMMDD.dat
```

Use `kg.esa1.select(day).remote_files()` to inspect expected public archive
paths before downloading or copying data into the store.

## Current Limits

PACE calibration tables can be read as `PaceCalibration`, but calibration from
counts to physical energy flux is not implemented yet. ESA1 `energy_flux` is
represented as NaN in decoded xarray output until the tables are applied and
SPEDAS parity tests are ported.

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")
cal = kg.esa1.load_calibration(download="never")
cal.coverage("ESA1")
kg.esa1.load(time, calibration=cal).to_xarray().attrs["calibration"]
```
