# 実装状況

このページは、通常の利用ドキュメントから進捗・未実装情報を分離して集約する場所です。

## 概要

| 領域 | 現状 | 次の主作業 |
| --- | --- | --- |
| KAGUYA ESA1 | PBF decode、Store 保存、pipeline、quicklook | 較正、SPEDAS parity、look-angle |
| KAGUYA LMAG | path planning、`MAG_TS*.dat` load、magnetic field endpoint | schema 拡張、plot/Store 連携の強化 |
| KAGUYA その他 | PACE/LMAG の一部のみ | LRS、PACE 他 sensor の loader |
| ARTEMIS | object API、normalized parquet reader skeleton | CDAWeb/HAPI/CDF discovery と raw loader |
| Frames | `FrameContext` と identity transform | SPICE / SpacePy backend |
| Moon maps | `Moon()`, `Region`, `SurfacePlan` skeleton | DEM/SVM load、projection、shadow 計算 |
| Rust backend | 未接続 | decode、binning、fit、batch shard 処理 |
| PlotStack | Matplotlib line/spectrogram/histogram quicklook | interactive HTML、datashader、長期 quicklook |

## KAGUYA ESA1

入っているもの:

- PACE ESA1 raw PBF discovery
- local decode
- `xarray` / `polars` conversion
- parquet Store 保存
- pipeline `run()` / `scan()` / `collect()`
- Matplotlib quicklook

残っているもの:

- `energy_flux` の物理較正
- FOV / INFO calibration table の本格適用
- look-angle 座標
- SPEDAS/IDL との golden test

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

残っているもの:

- DEM/SVM raster loading
- projection / reproject / sample
- SPICE 太陽位置
- DEM と球/楕円体形状を考慮した terrain-aware shadow

## Pipeline / Store

入っているもの:

- Store manifest、schema、catalog、checksum
- KAGUYA ESA1 backend
- daily partition
- failed shard status と resume の基礎

残っているもの:

- mission 非依存の generic backend
- provider-native streaming
- Rust stage 接続
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

1. KAGUYA ESA1 calibration / SPEDAS parity
2. KAGUYA LRS/LMAG/他 sensor の loader と Store 保存
3. ARTEMIS raw discovery と CDF ingest
4. SPICE / SpacePy を使う frame transform
5. Moon DEM/SVM load と terrain-aware shadow
6. PlotStack の interactive backend
