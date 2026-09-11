# 実装状況

このページは、通常の利用ドキュメントから進捗・未実装情報を分離して集約する場所です。

## 概要

| 領域 | 現状 | 次の主作業 |
| --- | --- | --- |
| KAGUYA PACE | ESA1/ESA2/IMA/IEA PBF decode、ESA1 energy_flux 較正、exposure 付き pitch angle native binning、Store 保存、pipeline、coverage、quicklook | 較正対象の拡張、内部 validation、look-angle |
| KAGUYA electron reflectometry | paired-count fit、全期間 catalog、profile CI 再計算、blind 再監査、ESA1/ESA2・cadence 検証、official/curved SVM3D 比較 | 時間窓 joint fit、ESA2 geometry/response 監査、独立複数 expert 監査、finite-gyroradius forward validation |
| KAGUYA LMAG/geometry | path planning、`MAG_TS*.dat` load、MOON_ME/GSE magnetic field、`|B|`、MOON_ME/GSE orbit geometry、radial distance、SZA、magnetic connection、Store cache | SPICE-backed Sun geometry、SPEDAS parity |
| KAGUYA LRS | NPW/WFC CDF、PDC-TI/sparse pad、PSD、WFC-H multi-label detector、ridge tracker、run-scoped clustering | 全期間統計、WFC-L取得、外部物理 validation |
| KAGUYA その他 | PACE/LMAG/LRS の一部を実装済み | instrument 固有の較正と実データ parity |
| ARTEMIS | object API、normalized parquet reader skeleton | CDAWeb/HAPI/CDF discovery と raw loader |
| Frames | `FrameContext`、identity transform、SPICE vector 委譲 | SpacePy / Astropy backend |
| Moon maps | `Moon()`, `Region`, DEM GeoTIFF load/download、Tsunakawa SVM load、球面 SZA、SPICE 太陽位置、SZA 閾値 illumination/shadow、terrain-ray shadow | projection、reproject、finite-sun shadow、実データ検証 |
| Rust backend | PACE PBF decode を PyO3 native module として任意 backend 接続 | binning、fit、batch shard 処理 |
| PlotStack | Matplotlib line/spectrogram/histogram quicklook | interactive HTML、datashader、長期 quicklook |
| CI / 型検査 | pytest、compileall、schema docs、ruff、mypy を blocking step として実行 | 型境界の精度向上と strict 対象の拡大 |

## KAGUYA PACE

入っているもの:

- PACE ESA1/ESA2/IMA/IEA raw PBF discovery
- local decode
- Rust/PyO3 native decode backend (`read_pace_pbf(..., backend="rust")`)
- Rust/PyO3 native pitch angle calculation and pitch-bin aggregation
- count pitch spectrum の calibrated/relative exposure coordinate と Store 往復
- ESA1 `energy_flux` の Python reference 較正 (`counts / (integ_t * gfactor * efficiency)`)
- `xarray` / `polars` conversion
- parquet Store 保存
- endpoint pipeline `kg.esa1.energy_flux.pipeline(...).calibrate(...)`
- endpoint coverage `kg.esa1.counts.coverage(..., freq="day"|"month")`
- pipeline `run()` / `scan()` / `collect()`
- Matplotlib quicklook

残っているもの:

- ESA2/IMA/IEA への energy_flux 較正拡張
- energy coordinate / look-angle metadata の保存
- look-angle 座標
- package 内 synthetic / fixture validation の拡充

Rust PACE backend は `sopran._native` PyO3 module として package に同梱されます。record 単位や
配列単位の細かい往復は避け、`read_pace_pbf()` 1 回につき複数 file をまとめて decode してから
Python の `PaceData` に戻します。既定の `backend="auto"` は native module が無い環境では
Python reference に fallback します。
開発環境では repository root で `python -m pip install -e .` または
`python -m maturin develop --release` を実行して native module を入れます。

## KAGUYA electron reflectometry

入っているもの:

- `spn.kaguya.er.effective_field.fit(...)`
- mission 非依存の `spn.ElectronReflectionCounts` / `spn.fit_effective_field(...)`
- exposure 補正付き paired-count beta-binomial 尤度
- `no_edge` / `mirror_only` / `electrostatic` の BIC 比較
- bound 張り付き reject と mirror ratio の profile-likelihood 95% interval
- affected side の `B dot r` による物理選択
- variant 付き Store cache と provenance/schema
- synthetic Monte Carlo と旧 raw-PAD 読み取り smoke
- raw PACE、LMAG、SPICE からの再開可能な日別 archive build
- 473日・55,702行の固定 variant に対する checksum / geometry / 派生量 integrity 検証
- accepted 2,470件の別 workflow 再 fit と profile-likelihood 95% interval
- 月、SZA、count、altitude、spacecraft field の全期間 selection function と時間 block 交差検証
- 70 edge 候補の境界なし blind 再監査
- 固定18日の ESA1/ESA2 相互検証と、2分・native cadence 感度検証
- official Tsunakawa SVM v2 出力5,041点に対する Rust evaluator parity
- 0.5 degree SVM3D shell、曲線 field-line trace、格子感度、正規化 SVM 比較

残っているもの:

- ESA2 look-vector 座標・半球対応・絶対 exposure/response の独立監査
- native count を時間 window で同時に扱う階層 fit と persistence gate
- profile interval と truncation flag の標準 archive への統合
- accepted/poor/no-edge/reject を混ぜた複数 expert blind audit と recall 評価
- finite-gyroradius particle tracing による forward validation
- solar wind / wake / magnetotail / spacecraft potential と独立観測を使う外部検証

`B_eff` は実効 mirror field であり、月面磁場ベクトルではありません。詳細は
[電子反射法による実効磁場](../missions/kaguya/electron-reflectometry.md)、
[推定アルゴリズム](../missions/kaguya/electron-reflectometry-algorithm.md)、
[全期間検証](../missions/kaguya/electron-reflectometry-validation.md)を参照してください。

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

## KAGUYA LRS / WFC-H 波動候補

入っているもの:

- 実CDF `Epoch` へ揃えたspectrum/support flagとsparse pad処理
- 48-bit `wfc_pdc_ti` とraw high/middle/low wordの二層API
- 120秒窓・60秒step、median/MAD背景、7種multi-label候補
- 2--30 / 30--100 kHz独立Viterbi trackerとgap分割
- detector/config/feature/window/event/interval/run IDとeligible `exposure_seconds`
- EventCatalogのUTC/区間/confidence/schema検証、event onset count、exposure rate
- 背景残差PCA + deterministic K-meansのrun-scoped探索cluster
- 2008-01-10、2008-06-14、2008-06-18の実CDF anchor検証

残っているもの:

- 全期間daily shard生成と太陽風・wake geometry・ER文脈との統計検定
- tracker/clusterの人手解釈とselection function
- 8秒級spike用の短時間triage detector
- 自然波動WFC-L waveformの取得経路確認とWFC-H候補との照合

詳細は [KAGUYA LRS/WFC 波動イベント抽出](../missions/kaguya/wfc-waves.md) を参照してください。

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
- `sun_vector` / `subsolar_lon_lat` による球面 SZA raster 計算
- `time=` と `spice_kernels=` による SPICE Sun vector 解決
- SZA 閾値による二値 illumination / shadow raster 計算
- DEM horizon を追う `method="terrain_ray"` shadow raster 計算

残っているもの:

- projection / reproject / bilinear interpolation
- finite-sun / penumbra shadow fraction
- 大規模 DEM 向けの terrain-ray 高速化
- 実 SPICE kernel と公開 DEM による数値検証

## Pipeline / Store

入っているもの:

- Store manifest、schema、catalog、checksum
- endpoint coverage summary の Store cache
- `Store.event_catalog(...)` による curated event table と日別・月別 count
- event ID冪等append、detector-run整合性、eligible exposureによるrate
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

1. KAGUYA electron reflectometry の時間窓 joint fit、ESA2 geometry 監査、独立 blind/forward validation
2. KAGUYA PACE energy coordinate / look-angle metadata と内部 validation
3. KAGUYA LRS/WFC-H の全期間統計・WFC-L照合と LMAG parity
4. ARTEMIS raw discovery と CDF ingest
5. SPICE / SpacePy を使う frame transform
6. Moon projection/reproject と terrain-ray の高速化・実データ検証
