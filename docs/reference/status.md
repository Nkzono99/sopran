# 実装状況

このページは、通常の利用ドキュメントから進捗・未実装情報を分離して集約する場所です。

## 概要

| 領域 | 現状 | 次の主作業 |
| --- | --- | --- |
| KAGUYA PACE | ESA1/ESA2/IMA/IEA PBF decode、ESA1 energy_flux 較正、Store 保存、pipeline、quicklook | 較正対象の拡張、内部 validation、look-angle |
| KAGUYA LMAG/geometry | path planning、`MAG_TS*.dat` load、MOON_ME/GSE magnetic field、`|B|`、MOON_ME/GSE orbit geometry、radial distance、SZA、magnetic connection、Store cache | SPICE-backed Sun geometry、SPEDAS parity |
| KAGUYA LRS | NPW/WFC CDF path planning、spectrum/gain/mode/PSD endpoint、Store cache | SPEDAS parity、実データでの数値検証 |
| KAGUYA その他 | PACE/LMAG/LRS の一部を実装済み | instrument 固有の較正と実データ parity |
| ARTEMIS | object API、normalized parquet reader skeleton | CDAWeb/HAPI/CDF discovery と raw loader |
| Frames | `FrameContext`、identity transform、SPICE vector 委譲 | SpacePy / Astropy backend |
| Moon maps | `Moon()`, `Region`, DEM GeoTIFF load/download、Tsunakawa SVM load | projection、reproject、shadow 計算 |
| Rust backend | 未接続 | decode、binning、fit、batch shard 処理 |
| PlotStack | Matplotlib line/spectrogram/histogram quicklook | interactive HTML、datashader、長期 quicklook |
| CI / 型検査 | pytest、compileall、schema docs、ruff、mypy を blocking step として実行 | 型境界の精度向上と strict 対象の拡大 |

## KAGUYA PACE

入っているもの:

- PACE ESA1/ESA2/IMA/IEA raw PBF discovery
- local decode
- ESA1 `energy_flux` の Python reference 較正 (`counts / (integ_t * gfactor * efficiency)`)
- `xarray` / `polars` conversion
- parquet Store 保存
- endpoint pipeline `kg.esa1.energy_flux.pipeline(...).calibrate(...)`
- pipeline `run()` / `scan()` / `collect()`
- Matplotlib quicklook

残っているもの:

- ESA2/IMA/IEA への energy_flux 較正拡張
- energy coordinate / look-angle metadata の保存
- look-angle 座標
- package 内 synthetic / fixture validation の拡充

## KAGUYA LMAG / geometry

入っているもの:

- `kg.lmag.load(time)` と `kg.lmag.magnetic_field` / `magnetic_field_gse` /
  `magnetic_field_magnitude`
- LMAG native time の `kg.orbit.position`, `position_gse`, `radial_distance`,
  `altitude`, `subpoint`, `sza`
- `kg.lmag.magnetic_connection` の footpoint / distance / incidence angle
- Store variant cache と `resample_like` による ESA1/PACE などへの時刻合わせ

残っているもの:

- SPICE kernel による Sun vector / GSE / SSE の実運用 parity
- SPEDAS/IDL との geometry golden test

## ARTEMIS

入っているもの:

- `spn.Artemis()` object API
- P1/P2 FGM magnetic field endpoint
- P1/P2 ESA ion energy flux endpoint
- normalized parquet が Store にある場合の読み込み導線

残っているもの:

- raw discovery
- CDAWeb/HAPI/CDF download
- CDF loader
- frame、component、energy bin metadata の保存

## Maps / Moon

入っているもの:

- `spn.Moon()`
- `spn.Region`
- DEM/SVM/SZA/shadow/illumination の planning endpoint
- longitude domain、projection、shape、area-or-point metadata
- `rasterio` backend による DEM GeoTIFF load
- USGS LRO LOLA DEM 118m / SLDEM2015 の source metadata と直接 download 導線
- Tsunakawa SVM (`LunarSVM_000_02_v02.dat`) の text / npy load
- `moon.svm` から `moon.svm_tsunakawa2015` への既定 alias
- 直接 URL が確認できない SVM source の手動取得 guide

残っているもの:

- projection / reproject / bilinear interpolation
- SPICE 太陽位置
- DEM と球/楕円体形状を考慮した terrain-aware shadow

## Pipeline / Store

入っているもの:

- Store manifest、schema、catalog、checksum
- KAGUYA PACE backend
- daily partition
- failed shard status と resume の基礎

残っているもの:

- mission 非依存の generic backend
- provider-native streaming
- Rust stage 接続

## CI / 型検査

入っているもの:

- GitHub Actions の `ci` workflow
- `pytest`、`compileall`、schema docs check、`ruff`
- `mypy` blocking 実行

残っているもの:

- 動的 loader / plotting backend 境界の型精度向上
- optional dependency ごとの型検査範囲整理
- 長期 batch の監査 UI

## 可視化

入っているもの:

- `SopranArray.quicklook()`
- `PlotStack`
- line panel
- spectrogram panel
- histogram panel
- PNG/HTML/JSON quicklook

残っているもの:

- HoloViews/hvPlot/datashader
- Panel dashboard
- 長期間 quicklook

## 直近の優先度

1. KAGUYA PACE energy coordinate / look-angle metadata と内部 validation
2. KAGUYA LRS/LMAG の実データ数値検証
3. ARTEMIS raw discovery と CDF ingest
4. SPICE / SpacePy を使う frame transform
5. Moon projection/reproject と terrain-aware shadow
6. PlotStack の interactive backend
