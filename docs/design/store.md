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

## Portability And Synchronization

A Store root must survive `rsync` to another machine with a different root path,
and several machines or batch jobs may write shards of the same dataset.

- **Root-relative references.** Manifests, catalogs and sidecars hold root-relative
  POSIX paths. Files outside the Store are external references (checksum, size,
  origin hint) and are never resolved. `Store.file_reference()` builds them.
- **Content-derived variants.** Automatic caches derive `variant_id` from settings
  and input content, never from absolute paths or the installed-package list. For
  SPICE-based geometry the kernels enter as `(name, sha256, size)`.
- **Sidecars are the source of truth.** Every shard `<path>` has
  `<path>.sopran.json` with the catalog row. `catalog.parquet` and `registry/` are
  derived indexes: `DatasetRecord.rebuild_catalog()` merges catalog rows with
  sidecars (sidecars win), and `Store.rebuild()` does this for every dataset.
- **Replace versus append.** `register_dataset()` and non-append writes declare the
  complete shard list and delete sidecars of unlisted shards. Appends, shard
  replacement and status updates never delete other sidecars, so concurrent writers
  lose at most catalog rows, which a rebuild restores.
- **Atomic files.** Shards and metadata are written as `*.sopran-tmp*` and renamed;
  backups are `*.sopran-bak*`. Registries, `cache/` and dataset `work/` directories
  are machine-local. `SYNC_EXCLUDES` lists the patterns.
- **Managed datasets.** `managed=True` marks datasets sopran creates and reuses on
  its own; `sopran-store sync-list` selects them by default.

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
