# PACE ESA1

PACE ESA1 is the KAGUYA electron spectrum analyzer currently used as the
SOPRAN v0.1 reference instrument.

## Data Product

The current reader handles local PACE PBF records and exposes raw counts as:

- `counts`: raw count matrix with dimensions `time`, `energy`, `look`.
- `quality`: record quality flag with dimension `time`.
- `energy_flux`: placeholder with the same dimensions as `counts`; calibration
  is not applied yet.
- `energy`: PACE ESA1 energy channel index; physical eV/bin-center calibration
  is not applied yet.

For PBF type `0x01`, SOPRAN maps the record count array from `(32, 4, 16)` to
`(energy=32, look=64)`. Use xarray/SOPRAN arrays as the primary dense
representation. Polars/Pandas conversion keeps one row per time sample by
default and stores `counts` as a `pl.Array` column. Request full expansion with
`layout="long"`; ordinary tabular analysis should usually reduce the `look`
dimension first.

## Pitch Angle Spectrum

`pitch_angle_spectrum()` maps PACE look bins back to calibrated `theta`, `phi`
look directions, computes pitch angle against a magnetic-field vector, and
returns a counts-based `time x energy x pitch_angle` array. The `look`
coordinate is not a physical direction by itself; the FOV/INFO calibration
tables are required.

```python
kg = spn.Kaguya()
time = spn.day("2008-01-01")
cal = kg.esa1.load_calibration()
esa1 = kg.esa1.load(time, calibration=cal)

pas = esa1.pitch_angle_spectrum(
    magnetic_field=[1.0, 0.0, 0.0],
    pitch_bins="native",
)
pas.to_xarray()
pas.plot()
pas.pitch_spectrogram(log_color=True)
pas.energy_spectrogram(pitch=(0.0, 30.0), log_color=True)
```

`pitch_bins="native"` uses 16 bins for 4x16 angular records and 32 bins for
16x64 records; mixed days use the larger bin count. A magnetic-field
`SopranArray` in another frame requires a `FrameContext` with `spiceypy` and
the needed SPICE kernels.
`pas.plot()` uses the default `mode="auto"` and returns a two-panel pitch/time
and energy/time overview.

## Raw Count 65535

The JAXA/DARTS PACE format document defines PBF1 ESA count fields as
`USHORT cnt[...]`; for example, ESA type 00 has `cnt[32][16][64]` and type 01
has `cnt[32][4][16]`.

The checked PDS3 label does not declare a `MISSING_CONSTANT = 65535` field.
SOPRAN therefore treats `65535` as a SPEDAS-compatibility normalization rather
than a separately declared PDS label constant. SPEDAS `kgy_read_pbf.pro` notes
that `65535 = uint(-1)` and `4294967295 = ulong(-1)` mean NaN, and
`kgy_esa1_get3d.pro` replaces `cnt eq uint(-1)` with `!values.f_nan`.

References:

- JAXA/DARTS PACE format: https://darts.isas.jaxa.jp/app/pdap/selene/help/en/PACE_Format_en_V01.pdf
- Example PDS3 label: https://data.darts.isas.jaxa.jp/pub/pds3/sln-l-pace-3-pbf1-v3.0/20080802/data/IPACE_PBF1_080802_ESA1_V003.lbl
- SPEDAS `kgy_read_pbf.pro`: https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_read_pbf.pro
- SPEDAS `kgy_esa1_get3d.pro`: https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_esa1_get3d.pro

PACE FOV / INFO calibration tables can be read explicitly:

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")
cal = kg.esa1.load_calibration(download="never")
cal.coverage("ESA1")

esa1 = kg.esa1.load(time, calibration=cal)
esa1.to_xarray().attrs["calibration"]
```

The same readers are also available at the low-level boundary:

```python
from sopran.missions.kaguya import PaceCalibration, read_pace_fov, read_pace_info

cal = PaceCalibration(
    fov=read_pace_fov(["esas1-ch_angle", "esas1-pol_angle-RAM0"]),
    info=read_pace_info(["ESA-S1_ENE_POL_AZ_GFACTOR_4X16_20090828.dat"]),
)
cal.coverage("ESA1")
```

This is only the table-loading boundary. Passing `calibration=cal` records the
coverage metadata as `tables_loaded_not_applied`; applying those tables to
produce physical `energy_flux`, calibrated energy coordinates, and all
look-angle coordinates remains separate planned work. `pitch_angle_spectrum()`
uses the calibration tables for the look directions needed by pitch binning.

## Examples

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
esa1 = kg.esa1.load(spn.day("2008-01-01"))

esa1.info()
ds = esa1.to_xarray()
frame = esa1.to_polars("counts")
summed = esa1.to_polars("counts", reduce_look="sum")
pas = esa1.pitch_angle_spectrum([1.0, 0.0, 0.0])
pas.plot()
item = esa1.counts.spectrogram(y="energy", log_color=True)
record = esa1.write_parquet(store, variable="counts", reduce_look="sum")
```

## Next Work

- Apply ESA1 calibration tables to energy/angle metadata and `energy_flux`.
- Add SPEDAS parity tests for representative PBF record types.
- Preserve look-angle coordinates instead of integer placeholder bins.
