# KAGUYA/SELENE

KAGUYA/SELENE support is the first SOPRAN vertical slice. The current
implementation focuses on local public archive discovery and PACE raw PBF
decode.

## Implemented

- PACE ESA1/ESA2/IMA/IEA public PBF path planning and spectrum endpoints.
- LMAG public path planning, public `MAG_TS*.dat` loading through
  `kg.lmag.load(time)`, the `kg.lmag.magnetic_field` / `magnetic_field_gse` /
  `magnetic_field_magnitude` endpoints, and native-time derived geometry
  endpoints such as `kg.orbit.radial_distance` and `kg.orbit.altitude`.
- LRS NPW/WFC public CDF path planning, NPW spectra, WFC electric-field spectra,
  gain/mode flags, power spectral-density endpoints, and endpoint-level Store
  cache.
- Local raw cache lookup and missing-file downloads under
  `Store.raw_path("kaguya", "pds3")`.
- PACE FOV / INFO calibration table readers and `load_calibration()`.
- PACE typed data objects with `to_xarray()`, `to_polars()`, and
  `write_parquet()`.
- Minimal Matplotlib `PlotStack` integration through top-level
  `sopran.stack()`.

## Raw File Layout

Keep provider paths under the raw KAGUYA PDS3 root:

```text
raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/YYYYMMDD/data/IPACE_PBF1_YYMMDD_<ESA1|ESA2|IMA|IEA>_V003.dat.gz
  sln-l-lmag-3-mag-ts-v1.0/nominal/YYYYMMDD/data/MAG_TSYYYYMMDD.dat
  sln-l-lrs-5-npw-spectrum-v1.0/YYYYMMDD/data/LRS_NPW_V010_YYYYMMDD.cdf
  sln-l-lrs-4-wfc-spectrum-v1.0/YYYYMMDD/data/LRS_WFC_V010_YYYYMMDDhhmmss.cdf
```

WFC CDFs are 2-hour slots, so an odd-hour window such as 01:00-01:30 still
plans the preceding 00:00 file.

Use `kg.ima.select(day).remote_files()` to inspect expected public archive
paths before downloading or copying data into the store.

LMAG can be loaded either as a typed instrument object or through the normalized
magnetic-field endpoint:

```python
lmag = kg.lmag.load(time)
moon_me = lmag.to_xarray()["magnetic_field_moon_me"]

b = kg.lmag.magnetic_field.load(time)
bgse = kg.lmag.magnetic_field_gse.load(time)
bmag = kg.lmag.bmag.load(time)
radius = kg.orbit.radial_distance.load(time, cache="use")
item = kg.lmag.magnetic_field.lines(time, components="xyz")

conn = kg.lmag.magnetic_connection.load(time, cache="use")
sza = kg.orbit.sza.load(time, cache="use")
sza.plot()
conn.plot(kind="footpoint")
conn.plot(kind="incidence")

ima = kg.ima.counts.load(time)
conn_on_ima = conn.resample_like(ima, method="nearest", tolerance="2s")
```

LRS endpoints expose NPW and WFC products as `SopranArray` objects:

```python
npw = kg.lrs.npw.rx1.load(time, cache="use")
wfc = kg.lrs.wfc.ey_power_spectral_density.load(time, cache="use")
wfc.spectrogram(y="frequency", log_color=True)
```

## Current Limits

PACE calibration tables can be read as `PaceCalibration`. ESA1 counts can be
converted to `energy_flux` with the INFO g-factor tables; the current
calibration is package-internal Python reference code, and SPEDAS parity tests
are still future work.

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")
cal = kg.esa1.load_calibration(download="never")
cal.coverage("ESA1")
kg.esa1.energy_flux.load(time, calibration=cal)
record = (
    kg.esa1.energy_flux.pipeline(time)
    .calibrate(calibration="auto")
    .write("kaguya.esa1.energy_flux", layer="normalized")
    .run()
)
```
