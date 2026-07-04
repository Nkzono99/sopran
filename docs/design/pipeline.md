# SOPRAN Pipeline Spec

Status: draft

Pipeline is the advanced batch/storage API. It is not the beginner-facing API.
The beginner path is object-first:

```python
flux = kg.esa1.energy_flux.load(time)
flux.plot()
```

Pipeline is used for raw download, decode, normalization, parquet generation,
feature generation, database products, quicklook batches, and Rust backend
stages.

## Naming Rules

Variable names are endpoints in the object API:

```python
kg.esa1.energy_flux
```

Pipeline should not use `.energy_flux()` as a primary stage name. Use
`select_variables(...)` for stored variables and `derive(...)` for derived
products.

```python
pipe = (
    kg.esa1
    .pipeline(time)
    .download()
    .decode()
    .normalize()
    .select_variables("energy_flux", "counts", "quality")
    .quicklook("esa1_counts")
    .write("kaguya.esa1.normalized", layer="normalized")
)
```

Derived products:

```python
pipe = (
    kg.esa1
    .pipeline(time)
    .from_normalized()
    .derive("pitch_angle_distribution")
    .write("kaguya.esa1.pitch_angle_distribution", layer="features")
)
```

Rust backends should be large stages taking manifests, catalogs, shard paths,
and JSON config. v0.1 uses Python reference implementations first.

## Quicklook Stage

`quicklook()` records a preview generation stage. The current KAGUYA ESA1
Python backend writes Matplotlib PNG quicklooks and JSON metadata under the
output dataset `preview/` directory after parquet output succeeds.

```python
(
    kg.esa1.pipeline(time)
    .decode()
    .select_variables("counts")
    .quicklook("counts")
    .write("kaguya.esa1.counts", layer="normalized")
    .run()
)
```

The first implementation supports one selected variable and `backend="matplotlib"`.
