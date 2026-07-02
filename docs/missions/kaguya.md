# KAGUYA/SELENE

KAGUYA/SELENE is the first SOPRAN vertical slice. The current implementation
focuses on local public archive discovery and PACE ESA1 raw PBF decode.

## Implemented

- PACE ESA1/ESA2/IMA/IEA public PBF path planning.
- LMAG public path planning.
- Local raw cache lookup under `Store.raw_path("kaguya", "pds3")`.
- ESA1 typed data object with `to_xarray()`, `to_polars()`, `to_pandas()`,
  and `write_parquet()`.
- Variable endpoint plotting and `PlotStack` integration.
- Pipeline run, append, replace, scan, and collect for ESA1 counts.
- `example()` pages on `Kaguya`, `kg.esa1`, and ESA1 variable endpoints.

## Raw File Layout

```text
raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/YYYYMMDD/data/IPACE_PBF1_YYMMDD_ESA1_V003.dat.gz
```

Use `kg.esa1.select(day).remote_files()` to inspect expected public archive
paths before downloading or copying data into the store.
