# Status

This page centralizes implementation status and known gaps so normal usage
pages can focus on their own task.

## Overview

| Area | Current state | Next work |
| --- | --- | --- |
| KAGUYA PACE | ESA1/ESA2/IMA/IEA PBF decode, ESA1 energy_flux calibration, native pitch-angle binning, Store writes, pipeline, coverage, quicklook | Broader calibration, internal validation, look-angle metadata |
| KAGUYA LMAG/geometry | Path planning, `MAG_TS*.dat` loading, MOON_ME/GSE magnetic field, `|B|`, MOON_ME/GSE orbit geometry, radial distance, SZA, magnetic connection, Store cache | SPICE-backed Sun geometry and SPEDAS parity |
| KAGUYA LRS | NPW/WFC CDF path planning, spectra, gain/mode, PSD endpoints, and Store cache | SPEDAS parity and real-data numerical checks |
| Other KAGUYA sensors | PACE/LMAG/LRS partial support | Instrument-specific calibration and real-data parity |
| ARTEMIS | Object API and normalized parquet skeleton | CDAWeb/HAPI/CDF discovery and raw loader |
| Frames | `FrameContext`, identity transform, and SPICE vector delegation | SpacePy / Astropy backend |
| Moon maps | `Moon()`, `Region`, DEM GeoTIFF load/download, Tsunakawa SVM load | Projection, reprojection, shadow calculation |
| Rust backend | Optional PACE PBF decode connected through a PyO3 native module | Binning, fitting, batch shard work |
| PlotStack | Matplotlib line/spectrogram/histogram quicklook | Interactive HTML, datashader, long-span quicklooks |
| CI / typing | pytest, compileall, schema docs, ruff, and blocking mypy | Improve type precision at dynamic boundaries and expand strict coverage |

## KAGUYA PACE

Implemented:

- PACE ESA1/ESA2/IMA/IEA raw PBF discovery
- Local decode
- Rust/PyO3 native decode backend (`read_pace_pbf(..., backend="rust")`)
- Rust/PyO3 native pitch-angle calculation and pitch-bin aggregation
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

Remaining:

- Event detectors and coverage-normalized rates
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

## Near-Term Priorities

1. KAGUYA PACE energy-coordinate/look-angle metadata and internal validation.
2. KAGUYA LRS/LMAG real-data numerical checks.
3. ARTEMIS raw discovery and CDF ingest.
4. SpacePy / Astropy frame transforms.
5. Moon projection/reprojection and terrain-aware shadow.
6. PlotStack interactive backend.

## CI / Typing

Implemented:

- GitHub Actions `ci` workflow
- `pytest`, `compileall`, schema docs checks, and `ruff`
- Blocking `mypy` execution

Remaining:

- Improve typing precision around dynamic loader and plotting backend boundaries
- Refine type-checking scope by optional dependency
