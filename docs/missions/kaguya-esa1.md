# KAGUYA PACE ESA1

PACE ESA1 is the KAGUYA electron spectrum analyzer used as the SOPRAN v0.1
reference instrument.

## Variables

- `counts`: raw count matrix with dimensions `time`, `energy`, `look`.
- `quality`: record quality flag with dimension `time`.
- `energy_flux`: placeholder with the same dimensions as `counts`; calibration
  is not applied yet.

For PBF type `0x01`, SOPRAN maps the record count array from `(32, 4, 16)` to
`(energy=32, look=64)`.

PACE calibration table support is available at the low-level reader boundary:

```python
from sopran.missions.kaguya import PaceCalibration, read_pace_fov, read_pace_info

cal = PaceCalibration(
    fov=read_pace_fov(["esas1-ch_angle", "esas1-pol_angle-RAM0"]),
    info=read_pace_info(["ESA-S1_ENE_POL_AZ_GFACTOR_4X16_20090828.dat"]),
)
cal.coverage("ESA1")
```

This only loads the published FOV / INFO arrays. Applying those arrays to
produce physical `energy_flux`, calibrated energy coordinates, and look-angle
coordinates is still planned work.

## Example

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")

esa1 = kg.esa1.load(time)
esa1.info()
ds = esa1.to_xarray()
frame = esa1.to_polars("counts", reduce_look="sum")
record = esa1.write_parquet(store, variable="counts", reduce_look="sum")
```

The same example text is available from Python:

```python
kg.esa1.example()
kg.esa1.counts.example()
```

## Current Limits

Energy-angle metadata application, physical energy-flux calibration, and full
SPEDAS parity tests are still planned work.
