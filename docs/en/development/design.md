# Design Principles

These are the criteria for deciding SOPRAN's public API and internal implementation. Check new features and data sources against them.
The rules here are the ones the current implementation follows; decided plans and unimplemented ideas are kept in the last two sections.

## Intended experience

1. **Users learn the structure and meaning of the data while using it, even without prior expertise.** `spn.kaguya.esa1.energy_flux` reads as mission, instrument, and quantity,
   and types, completion, `info()`, units, frames, and time, energy, and viewing bins follow the same structure.
   File formats, distribution servers, and Rust implementation details never leak into quantity names.
2. **One path leads from the standard entry point to a figure.** A short call such as `plot(time)` goes through retrieval, calibration, storage, and reloading
   to a figure whose axes and colorbar show quantities and units. Automation never hides the applied corrections, input files, settings, or processing history,
   and missing data or model misfits are never replaced with other values.
3. **Source files and native bins stay reachable.** Results are not locked into processed values: source files (`files`) and records before calibration,
   rebinning, or time integration (such as PACE `pace`) remain in the loaded result.

## API contract

- **Getting attributes is discovery only.** Mission, instrument, variable, and Moon map attributes return lightweight objects
  and never download, decode, scan, or compute.
- **Work starts at a few well-defined points.** `load()` reads data, `compute()` derives products from inputs, and `plot()` draws figures.
  For pipelines these are `run()`, `collect()`, `scan()`, and `stream()`. An endpoint's `plot(time)` is a convenience that loads data;
  outputs meant to keep their conditions use `quicklook()`.
- **Every level offers the same discovery tools:** `info()` (short description), `guide()` (detailed description), `schema()` (machine-readable definition),
  `plan()` (plan before running), and `example()` (runnable example).
- **Meaningful names are canonical.** Names such as `energy_flux` and `magnetic_field` are the primary form in docs, plot labels, and schemas;
  short names such as `eflux` and `b` are aliases listed by `info()`. Aliases not in the specification are not added.
- **Results carry types, units, frames, times, and bins.** Type boundaries with external libraries are explicit, and `Any` is not chained.
- **Configuration resolves in one place.** Process defaults use `spn.config.use()`, temporary changes `spn.config.using()`,
  and everything else resolves through existing settings, Projects, and Views. Only `resolve_store_roots()` decides the Store root
  and only `resolve_download_mode()` the download policy, so every entry point gets the same result. Creating a Store never changes global settings,
  and no per-instrument global state is introduced.
- **Data sources are added by registration.** Missions and bodies register themselves with `register_source()` in their own packages,
  and `core` never imports missions ([Adding A Data Source](extending.md)).

## Schemas live in code

Variable names, dimensions, units, data types, frames, and aliases are written in code as `InstrumentSchema` and `VariableSchema`.
`info()`, validation (`validate_schema`), the Store's `schema.json`, plot axis labels and default logarithmic scales (`log_scale`, `log_dims`),
and the [Schemas](../reference/schemas.md) page all come from them, which keeps hand-written tables and per-name special cases from drifting.

## Storage and reproducibility

- Processed data is saved and reloaded through the existing product and cache mechanisms. Cache keys come from settings and input content,
  so results under different settings are never reused as the same entry.
- File lookup goes through the Store, layouts, and providers; machine-specific absolute paths are never embedded in the package.
- The Store stays copyable with `rsync`. Manifests and catalogs contain only root-relative paths, and shard sidecars are the source of truth
  ([Moving A Store](../guide/store-sync.md)).
- Missing values, zeros, not-retrieved data, calibration state, and quality flags are kept distinct.
- Schemas of saved datasets change even more carefully than the public API; incompatible changes bump the schema version.

## Dependencies

`import sopran` needs only `numpy` and `pandas`. Mission, map, and plotting dependencies are split into extras by use
and imported lazily on the path that needs them. Each extra lists only packages SOPRAN actually imports,
and `tests/test_project_metadata.py` checks that match. `pyproject.toml` is the source of truth for dependencies and build settings.

## Reuse existing libraries

Time-scale conversion, ephemerides and attitude, standard coordinate transforms, generic CDF and PDS reading, and unit conversion are not reimplemented.

| Area | Library |
|---|---|
| Body and spacecraft geometry, coordinate transforms | `spiceypy` |
| Geospace frames (GSE, GSM, SM) | `spacepy` (planned) |
| CDF | `cdflib` |
| Maps and DEMs | `rasterio` |
| Tables and Parquet | `polars`, `pyarrow` |
| Multidimensional arrays | `xarray` |
| Figures | `matplotlib`, `panel` |

Own implementations are allowed for mission-specific binary decoding, fixes for broken provider metadata, instrument calibrations missing from existing libraries,
and ports to Rust for performance. Even then, add tests against an external library or the official specification.
When matching SPEDAS behavior, record the source, units, and correction conditions ([License And Porting](license.md)).

## Rust extension boundary

Heavy deterministic processing (PACE decoding, pitch-angle binning, ER fits, field-line tracing) is delegated to the bundled Rust extension `sopran._native`.

- Data crosses between Python and Rust in coarse units (file groups, arrays, problems, batches), not per record or per bin.
- Results come back as regular Python types, and everyday APIs never expose the FFI.
- The backend name and settings are recorded for reproducibility and debugging.
- Before porting, small golden outputs are compared with a Python reference implementation or the official specification, and nothing silently falls back to Python.

## Isolating experiments

Unsettled models and analysis steps live in `sopran.experimental`, and the regular API never depends on them. Experiments still get types, units, and tests,
and their Store keys stay separate from regular products. No compatibility aliases or shims are added for unpublished APIs.
Individual research runs, comparison figures, and interpretations go to `working/`, not the public documentation ([Experimental](../experimental/index.md)).

## Package layout

| Location | Role |
|---|---|
| `src/sopran/core/` | Store, configuration, Project/Case/View, data types, Pipeline, plotting, time alignment |
| `src/sopran/missions/` | KAGUYA, ARTEMIS, Lunar Prospector, and OMNI readers, instruments, and product APIs |
| `src/sopran/bodies/moon/` | Moon products such as DEM, shadow, and SVM |
| `src/sopran/frames/`, `src/sopran/maps/` | Coordinate and time conversion, shared map types |
| `src/sopran/experimental/` | Experiments imported explicitly |
| `crates/sopran-native/` | Rust extension `sopran._native` |
| `tests/` | Regression tests built mostly on synthetic data and fixtures |
| `scripts/hpc/` | Supercomputer environment setup and job templates |
| `docs/` | Public documentation ([Writing Documentation](documentation.md)) |

## Exceptions and error messages

All exceptions derive from `SopranError` and also from a standard exception.

| Exception | Also derives from | When |
|---|---|---|
| `ConfigError` | `ValueError` | Invalid configuration value |
| `DatasetNotFoundError` | `LookupError` | Dataset or source file not found |
| `DownloadError` | `OSError` | Retrieval failed |
| `DecodeError` | `ValueError` | File could not be decoded |
| `SchemaError` | `ValueError` | Dimensions, data type, units, or frame do not match the schema |
| `FrameTransformError` | `ValueError` | Missing inputs for a coordinate transform, or unsupported transform |
| `PipelineError` | `RuntimeError` | No pipeline backend, or unsupported operation |
| `BackendError` | `RuntimeError` | Backend unavailable |

Error messages include, where possible, the failing endpoint or dataset ID, the available candidates, the next call to try (`info()` or `plan()`),
and which stage failed: retrieval, decoding, schema, or coordinate transform.

## Planned work

The following items are decided. Each gets its design, following these principles, when work starts.

| Item | Contents | Main work |
|---|---|---|
| Chandrayaan-1 SARA (SWIM, CENA) | PDS3 at ESA PSA. 2008–2009 overlaps KAGUYA, allowing simultaneous comparisons | Only raw counts (EDR) are published, so calibration has to be prepared |
| Wind SWE and MFI | CDF files at CDAWeb; the upstream solar-wind observations behind OMNI | Reuse the ARTEMIS retrieval (newest version from the SPDF listing) |
| LRO Diviner GCP | Surface (bolometric) brightness temperature by local time from PDS, for surface charging and exosphere studies | Return it as a Moon map on a grid with local time |
| Lunar Prospector ER extensions | Pitch angles and the high-rate ER (`ER_HI_TS`) | Add pitch angles after checking the look-direction sign conventions in the literature |
| ARTEMIS extensions | Quality flags and selenocentric position | Read `*_data_quality` for the quality flags |

## Ideas

The following are ideas, not promised.

- Interactive plotting (HoloViews, hvPlot, Datashader) and long-period quicklooks.
- `spacepy` and `astropy` coordinate transform backends.
- Moon map reprojection, shadows with penumbra, and faster `terrain_ray`.
- A mission-independent generic pipeline backend and Rust processing stages.
- Saving PACE viewing-direction and energy coordinate metadata.
