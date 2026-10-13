# Exploring Data

The previous page called `spn.kaguya.esa1.energy_flux` directly. This page shows how to find out,
before reading any file, which variables exist and what loading them returns.

## Walking attributes does not read files

`spn.kaguya`, `spn.kaguya.esa1`, and `spn.kaguya.esa1.energy_flux` all describe where data lives.
Getting an attribute never downloads, decodes, or computes anything.
Work starts only when you call a method such as `load()`, `plot()`, or `compute()`.

```python
import sopran as spn

kg = spn.kaguya          # mission
kg.esa1                  # instrument
kg.esa1.energy_flux      # physical quantity (endpoint)
```

These docs call the leaf object that represents a variable an **endpoint**.

## Check before loading

`info()` prints a short description at every level. Endpoints also provide:

```python
ep = spn.kaguya.esa1.energy_flux
time = spn.day("2008-02-01")

ep.info()       # description, dimensions, units, aliases
ep.schema()     # machine-readable dimensions, units, and frame
ep.plan(time)   # source files needed for loading
ep.guide()      # detailed instrument description (Markdown); English with guide(language="en")
ep.example()    # short example you can run
```

`info()` prints:

```text
KAGUYA.ESA1.energy_flux
description: KAGUYA PACE ESA1 differential electron energy flux derived from counts with PACE INFO calibration tables.
dims: ('time', 'energy', 'look')
units: eV/(cm^2 s sr eV)
aliases: eflux, differential_energy_flux
example: kg.esa1.energy_flux.load(time)
```

`dims` are the array dimensions. PACE `look` is the index of a detector viewing direction, not the direction itself.
`aliases` are other names for the same variable; `kg.esa1.eflux` reaches the same endpoint.
The dimensions and units of every variable are listed in [Schemas](../reference/schemas.md).

## What loading returns

An endpoint's `load()` returns one variable as a `SopranArray`.
An instrument's `load()` returns an object that holds several variables measured at the same times.

```python
flux = spn.kaguya.esa1.energy_flux.load(time)   # SopranArray
esa1 = spn.kaguya.esa1.load(time)               # instrument-level result

esa1.counts          # SopranArray
esa1.energy_flux     # SopranArray
esa1.to_xarray()     # xarray.Dataset with all variables
```

A `SopranArray` converts to other libraries' types.

| You want | Call |
|---|---|
| xarray | `flux.to_xarray()`, or `flux.xr` for the underlying `DataArray` |
| Polars | `flux.to_polars()` |
| pandas | `flux.to_pandas()` |

Converting an array with three or more dimensions to Polars gives one row per time by default,
with the remaining dimensions in an array-typed column. Use `layout="long"` for a fully expanded long table.
See [Working With Arrays](../guide/arrays.md) for details.

## Back to source files and native bins

Calibrated or rebinned values alone are not always enough to check an analysis.
SOPRAN results keep the source files and the records as decoded.

```python
esa1.files           # paths of the source files
esa1.pace            # decoded headers and record arrays (None when no file was found)
```

To decode files directly, use `sopran.missions.kaguya.read_pace_pbf(files)`.

## Loading by string ID

Scripts and batch jobs can pass the attribute path as a string.

```python
counts = spn.load("kaguya.esa1.counts", time)   # same as spn.kaguya.esa1.counts.load(time)
```

The ID starts with a registered data source: `kaguya`, `artemis`, `omni`, or `moon`.

## Next

When repeating the same period gets tedious, continue with [Reproducible Analysis](reproducible.md).
