# Load KAGUYA ESA1

## Prerequisites

- A `Store` root is configured.
- KAGUYA PDS3 raw files exist, or download policy is allowed.
- Time ranges are half-open: `[start, stop)`.

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")
```

## 1. Inspect

```python
kg.esa1.counts.plan(time)
kg.esa1.select("2008-01-01").remote_files()
```

## 2. Load

```python
counts = kg.esa1.counts.load(time)
array = counts.to_xarray()
table = counts.to_polars()
```

## 3. Plot

```python
counts.quicklook("kaguya_esa1_counts", root="reports", y="energy", log_color=True)
```

## Download Policy

```python
kg = spn.Kaguya(store=store, download="missing")
kg.esa1.counts.load(time)
```

Offline behavior is tracked in [Status](../reference/status.md).
