# KAGUYA/SELENE

KAGUYA/SELENE は SOPRAN の最初の縦切り実装です。現在は KAGUYA public archive の
local raw cache 探索、PACE ESA1 raw PBF decode、typed data object、parquet pipeline を
中心に整備しています。

## 実装済み

- PACE ESA1/ESA2/IMA/IEA public PBF path planning。
- LMAG public path planning と public `MAG_TS*.dat` の `kg.lmag.load(time)`。
- `Store.raw_path("kaguya", "pds3")` 以下の local raw cache lookup。
- PACE FOV / INFO calibration table reader と `kg.esa1.load_calibration()`。
- ESA1 typed data object の `to_xarray()`, `to_polars()`, `write_parquet()`。
- `sopran.stack()` 経由の最小 PlotStack 連携。

## 使い方

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")

kg.esa1.counts.plan(time)
counts = kg.esa1.counts.load(time)
lmag = kg.lmag.load(time)
```

詳細な data layout、pipeline、保存形式は英語 guide と `SPEC.md` を参照してください。
