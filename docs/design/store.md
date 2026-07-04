# SOPRAN Store Spec

Status: draft

`Store` is the physical data repository layer. It manages raw, normalized,
features, databases, cache, manifests, catalogs, and registries. It does not
own notebooks, figures, scripts, or case definitions; those belong to
`Project`.

## Responsibilities

- Resolve dataset IDs to physical paths.
- Store official raw files with provider paths and checksums.
- Store normalized parquet/arrow/zarr datasets for scan-friendly analysis.
- Store derived analysis features separately from normalized instrument data.
- Maintain `dataset.json`, `catalog.parquet`, `schema.json`, and logs.
- Register user-defined database namespaces and products.
- List registered database products from `database.json`.

## Layers

```text
raw          official source files, provider naming preserved
normalized   decoded and standardized instrument quantities
features     SOPRAN-derived analysis quantities
databases    user/project-defined logical products
registry     dataset and manifest indexes
```

`energy_flux`, `counts`, `quality`, `magnetic_field`, and spacecraft position
belong in `normalized` when they are standard instrument quantities. PAD,
moments, loss-cone fits, wake context, and residual context belong in
`features`.

See [API and Data Store Spec](spec.md) for the public API contract.

## Database Metadata

User-defined database namespaces keep a `database.json` file alongside their
registered products. The API can read that file back for discovery:

```python
db = store.database("lunar_wake")
db.register_product(
    name="event_table",
    schema=kg.esa1.schema(),
    description="hand-curated lunar wake events",
)

products = db.products()
assert products[0].name == "event_table"
```

Existing Store-managed datasets can also be adopted into a database metadata
list without moving their physical shards:

```python
features = aligned.write_dataset(store, "analysis.wake_context")
db.adopt_dataset(features, description="aligned context features")
```
