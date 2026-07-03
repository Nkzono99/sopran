# SOPRAN

SOPRAN is the **Satellite Observation Package for Retrieval, Analysis, and
Navigation**. It is a Python-first library for retrieving, normalizing, storing,
visualizing, and comparing lunar and planetary-spacecraft observations.

The main user flow is object navigation by mission, instrument, and variable.

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
moon = spn.Moon()

time = spn.day("2008-01-01")
counts = kg.esa1.counts.load(time)
counts.quicklook("kaguya_esa1_counts", root="reports", y="energy")
```

## Entry Points

| Entry point | Role |
| --- | --- |
| `Kaguya()` / `Artemis()` | Navigate missions, probes, instruments, and variables |
| `Store()` | Manage raw files, normalized parquet, features, and databases |
| `Project()` / `Case()` | Keep analysis time ranges, regions, defaults, and artifacts together |
| `Moon()` | Work with DEM, SVM, SZA, shadow, and illumination maps |
| `spn.stack()` | Build SPEDAS/tplot-like stacked time-series views |

## Data Flow

```text
provider raw files
  -> Store.raw
  -> decode / normalize
  -> Store.normalized parquet
  -> PlotStack quicklook
  -> time_bins / SampleTable
  -> Store.features or Store.databases
```

## Next

- [Installation](getting-started/installation.md)
- [First Analysis](getting-started/first-analysis.md)
- [KAGUYA/SELENE](missions/kaguya/index.md)
- [Status](reference/status.md)
