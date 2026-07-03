# Status

This page centralizes implementation status and known gaps so normal usage
pages can focus on their own task.

## Overview

| Area | Current state | Next work |
| --- | --- | --- |
| KAGUYA ESA1 | PBF decode, Store writes, pipeline, quicklook | Calibration, SPEDAS parity, look-angle metadata |
| KAGUYA LMAG | Path planning, `MAG_TS*.dat` loading, magnetic-field endpoint | Schema expansion, Store/plot integration |
| Other KAGUYA sensors | PACE/LMAG partial support | LRS and other loaders |
| ARTEMIS | Object API and normalized parquet skeleton | CDAWeb/HAPI/CDF discovery and raw loader |
| Frames | `FrameContext` and identity transform | SPICE / SpacePy backend |
| Moon maps | `Moon()`, `Region`, DEM GeoTIFF load/download, Tsunakawa SVM load | Projection, reprojection, shadow calculation |
| Rust backend | Not connected | Decode, binning, fitting, batch shard work |
| PlotStack | Matplotlib line/spectrogram/histogram quicklook | Interactive HTML, datashader, long-span quicklooks |

## Near-Term Priorities

1. KAGUYA ESA1 calibration and SPEDAS parity.
2. KAGUYA LRS/LMAG/other sensor loaders and Store writes.
3. ARTEMIS raw discovery and CDF ingest.
4. SPICE / SpacePy frame transforms.
5. Moon projection/reprojection and terrain-aware shadow.
6. PlotStack interactive backend.
