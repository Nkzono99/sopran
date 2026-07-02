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

Use `download="missing"` or configure `Kaguya(download="missing")` when SOPRAN
should fetch missing public PDS3 files into `Store.raw_path("kaguya", "pds3")`.
Downloaded files are registered with a neighboring `<filename>.sopran.json`
manifest, so `store.raw_file(...)` can verify the checksum and
`store.raw_files(refresh=True)` can index the raw inputs.
