# Data Store

`Store` manages raw files, normalized parquet, derived features, and project
databases under one physical root.

```python
store = spn.Store("F:/sopran_data")
```

## Layers

| Layer | Contents |
| --- | --- |
| `raw` | Provider files, with provider names preserved |
| `normalized` | Instrument quantities stored as parquet |
| `features` | Aligned feature tables and derived metrics |
| `models` | Calibration, estimation, or learned model artifacts |
| `databases` | User or project-defined curated products |
| `cache` | Rebuildable temporary files |

## Raw Files

```text
F:/sopran_data/raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz
```

## Parquet Dataset

```text
dataset.json
schema.json
catalog.parquet
shards/
```

```python
lazy = store.scan_dataset("kaguya.esa1.counts", layer="normalized")
frame = lazy.collect()
```

## Discovery

```python
index = store.datasets(refresh=True)
normalized = store.datasets(layer="normalized")
raw_files = store.raw_files(refresh=True, mission="kaguya")
```
