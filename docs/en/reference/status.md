# Status

This page centralizes implementation status and known gaps so normal usage
pages can focus on their own task.

## Overview

| Area | Current state | Next work |
| --- | --- | --- |
| KAGUYA PACE | ESA1/ESA2/IMA/IEA PBF decode, ESA1 energy_flux calibration, Store writes, pipeline, quicklook | Broader calibration, internal validation, look-angle metadata |
| KAGUYA LMAG/geometry | Path planning, `MAG_TS*.dat` loading, MOON_ME/GSE magnetic field, `|B|`, MOON_ME/GSE orbit geometry, radial distance, SZA, magnetic connection, Store cache | SPICE-backed Sun geometry and SPEDAS parity |
| KAGUYA LRS | NPW/WFC CDF path planning, spectra, gain/mode, PSD endpoints, and Store cache | SPEDAS parity and real-data numerical checks |
| Other KAGUYA sensors | PACE/LMAG/LRS partial support | Instrument-specific calibration and real-data parity |
| ARTEMIS | Object API and normalized parquet skeleton | CDAWeb/HAPI/CDF discovery and raw loader |
| Frames | `FrameContext`, identity transform, and SPICE vector delegation | SpacePy / Astropy backend |
| Moon maps | `Moon()`, `Region`, DEM GeoTIFF load/download, Tsunakawa SVM load | Projection, reprojection, shadow calculation |
| Rust backend | Not connected | Decode, binning, fitting, batch shard work |
| PlotStack | Matplotlib line/spectrogram/histogram quicklook | Interactive HTML, datashader, long-span quicklooks |
| CI / typing | pytest, compileall, schema docs, ruff, and blocking mypy | Improve type precision at dynamic boundaries and expand strict coverage |

## KAGUYA PACE

Implemented:

- PACE ESA1/ESA2/IMA/IEA raw PBF discovery
- Local decode
- ESA1 `energy_flux` Python reference calibration with `counts / (integ_t * gfactor * efficiency)`
- `xarray` / `polars` conversion
- Parquet Store writes
- Endpoint pipeline `kg.esa1.energy_flux.pipeline(...).calibrate(...)`
- Pipeline `run()` / `scan()` / `collect()`
- Matplotlib quicklook

Remaining:

- Extend energy_flux calibration to ESA2/IMA/IEA
- Preserve energy-coordinate and look-angle metadata
- Expand package-internal synthetic and fixture validation

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
