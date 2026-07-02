# SOPRAN

SOPRAN is the **Satellite Observation Package for Retrieval, Analysis, and
Navigation**. It is being built as a Python-first library for lunar satellite
data analysis, with Rust backends planned for heavier decoding and batch
processing stages.

The current implementation focuses on an end-to-end vertical slice:

- KAGUYA/SELENE PACE ESA1 raw PBF discovery, local decode, `xarray` conversion,
  `polars` conversion, parquet storage, and plotting.
- ARTEMIS FGM object API and store-backed normalized parquet loading.
- A filesystem `Store` with raw, normalized, features, and databases layers.
- A pipeline API for scan, collect, append, replace, and dry-run planning.
- Moon surface product skeletons for DEM, SVM, shadow, and illumination maps.

## Install From A Checkout

```bash
pip install -e .
```

To build this documentation locally:

```bash
pip install -e ".[docs]"
mkdocs serve
```

## Main Entry Points

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
art = spn.Artemis(store=store)
moon = spn.Moon()
```

Use mission objects for instrument data, `Store` for persisted datasets,
`Project`/`Case` for analysis context, and body-first objects such as
`Moon()` for surface products.
