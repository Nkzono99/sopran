# ARTEMIS

ARTEMIS is the NASA mission that moved THEMIS probes P1 and P2 into lunar orbit.
SOPRAN provides entry points that follow probe, instrument, and variable, but **source file retrieval and CDF reading are not implemented yet.**
Currently it reads only normalized Parquet that you have saved in the Store.

## Variables

| Entry point | Dimensions | Units | Meaning |
|---|---|---|---|
| `art.p1.fgm.magnetic_field` (same for `p2`) | `time, component` | nT | FGM magnetic field vector; alias `b` |
| `art.p1.esa.ion_energy_flux` | `time, energy` | eV/(cm^2 s sr eV) | ESA ion differential energy flux |

## Loading

```python
art = spn.artemis
time = spn.day("2011-07-01")

art.p1.fgm.magnetic_field.plan(time)       # dataset ID that will be read
b = art.p1.fgm.magnetic_field.load(time)

spn.stack(
    art.p1.esa.ion_energy_flux.spectrogram(time, y="energy", log_color=True),
    art.p1.fgm.magnetic_field.lines(time, components="xyz"),
).plot()
```

`load()` reads datasets such as `artemis.p1.fgm.magnetic_field` in the `normalized` layer.
If the dataset is missing, it raises `DatasetNotFoundError` with instructions on how to create it.
Tables prepared by other means become readable once saved with `Store.write_parquet_dataset(..., layer="normalized")`.

```python
lazy = store.scan_dataset("artemis.p1.fgm.magnetic_field", layer="normalized")
```

## Not yet implemented

Retrieval from CDAWeb or HAPI, CDF reading, and storing frame, component, and energy bin metadata.
