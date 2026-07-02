# Data Store Setup

Use one physical root for raw files, normalized parquet, derived features, and
project database products:

```python
store = spn.Store("F:/sopran_data")
```

KAGUYA PDS3 files should preserve provider paths:

```text
F:/sopran_data/raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz
```

After a parquet write, each dataset has:

```text
dataset.json
schema.json
catalog.parquet
shards/
```

You can scan stored data with Polars:

```python
lazy = store.scan_dataset("kaguya.esa1.counts", layer="normalized")
frame = lazy.collect()
```

Build a registry index when you want to inspect or filter saved datasets:

```python
index = store.datasets(refresh=True)
normalized = store.datasets(layer="normalized")
```
