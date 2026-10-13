# SOPRAN

SOPRAN (Satellite Observation Package for Retrieval, Analysis, and Navigation) is the
Python package for retrieving, storing, analyzing, and visualizing spacecraft observations around the Moon.
KAGUYA/SELENE, ARTEMIS, Lunar Prospector, and OMNI observations, and lunar terrain, magnetic, and illumination maps, all use the same calling style.

```python
import sopran as spn

spn.config.use(store="/path/to/sopran_data")   # where data is kept
time = spn.day("2008-02-01")

spn.kaguya.esa1.energy_flux.plot(time)          # retrieve, calibrate, and plot in one line
flux = spn.kaguya.esa1.energy_flux.load(time)   # load as an array for analysis
```

`spn.kaguya.esa1.energy_flux` means "electron energy flux measured by PACE ESA1 on KAGUYA".
Names follow mission, instrument, and physical quantity, so walking the attributes shows what the data is and how it is organized.
Loaded values carry units, coordinate frames, time and energy bins, and source files,
and those appear directly on plot axes and colorbars.

!!! note "Development status"
    SOPRAN is at an early stage (Pre-Alpha). The public API may change.
    The support table in the [data overview](data/index.md) shows what is implemented.

## How to read these docs

If you are new, read the four "Getting Started" pages in order. They take you from retrieving data
to saving a plot together with its analysis conditions. The other pages are references to look up when you need them.

| You want to | Read |
|---|---|
| Install and run something | [Installation](start/install.md) → [First Plot](start/quickstart.md) |
| Know which data exists, its units, and its caveats | [Data overview](data/index.md) and the mission pages |
| Slice, reduce, or convert loaded arrays to tables | [Working With Arrays](guide/arrays.md) |
| Stack several instruments on a shared time axis | [Plotting](guide/plotting.md) |
| Repeat analyses on the same period and region, and record conditions | [Time, Regions, And Cases](guide/views-cases.md) |
| Choose where data is stored, work offline | [Configuration](guide/configuration.md), [Storing Data](guide/store.md) |
| Align times for statistics or machine learning | [Time Alignment](guide/alignment.md) |
| Process long periods into daily Parquet | [Batch Pipelines](guide/pipeline.md) |
| Look up arguments and types | [Python API](reference/api.md), [Glossary](reference/glossary.md) |
| Use experimental electron reflectometry (ER) or wave-candidate APIs | [Experimental](experimental/index.md) |
| Contribute to SOPRAN | [Design Principles](development/design.md), [Setup And Checks](development/setup.md) |

## Supported data

| Entry point | Main data | Details |
|---|---|---|
| `spn.kaguya` | PACE (electrons, ions), LMAG (magnetic field), LRS (radio and plasma waves), orbit geometry | [KAGUYA](data/kaguya/index.md) |
| `spn.artemis` | P1/P2 FGM magnetic field, ESA ion and electron fluxes and moments | [ARTEMIS](data/artemis.md) |
| `spn.lunar_prospector` | MAG (field, position), ER (omnidirectional and 3-D electron flux) | [Lunar Prospector](data/lunar-prospector.md) |
| `spn.omni` | Hourly solar wind and geomagnetic indices, plus 1- and 5-minute values (HRO, HRO2) | [OMNI](data/omni.md) |
| `spn.moon` | DEM, surface magnetic field (SVM), solar zenith angle, shadow, magnetic anomaly catalog | [Moon Maps](data/moon/index.md) |

## Questions and bug reports

Send usage questions, documentation errors, and bugs to
[GitHub Issues](https://github.com/Nkzono99/sopran/issues).
Use `Lang` at the top right of each page to switch to Japanese.
