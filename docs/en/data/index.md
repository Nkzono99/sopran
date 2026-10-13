# Data Overview

This page lists the data sources SOPRAN supports and what is implemented for each.
Each data page describes variable dimensions, units, and frames, where the data comes from, how calibration and quality are handled, and known limitations.

## Support

| Source | Entry point | Auto retrieval | Loading | Calibration and derived products | Cache | Pipeline |
|---|---|---|---|---|---|---|
| [KAGUYA PACE](kaguya/pace.md) | `spn.kaguya.esa1` etc. | Yes, DARTS | Yes | Energy flux, pitch-angle spectra | Yes | Yes |
| [KAGUYA LMAG and orbit](kaguya/lmag-orbit.md) | `spn.kaguya.lmag`, `spn.kaguya.orbit` | Yes, DARTS | Yes | Orbit geometry, solar zenith angle, field-line connection | Yes | — |
| [KAGUYA LRS](kaguya/lrs.md) | `spn.kaguya.lrs` | Yes, DARTS | Yes | Electric field level, power spectral density | Yes | — |
| [ARTEMIS](artemis.md) | `spn.artemis` | ○ SPDF | ○ | — | Source files only | — |
| [OMNI](omni.md) | `spn.omni` | Yes, SPDF | Yes | Matching to observation times | Source files only | — |
| [Moon maps](moon/index.md) | `spn.moon` | DEM only | Yes | Solar zenith angle, illumination, shadow | — | — |
| [Magnetic anomaly catalog](moon/magnetic-anomalies.md) | `spn.moon.magnetic_anomalies()` | Not needed (bundled) | Yes | — | — | — |

"Auto retrieval" means that with `download="missing"` (the default) missing source files are retrieved into the Store's `raw/`.
"Cache" means computed results can be kept in the Store with `cache="use"` ([Storing Data](../guide/store.md)).

Research prototypes (electron reflectometry, wave-candidate extraction) are kept apart from the regular entry points in [Experimental](../experimental/index.md).

## Common arguments

Time-series endpoints share these arguments.

| Argument | Values | Meaning |
|---|---|---|
| `time` | `TimeRange` | Time range; can be omitted when called through a `View` or `Case` |
| `download` | `"missing"`, `"never"`, `"always"` | Source file retrieval policy ([Configuration](../guide/configuration.md#download-policy)) |
| `missing` | `"empty"`, `"warn"`, `"error"` | When source files are missing: return an empty result, warn and return, or raise |
| `cache` | `"use"`, `"refresh"`, `"never"` | Reuse of computed results (derived products only) |

KAGUYA endpoints take `missing`, with default `"empty"`. Missing source files therefore do not raise;
when processing long periods, set `missing="warn"` or `"error"` so gaps are not overlooked.

## Missing values and zeros

SOPRAN keeps not-retrieved, not-observed, fill values, and observed zeros distinct.
Fill values are converted to NaN according to each data specification (PACE `65535`, LRS CDF pad values, OMNI per-variable fill values, …),
while observed zero counts stay zero. The rules per data source are on each page.
