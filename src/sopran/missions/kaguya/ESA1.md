# PACE ESA1

PACE ESA1 is the KAGUYA electron spectrum analyzer currently used as the
SOPRAN v0.1 reference instrument.

## Data Product

The current reader handles local PACE PBF records and exposes raw counts as:

- `counts`: raw count matrix with dimensions `time`, `energy`, `look`.
- `quality`: record quality flag with dimension `time`.
- `energy_flux`: placeholder with the same dimensions as `counts`; calibration
  is not applied yet.

For PBF type `0x01`, SOPRAN maps the record count array from `(32, 4, 16)` to
`(energy=32, look=64)`.

## Examples

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
esa1 = kg.esa1.load(spn.day("2008-01-01"))

ds = esa1.to_xarray()
frame = esa1.to_polars("counts", reduce_look="sum")
record = esa1.write_parquet(store, variable="counts", reduce_look="sum")
```

## Next Work

- Port ESA1 calibration tables and energy/angle metadata.
- Add SPEDAS parity tests for representative PBF record types.
- Preserve look-angle coordinates instead of integer placeholder bins.
