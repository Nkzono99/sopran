# Status

This page centralizes implementation status and known gaps so normal usage
pages can focus on their own task.

## Overview

| Area | Current state | Next work |
| --- | --- | --- |
| KAGUYA ESA1 | PBF decode, Store writes, pipeline, quicklook | Calibration, SPEDAS parity, look-angle metadata |
| KAGUYA LMAG/geometry | Path planning, `MAG_TS*.dat` loading, MOON_ME/GSE magnetic field, `|B|`, MOON_ME/GSE orbit geometry, radial distance, SZA, magnetic connection, Store cache | SPICE-backed Sun geometry and SPEDAS parity |
| KAGUYA LRS | NPW/WFC CDF path planning, spectra, gain/mode, PSD endpoints, and Store cache | SPEDAS parity and real-data numerical checks |
| Other KAGUYA sensors | PACE/LMAG/LRS partial support | Other PACE sensor loaders |
| ARTEMIS | Object API and normalized parquet skeleton | CDAWeb/HAPI/CDF discovery and raw loader |
| Frames | `FrameContext`, identity transform, and SPICE vector delegation | SpacePy / Astropy backend |
| Moon maps | `Moon()`, `Region`, DEM GeoTIFF load/download, Tsunakawa SVM load | Projection, reprojection, shadow calculation |
| Rust backend | Not connected | Decode, binning, fitting, batch shard work |
| PlotStack | Matplotlib line/spectrogram/histogram quicklook | Interactive HTML, datashader, long-span quicklooks |
| CI / typing | pytest, compileall, schema docs, ruff. mypy runs as informational | Burn down mypy errors and make it blocking |

## Near-Term Priorities

1. KAGUYA ESA1 calibration and SPEDAS parity.
2. KAGUYA LRS/LMAG parity tests and other-sensor Store writes.
3. ARTEMIS raw discovery and CDF ingest.
4. SpacePy / Astropy frame transforms.
5. Moon projection/reprojection and terrain-aware shadow.
6. PlotStack interactive backend.

## CI / Typing

Implemented:

- GitHub Actions `ci` workflow
- `pytest`, `compileall`, schema docs checks, and `ruff`
- `mypy` execution as an informational `continue-on-error` step while existing
  annotation debt remains

Remaining:

- Resolve current `mypy` errors
- Make type checking a blocking CI step
