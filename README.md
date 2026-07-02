# SOPRAN

Satellite Observation Package for Retrieval, Analysis, and Navigation.

`SOPRAN` は、衛星観測データの取得、読み込み、解析、可視化、座標変換を Python から
扱うためのライブラリとして作る予定のリポジトリです。まずは KAGUYA/SELENE や
ARTEMIS など、月周辺の衛星データ解析を主対象にします。

## 目標

- ミッションごとに異なるデータ形式や測定器を、共通した使い方で扱えるようにする。
- IDL/SPEDAS で使ってきた解析スクリプトを pure Python + Rust の実装へ移植する。
- Python から読みやすい API を提供しつつ、重い decode、binning、fit、大量 batch 処理は
  Rust backend へ分離する。
- 解析作業で増えた一時コードを、そのまま積み上げず、reader、product、workflow、
  analysis primitive として整理する。

## 初期スコープ

- KAGUYA/SELENE の public data reader と product builder
- ARTEMIS の基本 reader と時系列 product
- SPEDAS/tplot に近い軽量な時系列データモデル
- dataset root / local cache / metadata の共通 resolver
- SPICE を使った時刻・座標系補助
- DEM/SVM などの天体固有 map product、投影、経度表現、region query
- DEM と太陽位置に基づく shadow / illumination product
- Rust による重い処理の backend 化

## 依存関係

SOPRAN は研究・解析環境でそのまま使えることを優先し、KAGUYA/ARTEMIS、SPICE、
SpacePy、MAP/DEM/SVM、Matplotlib/HoloViz 系の runtime backend を標準 dependencies に
含めます。`optional-dependencies` は用途別の目印と開発環境向けに残しています。

```text
pip install sopran
pip install "sopran[full]"
pip install "sopran[dev]"
```

optional extras は `kaguya`, `artemis`, `moon`, `viz`, `geospace`, `full`, `dev` に分けますが、
runtime 系は標準 dependencies にも含めます。

## 現在動く最小 API

KAGUYA ESA1 については、public PBF file discovery、ローカル raw PBF decode、
`xarray`/`polars` 変換、parquet 保存、最小 PlotStack までの縦切りを実装し始めています。

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")

kg.esa1.energy_flux.info()
kg.esa1.energy_flux.plan(time)

esa1 = kg.esa1.load(time)
ds = esa1.to_xarray()
counts = esa1.to_polars("counts", reduce_look="sum")
record = esa1.write_parquet(store, variable="counts", reduce_look="sum")

stack = spn.stack(
    spn.spectrogram(ds["counts"].sum("look"), y="energy"),
    spn.line(ds["quality"]),
)
fig = stack.plot()
```

raw file は `Store.raw_path("kaguya", "pds3")` 以下に public provider path を保って置きます。
たとえば ESA1 の 2008-01-01 は次の配置を探索します。

```text
F:/sopran_data/raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz
```

`kg.esa1.energy_flux` は実データではなく endpoint です。属性アクセスだけでは I/O を起こさず、
実データ取得は `.load(time)`、計算は `.compute(...)`、描画は `.plot(...)` を実行点にします。

解析プロジェクトでは case に時間範囲や既定 frame を持たせます。

```python
prj = spn.Project("projects/lunar_wake")
case = prj.case("wake_20080201")

flux = case.kaguya.esa1.energy_flux.load()
b = case.artemis.p1.fgm.magnetic_field.load()

stack = case.stack(
    case.kaguya.esa1.energy_flux.spectrogram(y="energy"),
    case.kaguya.orbit.altitude.line(),
    case.artemis.p1.fgm.magnetic_field.lines(components="xyz", frame="SSE"),
)
stack.plot()
```

月面 DEM/SVM/shadow/illumination は mission ではなく body-first API を主導線にします。

```python
moon = spn.Moon(project="projects/lunar_wake")
region = spn.maps.Region(lon=(120, 160), lat=(-45, -10), body="moon")

dem = moon.dem.load(source="kaguya.tc.dem", region=region, resolution="512ppd")
shadow = moon.shadow.compute(time="2008-02-01T12:00:00", dem=dem, method="terrain_ray")
shadow.plot(projection="polar_stereographic")
```

## 予定ディレクトリ

```text
src/sopran/
  core/
  missions/
    kaguya/
    artemis/
  bodies/
    moon/
  maps/
  frames/
  analysis/
  plot/
crates/
  sopran-backend/
docs/
tests/
```

ユーザーの解析 workspace は repository 内部の package とは分けて、`projects/lunar_wake/` のように
管理します。

## 旧リポジトリ

以前の作業リポジトリは `F:\idl\lunarsat` にあります。そこには KAGUYA 解析、dataset
layout、Rust backend の試行錯誤が含まれていますが、このリポジトリでは設計を整理し直して
作り直します。

## License

SOPRAN original code and documentation are licensed under Apache-2.0.

SPEDAS/PySPEDAS-derived ports must retain their upstream notices. The current
policy is documented in `THIRD_PARTY_NOTICES.md`: MIT-licensed SPEDAS routines
can be ported with attribution, while GPL/NASA-OSA external components should
not be copied into the Apache-2.0 core without a separate license review.

## 開発状況

現在は初期設計と最小スキャフォールドの段階です。`SPEC.md` に API、保存レイヤ、
可視化、MAP/DEM/SVM、ドキュメント方針を集約しつつ、最初の実装は KAGUYA ESA1 の
file discovery、schema、typed data object、plot までの縦切りから進めます。保存、
pipeline、surface、plotting の詳細は `STORE.md`, `PIPELINE.md`, `SURFACE.md`, `PLOTTING.md`
に分けます。
