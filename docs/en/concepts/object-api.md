# Object API

SOPRAN avoids global state. Users navigate objects to reach a variable endpoint.

```python
kg = spn.Kaguya()
kg.esa1.counts
kg.lmag.magnetic_field

art = spn.Artemis()
art.p1.fgm.magnetic_field
```

Attribute access does not download, decode, scan, or plot data. Execution starts
at explicit methods.

| Method | Role |
| --- | --- |
| `info()` | Show variables, units, aliases, and next calls |
| `plan(time)` | Inspect files, dataset IDs, and execution intent |
| `load(time)` | Load a typed data object |
| `plot(time)` | Convenience load-and-plot path |
| `schema()` | Inspect dimensions, units, frames, and aliases |
| `guide(language=...)` | Return a Markdown guide for notebooks or terminals |
| `example()` | Return a short runnable example |

## Loaded Data

```python
counts = kg.esa1.counts.load(time)
counts.info()
counts.to_xarray()
counts.to_polars()
counts.to_pandas()
```

Simple xarray operations return another `SopranArray`, preserving schema and
provenance.

```python
band = counts.sel(energy=slice(100, 1000)).mean("energy")
band.quicklook("counts_energy_band")
band.metadata["operations"]
```
