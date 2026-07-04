# KAGUYA/SELENE

KAGUYA/SELENE は SOPRAN の最初の縦切り実装です。現在は KAGUYA public archive の
local raw cache 探索、PACE ESA1 raw PBF decode、typed data object、parquet pipeline を
中心に整備しています。

## 実装済み

- PACE ESA1/ESA2/IMA/IEA public PBF path planning。
- LMAG public path planning、public `MAG_TS*.dat` の `kg.lmag.load(time)`、
  `kg.lmag.magnetic_field` / `magnetic_field_gse` / `magnetic_field_magnitude`
  endpoint、および `kg.orbit.radial_distance` / `altitude` など LMAG native
  time の geometry 派生 endpoint。
- LRS NPW/WFC public CDF path planning、NPW spectrum、WFC electric-field spectrum、
  gain、mode、power spectral density endpoint と endpoint 単位の Store cache。
- `Store.raw_path("kaguya", "pds3")` 以下の local raw cache lookup と missing file の自動取得。
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
b = kg.lmag.magnetic_field.load(time)
bgse = kg.lmag.magnetic_field_gse.load(time)
bmag = kg.lmag.bmag.load(time)
radius = kg.orbit.radial_distance.load(time, cache="use")
item = kg.lmag.magnetic_field.lines(time, components="xyz")
conn = kg.lmag.magnetic_connection.load(time, cache="use")
sza = kg.orbit.sza.load(time, sun_vector=(1.0, 0.0, 0.0), cache="use")
conn.plot(kind="footpoint")
conn.plot(kind="incidence")

npw = kg.lrs.npw.rx1.load(time, cache="use")
wfc = kg.lrs.wfc.ey_power_spectral_density.load(time, cache="use")
wfc.spectrogram(y="frequency", log_color=True)

esa1 = kg.esa1.counts.load(time)
conn_on_esa1 = conn.resample_like(esa1, method="nearest", tolerance="2s")
```

詳細な data layout、pipeline、保存形式は英語 guide と `SPEC.md` を参照してください。
