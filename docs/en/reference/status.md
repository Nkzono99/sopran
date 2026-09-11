# Status

This page centralizes implementation status and known gaps so normal usage
pages can focus on their own task.

## Overview

| Area | Current state | Next work |
| --- | --- | --- |
| KAGUYA PACE | ESA1/ESA2/IMA/IEA PBF decode, ESA1 energy_flux calibration, exposure-aware native pitch-angle binning, Store writes, pipeline, coverage, quicklook | Broader calibration, internal validation, look-angle metadata |
| KAGUYA LMAG/geometry | Path planning, `MAG_TS*.dat` loading, MOON_ME/GSE magnetic field, `|B|`, MOON_ME/GSE orbit geometry, radial distance, SZA, magnetic connection, Store cache | SPICE-backed Sun geometry and SPEDAS parity |
| KAGUYA LRS | NPW/WFC CDF, PDC-TI/sparse pads, PSD | WFC-L access and reader validation |
| Other KAGUYA sensors | PACE/LMAG/LRS partial support | Instrument-specific calibration and real-data parity |
| ARTEMIS | Object API and normalized parquet skeleton | CDAWeb/HAPI/CDF discovery and raw loader |
| Frames | `FrameContext`, identity transform, and SPICE vector delegation | SpacePy / Astropy backend |
| Moon maps | `Moon()`, `Region`, DEM GeoTIFF load/download, Tsunakawa SVM load, spherical SZA, SPICE solar geometry, SZA-threshold illumination/shadow, terrain-ray shadow | Projection, reprojection, finite-Sun shadow, real-data validation |
| Rust backend | Optional PACE PBF decode connected through a PyO3 native module | Binning, fitting, batch shard work |
| PlotStack | Matplotlib line/spectrogram/histogram quicklook | Interactive HTML, datashader, long-span quicklooks |
| CI / typing | pytest, compileall, schema docs, ruff, and blocking mypy | Improve type precision at dynamic boundaries and expand strict coverage |

## KAGUYA PACE

Implemented:

- PACE ESA1/ESA2/IMA/IEA raw PBF discovery
- Local decode
- Rust/PyO3 native decode backend (`read_pace_pbf(..., backend="rust")`)
- Rust/PyO3 native pitch-angle calculation and pitch-bin aggregation
- Calibrated/relative exposure coordinates and Store round trips for count pitch spectra
- ESA1 `energy_flux` Python reference calibration with `counts / (integ_t * gfactor * efficiency)`
- `xarray` / `polars` conversion
- Parquet Store writes
- Endpoint pipeline `kg.esa1.energy_flux.pipeline(...).calibrate(...)`
- Endpoint coverage `kg.esa1.counts.coverage(..., freq="day"|"month")`
- Pipeline `run()` / `scan()` / `collect()`
- Matplotlib quicklook

## Pipeline / Store

Implemented:

- Store manifests, schemas, catalogs, and checksums
- Store cache for endpoint coverage summaries
- `Store.event_catalog(...)` for curated event tables and daily/monthly counts
- Idempotent event-ID append, detector-run checks, and eligible-exposure rates

Remaining:

- Mission-independent generic backend
- Provider-native streaming

Remaining:

- Extend energy_flux calibration to ESA2/IMA/IEA
- Preserve energy-coordinate and look-angle metadata
- Expand package-internal synthetic and fixture validation

The Rust PACE backend is coarse-grained and bundled as the `sopran._native`
PyO3 module. `read_pace_pbf()` decodes multi-file inputs in one native call
instead of calling Rust per record or per array. The default `backend="auto"`
falls back to the Python reference implementation when the native module is not
installed.
For development installs, run `python -m pip install -e .` or
`python -m maturin develop --release` from the repository root.

## Experimental

ER models, KAGUYA ER adapters, and wave-candidate/ridge/clustering methods live
in `sopran.experimental`. Standard instrument APIs do not import them.
See [Experimental APIs](../experimental/index.md) for usage and limitations.
Individual research runs and literature reviews are not public library docs.

## KAGUYA LRS

- Epoch-aligned NPW/WFC spectra and support flags
- Separate sparse-pad and observed-zero handling
- Scalar 48-bit `wfc_pdc_ti` and raw high/middle/low words
- PSD units, frequency coordinates, Store persistence, and plotting

Candidate detection is documented under [experimental wave analysis](../experimental/waves.md).

## Maps / Moon

Implemented:

- `spn.Moon()`
- `spn.Region`
- Planning endpoints for DEM/SVM/SZA/shadow/illumination
- Longitude-domain, projection, shape, and area-or-point metadata
- DEM GeoTIFF loading through the `rasterio` backend
- Source metadata and direct download paths for USGS LRO LOLA DEM 118m / SLDEM2015
- Text / npy loading for the Tsunakawa SVM (`LunarSVM_000_02_v02.dat`)
- Default alias from `moon.svm` to `moon.svm_tsunakawa2015`
- Spherical SZA raster computation from `sun_vector` / `subsolar_lon_lat`
- SPICE Sun-vector resolution from `time=` and `spice_kernels=`
- Binary illumination / shadow raster computation from an SZA threshold
- `method="terrain_ray"` shadow raster computation from a DEM horizon

Remaining:

- Projection / reprojection / bilinear interpolation
- Finite-Sun / penumbra shadow fraction
- Terrain-ray acceleration for large DEM rasters
- Numerical validation with real SPICE kernels and public DEM files

## Near-Term Priorities

1. Data-axis, unit, calibration, and missing-value contracts.
2. ARTEMIS raw discovery and CDF ingest.
3. Frame transforms and Moon map projection/performance.
4. Periodic promotion or removal of experimental APIs.

## CI / Typing

Implemented:

- GitHub Actions `ci` workflow
- `pytest`, `compileall`, schema docs checks, and `ruff`
- Blocking `mypy` execution

Remaining:

- Improve typing precision around dynamic loader and plotting backend boundaries
- Refine type-checking scope by optional dependency
