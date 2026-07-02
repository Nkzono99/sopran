# Load KAGUYA ESA1

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")

counts = kg.esa1.counts.load(time)
array = counts.to_xarray()
```

Use `plan()` first to inspect expected public paths:

```python
kg.esa1.counts.plan(time)
kg.esa1.select("2008-01-01").remote_files()
```

If the local raw file is missing and `download="never"` is used, the current
loader returns an empty schema-backed dataset.
