# KAGUYA/SELENE

KAGUYA/SELENE is SOPRAN's first lunar mission API. Navigate mission, instrument,
and variable objects.

```python
kg = spn.Kaguya()
time = spn.day("2008-01-01")

counts = kg.esa1.counts.load(time)
b = kg.lmag.magnetic_field.load(time)
```

## Endpoints

| Instrument | Endpoint | Use |
| --- | --- | --- |
| `esa1` | `counts` | PACE ESA1 raw counts |
| `esa1` | `energy_flux` | Differential energy flux after calibration |
| `esa1` | `quality` | Quality flags |
| `lmag` | `magnetic_field` | Magnetic field in the Moon Mean Earth frame |

## Raw Path

```text
raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/YYYYMMDD/data/IPACE_PBF1_YYMMDD_ESA1_V003.dat.gz
  sln-l-lmag-3-mag-ts-v1.0/nominal/YYYYMMDD/data/MAG_TSYYYYMMDD.dat
```

## Common Checks

```python
kg.info()
kg.esa1.counts.plan(time)
kg.esa1.load_calibration(download="never")
kg.lmag.magnetic_field.lines(time, components="xyz")
```

PACE ESA1 details are in [PACE ESA1](esa1.md). Calibration and SPEDAS parity
status is tracked in [Status](../../reference/status.md).
