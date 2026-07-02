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

## Example

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")

esa1 = kg.esa1.load(time)
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

Calibration tables, energy-angle metadata, and full SPEDAS parity tests are
still planned work.
