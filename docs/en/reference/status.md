# Status

This page centralizes implementation status and known gaps so normal usage
pages can focus on their own task.

## Overview

| Area | Current state | Next work |
| --- | --- | --- |
| KAGUYA PACE | ESA1/ESA2/IMA/IEA PBF decode, ESA1 energy_flux calibration, exposure-aware native pitch-angle binning, Store writes, pipeline, coverage, quicklook | Broader calibration, internal validation, look-angle metadata |
| KAGUYA electron reflectometry | Paired-count fit, full-period catalog, profile-CI refit, blind re-audit, ESA1/ESA2 and cadence checks, official/curved SVM3D comparison | Time-window joint fit, ESA2 geometry/response audit, independent multi-expert review, finite-gyroradius forward validation |
| KAGUYA LMAG/geometry | Path planning, `MAG_TS*.dat` loading, MOON_ME/GSE magnetic field, `|B|`, MOON_ME/GSE orbit geometry, radial distance, SZA, magnetic connection, Store cache | SPICE-backed Sun geometry and SPEDAS parity |
| KAGUYA LRS | NPW/WFC CDF, PDC-TI/sparse pads, PSD, WFC-H multi-label detector, ridge tracking, run-scoped clustering | Full-period statistics, WFC-L access, external physical validation |
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

## KAGUYA Electron Reflectometry

Implemented:

- `spn.kaguya.er.effective_field.fit(...)`
- Mission-independent `spn.ElectronReflectionCounts` and `spn.fit_effective_field(...)`
- Exposure-corrected paired-count beta-binomial likelihood
- BIC comparison of `no_edge`, `mirror_only`, and `electrostatic`
- Bound-stuck rejection and profile-likelihood 95% mirror-ratio intervals
- Physical affected-side selection from `B dot r`
- Variant-aware Store caching with provenance and schema
- Synthetic Monte Carlo and a read-only legacy raw-PAD smoke test
- Resumable daily archive construction from raw PACE, LMAG, and SPICE inputs
- Checksum, geometry, and derived-value integrity validation on a fixed 473-day, 55,702-row variant
- Independent refits and profile-likelihood 95% intervals for all 2,470 accepted rows
- Full-period selection functions and time-blocked cross-validation
- Boundary-free blind re-audit of 70 edge candidates
- Fixed 18-day ESA1/ESA2 comparison and two-minute/native cadence sensitivity
- Rust evaluator parity at all 5,041 official Tsunakawa SVM v2 positions
- A 0.5 degree SVM3D shell, curved field-line traces, grid sensitivity, and normalized SVM comparisons

Remaining:

- Independent audit of ESA2 look-vector coordinates, hemisphere mapping, and absolute exposure/response
- A hierarchical time-window fit on native counts with an explicit persistence gate
- Integration of profile intervals and truncation flags into the standard archive
- Multi-expert blind review mixing accepted, poor, no-edge, and reject rows, including recall
- Finite-gyroradius particle-tracing forward validation
- External validation with solar-wind, wake, magnetotail, spacecraft-potential, and independent observations

`B_eff` is an effective mirror field, not a lunar-surface magnetic-field vector.
See [Effective Field From Electron Reflectometry](../missions/kaguya/electron-reflectometry.md),
the [estimation algorithm](../missions/kaguya/electron-reflectometry-algorithm.md), and
the [full-period validation](../missions/kaguya/electron-reflectometry-validation.md).

## KAGUYA LRS / WFC-H Wave Candidates

Implemented:

- Epoch-aligned spectra/support flags and sparse-pad handling for real CDFs
- Scalar 48-bit `wfc_pdc_ti` plus raw high/middle/low words
- 120-second/60-second robust-background, seven-label candidate detector
- Separate 2--30 and 30--100 kHz Viterbi tracks with gap splitting
- Stable detector/config/feature/window/event/interval/run IDs and eligible exposure
- Validated EventCatalog writes, onset counts, and exposure-normalized rates
- Run-scoped background-residual PCA and deterministic K-means exploration
- Real-CDF anchors from 2008-01-10, 2008-06-14, and 2008-06-18

Remaining:

- Full-period daily shards and tests against solar-wind, wake geometry, and ER context
- Human interpretation and selection functions for tracks and clusters
- A short-timescale triage detector for eight-second spikes
- A verified public acquisition path for natural-wave WFC-L waveforms

See [KAGUYA LRS/WFC Wave-Event Extraction](../missions/kaguya/wfc-waves.md).

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

1. KAGUYA electron-reflectometry time-window joint fitting, ESA2 geometry audit, and independent blind/forward validation.
2. KAGUYA PACE energy-coordinate/look-angle metadata and internal validation.
3. KAGUYA LRS/WFC-H full-period statistics, WFC-L matching, and LMAG parity.
4. ARTEMIS raw discovery and CDF ingest.
5. SpacePy / Astropy frame transforms.
6. Moon projection/reprojection and terrain-ray performance/real-data validation.

## CI / Typing

Implemented:

- GitHub Actions `ci` workflow
- `pytest`, `compileall`, schema docs checks, and `ruff`
- Blocking `mypy` execution

Remaining:

- Improve typing precision around dynamic loader and plotting backend boundaries
- Refine type-checking scope by optional dependency
