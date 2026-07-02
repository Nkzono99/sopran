# First Analysis

This example uses KAGUYA ESA1 data as the first complete SOPRAN vertical slice.

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")
```

Inspect the endpoint without loading data:

```python
kg.esa1.counts.info()
kg.esa1.counts.plan(time)
kg.esa1.counts.guide()               # Japanese by default
kg.esa1.counts.guide(language="en")  # English guide
```

Load local raw data and convert it:

```python
esa1 = kg.esa1.load(time)
ds = esa1.to_xarray()
counts = esa1.to_polars("counts", reduce_look="sum")
```

Plot a simple stack:

```python
stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy"),
    kg.esa1.quality.load(time).line(),
)

plot_result = stack.plot()
plot_result.fig
```
