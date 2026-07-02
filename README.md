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

## Documentation

公開ドキュメントは MkDocs Material で `docs/` からビルドします。GitHub Pages は
`.github/workflows/docs.yml` で `main` への push 時に build/deploy する構成です。

```text
pip install mkdocs mkdocs-material "mkdocstrings[python]" pymdown-extensions numpy
set PYTHONPATH=src
mkdocs serve
```

`pip install -e ".[docs]"` も定義していますが、通常の runtime dependencies も解決対象になるため、
Windows で MSVC がない環境では `aacgmv2` などの build に失敗することがあります。docs だけを
編集する場合は上の軽量 install を使います。

## 現在動く最小 API

KAGUYA ESA1 については、public PBF file discovery、ローカル raw PBF decode、
`xarray`/`polars` 変換、parquet 保存、Pipeline scan/run、最小 PlotStack までの縦切りを
実装し始めています。ARTEMIS FGM は normalized parquet が Store にある場合の load skeleton を
用意しています。

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

pipe = (
    kg.esa1.pipeline(time)
    .decode()
    .select_variables("counts")
    .quicklook("counts")
    .write("kaguya.esa1.counts", layer="normalized")
)
pipe.run()                 # existing shard があれば失敗
pipe.run(mode="replace")   # 明示置換
pipe.run(mode="append")    # catalog に shard を追加
manifest = store.dataset("kaguya.esa1.counts", layer="normalized").manifest()
manifest["provenance"]["pipeline"]["stages"]

lazy = kg.esa1.pipeline(time).from_normalized().select_variables("counts").scan()
counts_frame = lazy.collect()

stream = (
    kg.esa1.pipeline(time)
    .from_normalized()
    .select_variables("counts")
    .stream(partition="day")
)
for day_frame in stream:
    pass

stack = spn.stack(
    kg.esa1.counts.load(time).spectrogram(y="energy"),
    kg.esa1.quality.load(time).line(),
)
fig = stack.plot()
quicklook = stack.quicklook("esa1_counts", root="reports")

bins = spn.time_bins(time, cadence="10s", partial="keep")
features = spn.align(
    kg.esa1.quality.load(time),
    grid=bins,
    method="nearest",
    tolerance="5s",
).to_polars()

# sza, wave_power, density, and quality_flag are loaded xarray-like products.
ml_features = (
    spn.SampleTable(bins)
    .add(sza, method="nearest", tolerance="5s")
    .add(wave_power, method="max")
    .add(density, method="median")
    .collect(join="inner", quality_mask=quality_flag)
    .to_polars()
)
```

`time x component` の vector product は `magnetic_field_x` のような wide columns に展開します。
観測量ごとに対応づけ方法を変える場合は `SampleTable` を使います。現在の reducer は
`nearest`, `center`, `mean`, `max`, `median`, `first`, `last` です。
`join="outer"` は全binを残し、`join="inner"` は欠損featureを含むbinを落とします。
`fill=-1.0` のように指定すると、`outer` で残した欠損featureを明示値で埋められます。
`quality_mask=<1D time series>` はbin内でcenterに近いmask値が0/False/欠損のbinを落とします。
`partial="keep"` はcadenceで割り切れない末尾binを残し、`partial="drop"` は捨てます。
`to_polars(layout="long")` は `time`, `feature`, `value` 形式のtableを返します。
`metadata()` はgridやreducer条件を返し、保存時のmanifest材料にできます。
`spn.align(...).write_parquet("features.parquet")` または
`spn.SampleTable(...).collect().write_parquet("features.parquet")` で feature table を保存できます。

raw file は `Store.raw_path("kaguya", "pds3")` 以下に public provider path を保って置きます。
たとえば ESA1 の 2008-01-01 は次の配置を探索します。

```text
F:/sopran_data/raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz
```

保存済み dataset は `Store.datasets(refresh=True)` で `registry/datasets.parquet` に索引化し、
layer や mission で絞り込めます。

```python
index = store.datasets(refresh=True)
kaguya_features = store.datasets(layer="features", mission="kaguya")
```

`kg.esa1.energy_flux` は実データではなく endpoint です。属性アクセスだけでは I/O を起こさず、
実データ取得は `.load(time)`、計算は `.compute(...)`、描画は `.plot(...)` を実行点にします。

解析プロジェクトでは case に時間範囲や既定 frame を持たせます。

```python
prj = spn.Project("projects/lunar_wake")
case = prj.case("wake_20080201")

counts = case.kaguya.esa1.counts.load()
artemis_b_plan = case.artemis.p1.fgm.magnetic_field.plan()
moon_dem_plan = case.moon.dem.plan(source="kaguya.tc.dem", region=case.region)

stack = case.stack(
    counts.spectrogram(y="energy"),
    case.kaguya.esa1.quality.load().line(),
)
stack.plot()

artifact = prj.save(case.kaguya.esa1.quality.load(), "interim/kaguya_esa1_quality_wake")
```

月面 DEM/SVM/shadow/illumination は mission ではなく body-first API を主導線にします。

```python
moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

dem_plan = moon.dem.plan(source="kaguya.tc.dem", region=region, resolution="512ppd")
shadow_plan = moon.shadow.plan(time="2008-02-01T12:00:00", dem=dem_plan)
```

ユーザー定義の database product は Store 配下に metadata と空 dataset として登録できます。

```python
db = store.database("lunar_wake", create=True)
product = db.register_product(
    name="event_table",
    schema=kg.esa1.schema(),
    description="hand-curated lunar wake events",
)

pipe.write(db.product("event_table"))
events = db.product("event_table").scan()
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

現在は KAGUYA ESA1 の local PBF decode、xarray/polars 変換、parquet 保存、Pipeline run/scan、
PlotStack、Project/Case、Moon surface skeleton、ARTEMIS FGM normalized store load skeleton を
実装し始めています。
詳細設計は `SPEC.md`, `STORE.md`, `PIPELINE.md`, `SURFACE.md`, `PLOTTING.md` に分けます。
