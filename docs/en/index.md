# SOPRAN

SOPRAN is the **Satellite Observation Package for Retrieval, Analysis, and
Navigation**. It is a Python-first library for retrieving, normalizing, storing,
visualizing, and comparing lunar and planetary-spacecraft observations.

The main user flow is shortcut navigation through `spn.kaguya` / `spn.moon`,
with `View` carrying the active time range and region during analysis.

```python
import sopran as spn

counts = spn.kaguya.esa1.counts.load(spn.day("2008-01-01"))
counts.quicklook("kaguya_esa1_counts", root="reports", y="energy")

view = spn.view(time=spn.day("2008-01-01"), frame="SSE")
flux = view.kaguya.esa1.energy_flux.load()
```

## Entry Points

| Entry point | Role |
| --- | --- |
| `spn.kaguya` / `spn.artemis` / `spn.moon` | Everyday shortcuts using default config |
| `Kaguya()` / `Artemis()` / `Moon()` | Low-level objects for explicit store/source control |
| `Store()` | Manage raw files, normalized parquet, features, and databases |
| `Project()` | Keep the selected `Store`, artifact root, and project settings together |
| `View()` / `spn.view()` | Bind temporary analysis context such as time, region, and frame |
| `Case()` | Work with saved `View` contexts for reproducible analysis |
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
