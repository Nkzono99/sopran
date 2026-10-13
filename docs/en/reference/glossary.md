# Glossary

Terms used throughout this documentation.

| Term | Meaning |
|---|---|
| Endpoint | The leaf object reached by walking mission, instrument, and quantity, such as `spn.kaguya.esa1.energy_flux`. Getting it reads no files; work starts with `load()` or `plot()` |
| `SopranArray` | The array returned by `load()`: an xarray `DataArray` with schema, time range, source files, and processing history attached |
| Schema | Definition of a variable's name, dimensions, units, data type, frame, and aliases (`VariableSchema`, `InstrumentSchema`). Written in code; documentation and validation are generated from it |
| Alias | A short name for the same variable, such as `eflux` for `energy_flux` or `b` for `magnetic_field` |
| Time range (`TimeRange`) | Half-open interval `[start, stop)`; times without a time zone are UTC |
| `View` | Immutable analysis conditions bundling a time range, region, and processing settings |
| `Project` | Working directory per analysis topic that holds `sopran.toml` and outputs |
| `Case` | Analysis conditions saved by name in `sopran.toml` |
| Store | One root directory that keeps source files, intermediate data, and adopted results, separated into layers |
| Layer | A division of the Store: `raw`, `normalized`, `features`, `models`, `databases`, `cache`, `registry` |
| Dataset | One unit of data in the Store with a manifest, schema, catalog, and shards, named by an ID such as `kaguya.esa1.counts` |
| Shard | One Parquet file of a dataset; usually one per day |
| Sidecar | A `*.sopran.json` next to a source file or shard that records checksums and serves as the source of truth for catalogs |
| Manifest | A dataset's `dataset.json`, recording provenance, settings, and inputs |
| Catalog | `catalog.parquet`, an index of shard time ranges, row counts, checksums, and status |
| variant | A storage unit per set of conditions under one dataset ID; its ID is derived from settings and input content |
| managed | Marks datasets that SOPRAN creates and reuses by itself; the default target of synchronization |
| Cache | Keeping computed results in the Store for reuse, controlled by `cache="use"`, `"refresh"`, `"never"` |
| Download policy | How missing source files are retrieved: `missing`, `never`, `always` |
| Provenance | Record of the inputs, settings, and processing behind data or figures, kept in `metadata`, manifests, and figure JSON |
| Processing history (operations) | Record of operations such as `rebin` and `transform` and their arguments, in `metadata["operations"]` |
| Quicklook | A saved figure together with a JSON record of how it was made, created by `quicklook()` |
| `PlotStack` | A figure that stacks panels on a shared time axis; corresponds to SPEDAS `tplot` |
| Native bins | Time, energy, and viewing bins as recorded by the instrument, before calibration or rebinning |
| `look` | Index of a PACE detector viewing direction; not a direction itself, converted to one with the calibration tables |
| Pitch angle | Angle between particle velocity and the magnetic field (0–180°) |
| `FrameContext` | Bundle of SPICE kernels, time scale, and backend used for coordinate transforms |
| SPICE kernel | Data file for NASA NAIF SPICE with time, frame, ephemeris, or attitude information |
| Rust extension | The bundled native module `sopran._native` that handles heavy computation; users never call it directly |
| Experimental API | Research APIs in `sopran.experimental`, without compatibility guarantees |
| Pipeline | Mechanism that arranges retrieval, decoding, and saving stages to process long periods at once |
