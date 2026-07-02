# SOPRAN API and Data Store Spec

Status: draft

この文書は SOPRAN の API とデータ保存設計を考えるための作業仕様です。
最初から固定仕様にせず、実装しながら更新します。

## 目的

SOPRAN は、衛星観測データを mission / instrument 単位のオブジェクトとして扱い、
raw download、正規化、parquet 化、高レベル指標の生成、ユーザー側の database 拡張までを
一貫した pipeline として記述できる Python + Rust ライブラリにする。

中心となる利用感は SPEDAS の global product name ではなく、次のような直感的な
domain object interface とする。汎用 `open("kaguya.esa1.energy_flux")` を主導線にせず、
衛星、観測器、データ変数を Python の属性として表現する。

```python
import sopran as spn

kg = spn.Kaguya(project="projects/lunar_wake")
time = spn.period("2008-02-01T00:00:00", "2008-02-01T12:00:00")

kg.esa1.energy_flux.info()
kg.esa1.energy_flux.plan(time)

esa1 = kg.esa1.load(time)
energy_flux = kg.esa1.energy_flux.load(time)

esa1.energy_flux.plot()
energy_flux.plot()
```

同じ時間範囲で複数データを扱う notebook / analysis では、時間固定 view を使う。
ただし、時間範囲が case で確定していても、属性アクセスだけで I/O は起こさない。
実データ取得は `.load()`、計算は `.compute()`、描画は `.plot()` を実行点にする。

```python
case = spn.Project("projects/lunar_wake").case("wake_20080201")

esa1 = case.kaguya.esa1.load()
flux = case.kaguya.esa1.energy_flux.load()
b = case.artemis.p1.fgm.magnetic_field.load()

case.kaguya.esa1.energy_flux.plot()  # case の時間範囲で明示ログ付きロードを行う
```

pipeline API は主に正規化、parquet shard 生成、特徴量 DB 作成、長時間 batch で使う
下位 API とする。

## 設計原則

- Mission は `Kaguya()`, `Artemis()` のようなオブジェクトで表す。
- Body は `Moon()` のようなオブジェクトで表し、DEM、SVM、shadow、illumination などの
  天体表面 product の主導線にする。
- Instrument は `kaguya.esa1`, `kaguya.lmag`, `artemis.p1.fgm` のように属性で辿れる。
- Data variable は `kaguya.esa1.energy_flux`, `artemis.p1.fgm.magnetic_field` のように
  意味が分かる canonical name を属性で辿れる。`eflux`, `b`, `pos` などは alias とする。
- 裸の `kaguya.esa1.energy_flux` や `case.kaguya.esa1.energy_flux` は実データではなく
  endpoint とし、実データ取得は `.load(time)` で明示する。
- 属性アクセスだけで network I/O、download、decode、scan、collect を起こさない。
- `.plot()` は利便性のために内部で `.load()` してよいが、その場合は plan / log /
  provenance に何を読んだかを必ず残す。
- `.compute()` は shadow、illumination、feature など入力 product から新しい product を
  生成する明示的な実行点とする。
- すべての階層に `.info()` を置き、短い説明と利用可能な子要素を返す。
- 詳しい説明は `.guide()`、実行計画は `.plan(...)`、機械的な変数定義は `.schema()`、
  その場で動く例は `.example()` に分ける。
- 操作は pipeline として遅延評価する。`run()`, `collect()`, `scan()`, `write()` まで
  重い処理を始めない。これは batch / storage API の規則であり、variable endpoint の
  `.load()` は明示的な実行点とする。
- raw data、正規化済み parquet、高レベル feature、ユーザーDBを分ける。
- 公式配布データは provider の粒度と provenance を残す。
- 何度も使う中間成果物は manifest / catalog / schema を持つ dataset として保存する。
- Mission 固有の差分は instrument class に閉じ込め、共通 API は pipeline、
  store、product、metadata、time range に寄せる。
- Rust backend は decode、binning、fit、large shard generation などの重い決定的処理を担当する。
- 座標変換、時刻系、単位、CDF/PDS 読み込み、SPICE geometry、基本的な plasma parameter は
  既存の宇宙科学ライブラリを優先し、独自実装を避ける。

## 基盤ライブラリ方針

SOPRAN は mission-specific reader と pipeline / store / product abstraction を提供する。
一方で、宇宙科学で既に検証されている基盤機能は薄い adapter で使い、車輪の再開発をしない。

### 採用候補

| 領域 | 第一候補 | SOPRAN での扱い |
| --- | --- | --- |
| 惑星・月・探査機 geometry | `spiceypy` | KAGUYA/ARTEMIS の軌道、姿勢、月固定座標、SPICE kernel 管理の主軸 |
| 天文時刻・単位・天球座標 | `astropy.time`, `astropy.units`, `astropy.coordinates` | 時刻・単位・一般座標表現の基盤 |
| 太陽物理座標 | `sunpy.coordinates` | Carrington、Heliographic、太陽観測者依存 frame が必要な場合に使う |
| 地球磁気圏座標 | `spacepy.coordinates`, `spacepy.time`, `spacepy.irbempy` | GSE/GSM/SM など geospace frame、磁気座標、IRBEM 連携の候補 |
| CDF 読み書き | `cdflib`, 必要なら `spacepy.pycdf` | pure Python 優先なら `cdflib`。NASA CDF library 依存が許容できる場合のみ `spacepy.pycdf` |
| NASA CDAWeb | `cdasws`, `pyspedas` | ARTEMIS など CDAWeb 由来データの取得候補。PySPEDAS は挙動比較と fallback 参考に使う |
| HAPI | `hapiclient` | HAPI server 由来の時系列取得候補 |
| PDS3/PDS4 | `pdr`, `pds4_tools`, 必要なら GDAL | KAGUYA public/PDS 系 product の reader で再利用を検討 |
| raster / map / DEM | `rasterio`, `rioxarray`, `pyproj`, `cartopy`, `geopandas`, `shapely`, `pyogrio` | DEM、SVM、月面 map、footprint、region、投影変換、vector overlay の基盤 |
| plasma constants / formulae | `plasmapy` | 基本 plasma parameter、粒子定義、単位付き計算の候補 |
| satellite lifecycle design | `pysat` | download/load/clean/process の設計参考。SOPRAN の中心 API にはしない |
| 高緯度地球磁気座標 | `aacgmv2`, `apexpy` | 地球電離圏・極域解析が必要になった場合の optional backend |

### 座標系 adapter

SOPRAN の public API では、外部ライブラリの型をそのまま全面に露出させすぎず、
`sopran.frames` に薄い adapter を置く。

```python
from sopran.frames import FrameContext

frames = FrameContext(
    spice_kernels=store.kernels("kaguya"),
    time_scale="utc",
)

pos = (
    kaguya.orbit
    .select("2008-04-01")
    .position(frame="MOON_ME")
    .transform("GSE")
)
```

内部 backend の分担:

- `SpiceFrameAdapter`: SPICE kernel に基づく spacecraft、body-fixed、inertial frame。
- `AstropyFrameAdapter`: `Time`, `Quantity`, sky coordinate、一般的な frame transform。
- `SunPyFrameAdapter`: heliographic / helioprojective / Carrington 系。
- `SpacePyFrameAdapter`: GSE/GSM/SM など Earth magnetospheric frame と magnetic coordinates。

adapter は次を必ず記録する。

- 使用 backend と version。
- 使用 kernel、leapseconds、frame kernel、attitude kernel。
- 時刻系、入力 frame、出力 frame、単位。
- 磁場モデルや外部 field model を使った場合は model 名と parameter。

### 再実装しないもの

次は原則として SOPRAN 内に独自実装しない。

- UTC/TAI/TDB/TT/ET などの時刻系変換。
- 月・惑星・探査機の ephemeris と attitude geometry。
- GSE/GSM/SM など標準的な geospace coordinate transform。
- CDF/PDS/FITS など標準 format の汎用 parser。
- SI/cgs/天文単位や物理定数の変換。
- 既存ライブラリにある基本 plasma parameter の式。

例外として独自実装してよいのは、mission 固有 binary record decode、provider 固有の
broken metadata 補正、既存ライブラリにない instrument calibration、または performance のために
Rust へ移植する処理だけとする。その場合も、外部ライブラリまたは公式仕様との golden test を置く。

### 依存関係の扱い

SOPRAN は研究・解析用途を主対象にするため、依存を細かく optional extras に分けて
インストールサイズを小さく保つことは優先しない。標準インストールで、table 処理、
宇宙科学基盤、データ取得、可視化、地図・対話的探索に必要な主要ライブラリをまとめて入れる。

```text
standard dependencies:
  numpy, scipy, polars, pandas, pyarrow
  astropy, spiceypy, sunpy, spacepy, plasmapy
  cdflib, cdasws, hapiclient, astroquery, pdr, pds4_tools, pyspedas
  matplotlib, hvplot, holoviews, bokeh, datashader, panel
  cartopy, geoviews, rasterio, rioxarray, pyproj, shapely, geopandas, pyogrio
  xarray, dask, zarr

optional extras:
  sopran[dev]  # pytest, ruff, mypy, build tools
```

`import sopran` 自体は重くしすぎない。可視化 backend、SPICE、SpacePy、Cartopy、
Rasterio、GeoPandas などは
必要な module / method に入った時点で import する。つまり「依存は標準で入れる」が、
「全 backend を top-level import する」設計にはしない。

`pyarrow` は Polars の通常の parquet scan/write を動かすための必須実装ではなく、
Arrow table/array 互換、pandas/xarray 連携、partitioned dataset、Parquet metadata や
edge case の fallback を安定させるための依存として扱う。

外部ライブラリで計算した結果を `normalized`, `features`, `databases` に保存する場合は、
dataset manifest に backend 名、version、kernel/model、入力 dataset ID を残す。

## Public API

SOPRAN の public API は、まず次を主導線にする。

```python
spn.Kaguya
spn.Artemis
spn.Moon
spn.Project
spn.period
spn.stack
spn.align
```

補助 API として `TimeRange`, `concat`, `to_xarray`, `load("kaguya.esa1.energy_flux", time)`
などを増やしてよいが、主導線は object attribute API に置く。文字列 API は CLI、
batch、power-user 向けの補助とする。

### 共通実行規則

Mission、body、instrument、variable、surface product などの属性アクセスは軽い endpoint を返す。
属性アクセスだけで network I/O、download、decode、scan、collect、compute を起こさない。

```python
kg.esa1.energy_flux      # VariableEndpoint
case.kaguya.esa1.energy_flux
moon.dem                # SurfaceEndpoint
```

実行点は次に限定する。

- `.load(...)`: raw / normalized / cached data を読み、typed loaded object を返す。
- `.compute(...)`: 入力 product から feature、illumination、shadow などを生成する。
- `.plot(...)`: 利便性のために load/compute を伴ってよいが、plan / log / provenance を残す。
- pipeline の `.run()`, `.collect()`, `.scan()`, `.write()`: batch/storage API の実行点。

すべての階層は次の探索 API を持つ。

```python
obj.info()       # 短い説明。利用可能な子要素、変数、例を表示
obj.guide()      # Markdown guide。package README または docs を参照
obj.schema()     # machine-readable schema。該当する場合のみ
obj.plan(...)    # load/compute/plot 前の実行計画
obj.example()    # その場で動く短い例
```

### Mission object

Mission object は dataset store、download policy、default kernels、default calibration、
default frame、project context を持つ。

```python
kg = spn.Kaguya(project="projects/lunar_wake", frame="SSE", cache=True)
art = spn.Artemis(project="projects/lunar_wake", frame="SSE", cache=True)
moon = spn.Moon(project="projects/lunar_wake")
```

Mission object は instrument accessor を属性として提供する。

```python
kg.esa1
kg.esa2
kg.lmag
kg.orbit
kg.attitude

art.p1.fgm
art.p1.esa
art.p1.orbit
art.p2.fgm
```

Mission object 自体に巨大な処理を持たせず、instrument access、project context、
time-bound view を提供する。

```python
k = kg.between("2008-02-01T00:00:00", "2008-02-01T12:00:00")

k.esa1.energy_flux
k.esa1.counts
k.orbit.position
```

### Instrument object

Instrument object は mission 固有のデータ形式、変数定義、schema、reader、calibration を知る。

```python
time = spn.period("2008-02-01", "2008-02-02")

kg.esa1.info()
kg.esa1.schema()
kg.esa1.plan(time)
kg.esa1.load(time)

kg.esa1.energy_flux.load(time)
kg.esa1.counts.load(time)
kg.orbit.position.load(time, frame="SSE")

art.p1.fgm.load(time)
art.p1.fgm.magnetic_field.load(time, frame="SSE")
art.p1.esa.ion_energy_flux.load(time)
```

観測器単位で読む場合、返り値は型付き data object にする。

```python
esa1 = kg.esa1.load(time)

esa1.energy_flux
esa1.eflux          # alias
esa1.counts
esa1.energy
esa1.quality
esa1.to_xarray()
```

### Variable endpoint

`kg.esa1.energy_flux` は実データそのものではなく、KAGUYA / ESA1 / energy flux を表す
endpoint である。

```python
kg.esa1.energy_flux.info()
kg.esa1.energy_flux.guide()
kg.esa1.energy_flux.schema()
kg.esa1.energy_flux.plan(time)
kg.esa1.energy_flux.load(time)
kg.esa1.energy_flux.plot(time)
```

endpoint は次の metadata を持つ。

```text
name
canonical_name
dims
units
description
aliases
instrument
mission
loader
```

意味が分かる長い名前を canonical public API とし、短い名前は alias として残す。
ドキュメント上の主表記、plot label、schema の主キーは canonical name にする。
alias は SPEDAS/tplot や既存作業に慣れたユーザー向けのショートカットであり、`.info()` で明示する。

| canonical API name | aliases |
| --- | --- |
| `energy_flux` | `eflux`, `differential_energy_flux` |
| `number_flux` | `nflux`, `differential_number_flux` |
| `counts` |  |
| `energy` |  |
| `pitch_angle` | `pa` |
| `quality` | `q`, `quality_flag` |
| `spacecraft_position` | `pos`, `position` |
| `spacecraft_velocity` | `vel`, `velocity` |
| `magnetic_field` | `b` |

### Project and Case

`Project` は解析 workspace を表す薄い object とする。ライブラリ本体ではなく、
解析テーマ、case、cache、frame、provenance、保存先を束ねる。`Case` は時間範囲、
default frame、event region、plot preset などの context を与えるが、属性アクセスだけで
実データを返さない。

```python
prj = spn.Project("projects/lunar_wake")

case = prj.case("wake_20080201")

esa1 = case.kaguya.esa1.load()
flux = case.kaguya.esa1.energy_flux.load()
b = case.artemis.p1.fgm.magnetic_field.load()
dem = case.moon.dem.load(source="kaguya.tc.dem", region=case.region)
```

`projects/lunar_wake/sopran.toml` の例:

```toml
[project]
name = "lunar_wake"

[defaults]
frame = "SSE"
level = "l2"
cache = true

[cases.wake_20080201]
start = "2008-02-01T00:00:00"
stop = "2008-02-01T12:00:00"
```

`case.<mission>.<instrument>.<variable>` は時間範囲が確定していても endpoint を返す。
`.load()` は case の start/stop/default frame/cache policy を既定値として使う。
保存も project に紐づける。

```python
flux = case.kaguya.esa1.energy_flux.load()
prj.save(flux, "interim/kaguya_esa1_energy_flux_wake_20080201")
```

`plot()` だけは case context で内部 load してよい。ただし実行ログ、入力 dataset、time range、
frame、download policy、downsample / datashade 条件を残す。

```python
case.kaguya.esa1.energy_flux.plot()
```

## API の層

### 1. Context / Store

`Store` はデータ保存と探索の中心にする。単なる path wrapper ではなく、
raw、normalized、features、databases、cache、workspace の場所と registry を管理する。

```python
from sopran import Store

store = Store(
    root="F:/sopran_data",
    cache_root="F:/sopran_cache",
)
```

標準レイアウト案:

```text
F:/sopran_data/
  raw/              # 公式配布データ。provider path と checksum を保つ
  normalized/       # decoded / cleaned parquet, arrow, zarr
  features/         # PAD, moment, spectrum, orbit context など再利用する高レベル指標
  databases/        # ユーザー定義または研究テーマ単位の採用DB
  models/           # 学習済みモデルや calibration-derived artifact
  registry/         # dataset registry, manifest index

F:/sopran_cache/
  downloads/
  tmp/
  logs/
```

`Store` は次を担当する。

- dataset ID から実体 path を解決する。
- manifest と catalog を読み書きする。
- raw file の checksum、download URL、取得日時を記録する。
- parquet shard の schema、partition、期間、生成 pipeline を記録する。
- ユーザーが拡張した database を登録する。

### 2. Pipeline

Pipeline は処理 stage の列として扱う。これは public API の主導線ではなく、
raw download、decode、normalized parquet、features、database product を作るための
batch/storage API とする。

```python
pipe = (
    kaguya.esa1
    .select("2008-04-01", "2008-04-02")
    .download()
    .decode()
    .to_parquet("kaguya/esa1/records")
    .energy_flux()
    .write("kaguya/esa1/energy_flux", layer="features")
)
```

基本規則:

- stage を追加しても実行しない。
- `run()` は副作用ありで保存まで実行する。
- `collect()` はメモリ上の product として返す。
- `scan()` は Polars `LazyFrame` や Arrow scanner のような遅延 table を返す。
- `stream()` は shard / day / orbit 単位の iterator として返す。

```python
product = pipe.collect()
lazy = pipe.scan()

for chunk in pipe.stream(partition="day"):
    chunk.write(...)
```

### 3. Endpoint, loaded data, and products

SOPRAN では「まだ実行していないもの」と「読み込み済みのもの」と「保存・batch 用の遅延 product」を
用語上分ける。

| 型 | 役割 | 例 |
| --- | --- | --- |
| `VariableEndpoint` | mission / instrument / variable を表す軽量ハンドル。I/O しない | `kg.esa1.energy_flux` |
| `SurfaceEndpoint` | body / map product を表す軽量ハンドル。I/O しない | `moon.dem`, `moon.shadow` |
| `LoadedData` | instrument 単位で読み込んだ型付き data object | `KaguyaESA1Data`, `ArtemisFGMData` |
| `SopranArray` | 変数単体の loaded array。`xarray.DataArray` を薄く包む | `esa1.energy_flux` |
| `LazyProduct` | pipeline/storage 用の遅延 product | `pipe.energy_flux()` |
| `PlotStack` | 複数 panel の時系列可視化定義 | `case.stack(...)` |
| `SurfaceProduct` | body-fixed metadata を持つ loaded surface/raster product | `DemProduct`, `ShadowProduct` |

`Product` という語は広すぎるため、実装では上記の具体型を優先する。ドキュメント上で
総称として `product` と書く場合も、loaded なのか lazy なのかを明示する。

Loaded object の共通操作:

```python
loaded.to_polars()
loaded.to_pandas()
loaded.to_xarray()
loaded.plot()
loaded.info()
loaded.schema()
loaded.metadata
loaded.trange
```

Lazy product の共通操作:

```python
lazy.scan()           # polars.LazyFrame 相当
lazy.collect()        # loaded object または table
lazy.write(...)
lazy.plan()
lazy.run()
```

型付き data object の例:

```python
class KaguyaESA1Data:
    @property
    def dataset(self): ...

    @property
    def energy_flux(self): ...

    @property
    def eflux(self): ...  # alias

    @property
    def counts(self): ...

    @property
    def energy(self): ...

    @property
    def quality(self): ...

    def to_xarray(self): ...

    def plot_spectrogram(self, variable="energy_flux", **kwargs): ...
```

`SopranArray` は xarray を薄く包み、初心者向けの `.info()` / `.plot()` と、
上級者向けの `.xr` を両方提供する。

```python
flux = esa1.energy_flux

flux.info()
flux.plot()
flux.sel(energy=slice(100, 1000)).mean("energy").plot()
flux.xr
```

Loaded product の種類:

- `TimeSeriesProduct`: magnetic field, density, velocity など。
- `SpectrogramProduct`: energy-time, frequency-time など。
- `DistributionProduct`: 3D particle distribution。
- `OrbitProduct`: position, attitude, frame。
- `TableProduct`: event table, fit result, context table。
- `RasterProduct`: map image、DEM、SVM、shadow map、surface model。
- `SurfaceProduct`: body-fixed lon/lat/projection metadata を持つ天体表面 product。

## データ保存レイヤ

SOPRAN の保存設計は 4 層に分ける。

### raw

公式配布データを保存する。provider の path、filename、version、checksum、
download URL、取得時刻を manifest に残す。

例:

```text
raw/
  kaguya/
    darts/
      pace/
      lmag/
  artemis/
    cdaweb/
      p1/
      p2/
```

raw layer では schema 変換や列名統一をしない。再ダウンロード可能性と provenance を優先する。

### normalized

raw を解析しやすい parquet / arrow / zarr などへ変換した層。

例:

```text
normalized/
  kaguya/
    esa1/
      records/
        dataset.json
        catalog.parquet
        shards/year=2008/month=04/day=01/part-000.parquet
    lmag/
      b_vector/
```

normalized の目的:

- Polars で高速に scan できる。
- 時刻、品質 flag、単位、座標系、instrument metadata が揃う。
- raw file の provenance を各 shard または manifest から辿れる。

### features

後続解析で繰り返し使う高レベル指標。

例:

- energy flux
- pitch angle distribution
- moments
- loss-cone fit
- magnetic residual context
- orbit / solar wind context

features は raw や normalized よりも pipeline 設定への依存が強いので、
manifest に生成関数、引数、input dataset ID、code version、backend version を残す。

### databases

ユーザーや研究テーマが拡張できる database 層。

```python
db = store.database("kaguya_er")

(
    kaguya.esa1
    .select("2008")
    .decode()
    .energy_flux()
    .pitch_angle_distribution()
    .write(db.product("raw_pad"), partition="day")
    .run()
)
```

Database は複数 product をまとめる logical namespace とする。

```text
databases/
  kaguya_er/
    database.json
    raw_pad/
      dataset.json
      catalog.parquet
      shards/
    losscone/
      dataset.json
      catalog.parquet
      shards/
    omni_context/
      dataset.json
      catalog.parquet
      shards/
```

ユーザー拡張は `Database.register_product()` または pipeline の `write()` から行う。

```python
db = store.database("my_project")

db.register_product(
    name="event_table",
    layer="databases",
    schema=event_schema,
    description="hand-curated lunar wake events",
)
```

## Manifest / Catalog

保存される dataset は最低限次を持つ。

```text
dataset.json       # dataset ID, layer, schema version, provenance, generator
catalog.parquet    # shard index。期間、path、row count、checksum、status
schema.json        # column name, dtype, unit, frame, description
shards/            # 実データ
logs/              # 必要に応じて生成ログ
```

`dataset.json` に含めたい情報:

- `dataset_id`
- `layer`
- `mission`
- `instrument`
- `product`
- `version`
- `status`: `scratch`, `candidate`, `adopted`, `deprecated`
- `time_coverage`
- `source_datasets`
- `source_files`
- `schema`
- `partitioning`
- `producer`
- `created_at`
- `software`
- `parameters`

## Pipeline と保存の関係

Pipeline の `write()` は保存先を明示する。

```python
.write("kaguya/esa1/records", layer="normalized")
.write("kaguya/esa1/pad", layer="features")
.write(db.product("raw_pad"))
```

`write()` は `run()` まで実行しない。上書きは既定で禁止する。

```python
pipe.run()                  # 既存 dataset があれば失敗
pipe.run(mode="append")     # catalog に shard を追加
pipe.run(mode="replace")    # 明示時のみ置き換え
pipe.run(dry_run=True)      # 入出力計画だけ表示
```

大量処理では shard 単位で status を記録する。

```text
pending -> running -> complete
                  -> failed
                  -> skipped
```

失敗 shard は再実行できるようにする。

```python
pipe.run(resume=True)
pipe.run(only_failed=True)
```

## Polars との関係

Parquet shard、catalog、manifest 周辺の table 処理では Polars を第一候補にする。
一方で、観測器単位の読み込み済み data object は、多次元配列、座標軸、属性を自然に扱える
`xarray.Dataset` を内部表現にしてよい。

役割分担:

- `Polars`: catalog、event table、quality table、large parquet scan、join、filter。
- `Parquet`: normalized / features / databases の標準保存形式。
- `PyArrow`: Arrow table/array 互換、partitioned dataset、Parquet metadata、Polars native path で足りない I/O option の fallback。
- `xarray`: 読み込み済みの時系列、spectrogram、distribution、orbit などの in-memory data object。
- `pandas`: 互換出口。

- `scan()` は可能なら `polars.LazyFrame` を返す。
- `collect()` は SOPRAN Product を返し、必要に応じて中身に `polars.DataFrame` を持つ。
- typed data object は `to_xarray()` を持ち、必要に応じて `to_polars()` / `to_pandas()` も用意する。
- 保存形式はまず parquet を標準にする。

現行 Polars は PyArrow 実装の上に乗っているわけではなく、Rust 側の native
compute / buffer / parquet I/O を持つ。そのため通常経路は
`polars.scan_parquet()`, `DataFrame.write_parquet()`, `LazyFrame.sink_parquet()` を使う。
一方で、Hive partitioned dataset、既存の `pyarrow.dataset.Dataset`、PyArrow 側にしかない
writer option、他ライブラリとの zero-copy 連携が必要な場合は `pyarrow` 経路を明示的に使う。

例:

```python
lf = (
    kaguya.esa1
    .select("2008-04")
    .energy_flux()
    .scan()
    .filter(pl.col("energy_ev") > 100)
)
```

## Schema as code

データ構造が安定している mission / instrument では、schema を YAML だけに逃がさず、
Python code として明示する。

```python
KAGUYA_ESA1_SCHEMA = InstrumentSchema(
    mission="kaguya",
    instrument="esa1",
    variables=[
        VariableSchema(
            name="energy_flux",
            aliases=("eflux", "differential_energy_flux"),
            dims=("time", "energy", "look"),
            units="eV/(cm^2 s sr eV)",
        ),
        VariableSchema(
            name="counts",
            dims=("time", "energy", "look"),
            units="count",
        ),
        VariableSchema(
            name="energy",
            dims=("energy",),
            units="eV",
        ),
        VariableSchema(
            name="quality",
            aliases=("q", "quality_flag"),
            dims=("time",),
            units=None,
        ),
    ],
)
```

`load()` は normalized dataset を返す前に schema validation を行う。

```python
ds = normalize_kaguya_esa1(raw)
validate_schema(ds, KAGUYA_ESA1_SCHEMA)
return KaguyaESA1Data(ds)
```

これにより、ファイル仕様変更、欠損、列名変更、単位ミス、座標系 metadata 不足を早期に検出する。

## Package and workspace layout

ライブラリ本体と解析 workspace は分ける。`projects/` は SOPRAN package の中核ではなく、
研究・論文・解析テーマの作業場所とする。

```text
src/sopran/
  core/
    endpoint.py
    variable.py
    instrument.py
    data.py
    project.py
    case.py
    cache.py
    time.py
    metadata.py
    provenance.py

  projects/
    kaguya/
      README.md
      mission.py
      maps.py
      esa1.py
      esa2.py
      lmag.py
      lrs/
        README.md
        instrument.py
        schemas.py
        readers.py
      orbit.py
      schemas.py
      readers.py
      download.py
    artemis/
      mission.py
      probe.py
      esa.py
      fgm.py
      orbit.py
      schemas.py
      readers.py
      download.py

  bodies/
    moon/
      README.md
      body.py
      dem.py
      maps.py
      frames.py
      schemas.py

  maps/
    raster.py
    vector.py
    crs.py
    projection.py
    tiling.py

  frames/
  plot/

docs/
  index.md
  maps.md
  bodies/
    moon.md
  missions/
    kaguya.md
    kaguya/
      lrs.md
      pace.md
      lmag.md
    artemis.md

projects/
  lunar_wake/
    sopran.toml
    cases.toml
    notebooks/
    scripts/
    data/
      cache/
      raw/
      interim/
      processed/
    figures/
    outputs/
```

Python package namespace は当面 `sopran.projects.<mission>` を使う。将来、
`sopran.missions.<mission>` alias を追加してもよいが、初期実装では import path を増やしすぎない。

## Bodies, maps, and surface products

DEM、SVM、地形図、albedo、地質図、shadow map、footprint などの天体固有 map は、
mission reader だけに閉じ込めない。取得元・file format・provider layout は
`sopran.projects.<mission>` が担当し、月や惑星表面の product としての意味、座標系、
投影、region query、複数 mission source の比較は `sopran.bodies.<body>` と
`sopran.maps` が担当する。

```text
projects/kaguya/      # KAGUYA 由来 map product の取得、raw file discovery、decoder
bodies/moon/          # 月面 DEM/SVM/map としての統一 API
maps/                 # raster/vector/projection/tiling の mission 非依存基盤
```

API の主導線は body-first とする。

```python
moon = spn.Moon()

region = spn.maps.Region(lon=(120, 160), lat=(-45, -10), body="moon", lon_domain="0_360")

moon.dem.info()
moon.dem.sources()

dem = moon.dem.load(source="kaguya.tc.dem", region=region, resolution="512ppd")
svm = moon.svm.load(source="kaguya.lism.svm", region=region)

dem.plot(projection="polar_stereo", lon_domain="0_360")
dem.sample(lon=135.2, lat=-12.4, lon_domain="0_360")
dem.profile(path=case.kaguya.orbit.ground_track.load())
```

`moon.map("svm")` のような文字列 API は補助として残してよいが、主導線にはしない。

mission 側には provider-specific shortcut を置く。

```python
kg = spn.Kaguya()

kg.maps.dem.files()
kg.maps.dem.plan(region=region)
kg.maps.svm.files()
dem = moon.dem.load(source=kg.maps.dem, region=region)
```

`source` は `"kaguya"` のような粗い mission 名ではなく、`kaguya.tc.dem`,
`kaguya.lism.svm`, `lro.lola.dem`, `legacy.shadowmap_sza` のような stable source ID にする。
SPICE など幾何計算に使う入力は `source` ではなく `geometry_source` または `ephemeris` として
区別する。

保存 layout では provenance と意味上の所属を分ける。

```text
raw/
  kaguya/darts/map/...
  kaguya/darts/lism/...

normalized/
  bodies/moon/dem/kaguya_tc/
  bodies/moon/svm/kaguya_lism/
  bodies/moon/albedo/...
```

### Surface coordinate conventions

表面座標は暗黙にしない。`SurfaceProduct` とその具体型である `DemProduct`,
`SvmProduct`, `ShadowProduct`, `IlluminationProduct` は metadata に次を持つ。

- `body`: `moon`, `earth`, `mars` など。
- `datum` / `shape`: spherical、ellipsoid、triaxial、または SPICE body radii。
- `lon_domain`: `0_360` または `minus180_180`。
- `lon_direction`: `east_positive` または `west_positive`。
- `lat_type`: `planetocentric` または `planetographic`。
- `projection`: `equirectangular`, `polar_stereographic`, `orthographic`,
  `azimuthal_equidistant`, `lambert`, `native` など。
- `crs`: 可能なら `pyproj.CRS` / PROJ string / WKT として表現できるもの。
- `resolution`: degree/pixel、meter/pixel、pixels per degree など。
- `area_or_point`: pixel が area を表すか point を表すか。

経度表現、方位図法、極域投影は API で明示的に変換できるようにする。

```python
dem_180 = dem.wrap_longitude("-180_180")
dem_360 = dem.wrap_longitude("0_360")

polar = dem.reproject("polar_stereographic", center_lon=0, true_scale_lat=-90)
ortho = dem.reproject("orthographic", center_lon=135, center_lat=-30)

region = spn.maps.Region(lon=(120, 160), lat=(-45, -10), lon_domain="0_360")
cut = dem.crop(region).resample(resolution="128ppd")
```

内部では `pyproj` を CRS / projection transform、`rasterio` を raster I/O と reprojection、
`rioxarray` を xarray-backed raster data、`shapely` / `geopandas` / `pyogrio` を
region、footprint、vector overlay に使う。月・惑星固有の lon/lat convention は
Earth GIS の EPSG だけに寄せず、`body`, `datum`, `lon_domain`, `lat_type` を
SOPRAN metadata として必ず保持する。

### Shadow and illumination products

Shadow map は単なる描画用の暗い overlay として扱わない。解析に使う product では、
DEM、太陽位置、天体形状、座標系、投影、計算 method、入力データ version を manifest に残す。
旧実装や外部データにある `Shadowmap(sza)` のような SZA 固定 lookup は取り込めるが、
SOPRAN の標準 `ShadowProduct` では `model="external_precomputed"` または `model="legacy_lookup"`
として区別し、物理計算済み product と混同しない。

区別する product:

- `HillshadeProduct`: 地形を見やすくする可視化用 relief。解析上の陰影判定には使わない。
- `IlluminationProduct`: `cos_incidence`, `sun_elevation`, `sun_azimuth` など連続量。
- `ShadowProduct`: `is_shadow`, `shadow_fraction`, `terrain_occlusion`, `horizon_angle` など
  terrain shadow を含む判定量。

API 案:

```python
moon = spn.Moon()
dem = moon.dem.load(source="lro_lola", resolution="128ppd")

illum = moon.illumination.compute(
    time="2008-04-01T12:00:00",
    dem=dem,
    geometry_source="spice",
    body_frame="MOON_ME",
)

shadow = moon.shadow.compute(
    time="2008-04-01T12:00:00",
    dem=dem,
    method="terrain_ray",
    projection="native",
)

shadow.sample(lon=135.0, lat=-20.0, lon_domain="0_360")
shadow.plot(projection="polar_stereographic")
```

計算 model:

- `sphere`: DEM を使わず、天体半径と太陽方向だけで day/night と SZA を計算する。
  低解像度 context や sanity check 用。
- `local_slope`: DEM 勾配から surface normal を作り、局所入射角を計算する。
  近傍地形による cast shadow は含めない。
- `terrain_ray`: DEM と天体曲率を使い、太陽方向へ horizon / line-of-sight を追跡して
  cast shadow を計算する。解析用の標準候補。
- `terrain_ray_finite_sun`: 太陽視半径を考慮し、必要なら penumbra / shadow fraction を返す。
  高精度 product 用。

`terrain_ray` では平面 DEM 上の単純な 2D ray だけにしない。広域、極域、高 SZA では
球面または triaxial body 上の geodesic / 3D body-fixed ray marching として定義し、
projection の歪みと経度 wrap を扱う。実装はまず Python reference を作り、重い batch は
Rust backend stage に移す。

Shadow / illumination manifest に必ず残すもの:

- 入力 DEM dataset ID、version、resolution、datum / shape。
- 太陽位置の取得方法: SPICE kernel、frame、aberration correction、時刻系。
- `body`, `body_frame`, `lon_domain`, `lon_direction`, `lat_type`。
- 計算 method、ray step、最大探索距離、resampling、nodata policy。
- 出力変数、単位、boolean threshold、penumbra の扱い。
- backend 名、version、code hash。

validation:

- DEM なし sphere model では terminator が SZA 90 deg と一致すること。
- flat DEM では terrain shadow が発生せず、local incidence のみになること。
- 既知高さの ridge / crater synthetic DEM で解析的または高解像度 reference と一致すること。
- 極域、高 SZA、経度 0/360 wrap、`-180_180` wrap で不連続が出ないこと。
- 外部 precomputed shadow map を使う場合は、その生成条件を manifest に入れ、
  SOPRAN 計算 product との比較 test を置くこと。

## Documentation and guide API

Mission、instrument、variable、body、surface endpoint の仕様説明は、利用者が API から
辿れる形で持つ。
特に KAGUYA/ARTEMIS のように観測器、データレベル、座標系、file provider、品質 flag が
複雑な mission では、コードと離れた README だけにせず、package resource として同梱する。

### ドキュメント配置

基本方針は hybrid とする。

- `src/sopran/projects/<mission>/README.md`: mission 全体の概要、データ provider、座標系、
  時刻系、利用可能 instrument、引用、既知の注意点を書く。
- `src/sopran/projects/<mission>/<instrument>/README.md`: instrument 固有の仕様、観測量、
  cadence、データ level、file format、変数、単位、quality flag、calibration、SOPRAN API 例を書く。
- `docs/`: tutorial、how-to、横断的な概念説明、GitHub Pages / Read the Docs 用の公開文書を書く。
- `InstrumentSchema` / `VariableSchema`: 変数名、dims、units、frame、dtype、aliases など
  機械的に検証すべき情報の source of truth とする。

README は human-authored の説明、schema は machine-readable な仕様とする。
変数表、単位表、alias 表は可能なら schema から docs へ生成し、README と schema のズレを減らす。

### Guide API

Mission、instrument、variable endpoint、body、surface endpoint は、短い `info()` と詳しい
`guide()` を持つ。`help()` は Python 組み込みと名前が衝突しやすいため主導線にはせず、
interactive convenience の alias として許容する。

```python
kg = spn.Kaguya()
moon = spn.Moon()

kg.info()             # KAGUYA の短い概要
kg.guide()            # KAGUYA README を参照
kg.guide("lrs")       # KAGUYA/LRS README を参照

kg.lrs.info()
kg.lrs.guide()

kg.esa1.energy_flux.info()
kg.esa1.energy_flux.guide()

moon.info()
moon.dem.info()
moon.dem.guide()
```

`info()` は console で読みやすい短い text を返す。`guide()` は `GuidePage` のような
軽い object を返す。

```python
page = kg.guide("lrs")

str(page)        # plain text / markdown source
page.show()      # Jupyter では Markdown 表示、terminal では pager または print
page.open()      # docs URL が設定されていればブラウザで開く
page.source      # package resource path
page.url         # 公開 docs URL。未設定なら None
```

Jupyter では `_repr_markdown_()` を実装し、`kg.guide()` を最後の式に置くだけで
Markdown として読めるようにする。terminal では ANSI 装飾に依存しすぎず、plain text として
破綻しない表示にする。

### 公開 docs との関係

`docs/` は package 内 README をそのまま複製する場所ではなく、利用者向けの導線を作る場所とする。

- getting started、installation、first analysis。
- mission 横断の API 概念: `Project`, `Case`, `Store`, `LoadedData`, `LazyProduct`,
  `SurfaceProduct`, `PlotStack`。
- KAGUYA/ARTEMIS など mission ページ。
- instrument guide へのリンク。
- notebook gallery、quicklook examples、known caveats。
- citation、data policy、acknowledgement。

GitHub Pages などで公開する場合、`GuidePage.url` は対応する `docs/` ページを指せる。
offline 環境や未公開状態では package resource の Markdown を読む。

### ドキュメント内容テンプレート

Mission README の推奨構成:

- mission summary。
- supported instruments。
- data provider と mirror。
- data level と product 名。
- time system、coordinate frame、SPICE kernel の扱い。
- download/cache policy。
- examples。
- caveats、known gaps。
- references / citations。

Instrument README の推奨構成:

- instrument summary。
- measured quantity。
- product / file format。
- variables、dims、units、aliases。
- cadence、coverage、mode。
- quality flag、fill value、missing data。
- calibration status。
- coordinate/frame metadata。
- loader / decoder status。
- examples。
- references / citations。

## 可視化設計

データ解析では可視化が必須なので、SOPRAN は plotting を後付けの便利機能ではなく、
loaded data、endpoint、PlotStack の共通機能として扱う。ただし `import sopran` で重い可視化
backend を即 import しないよう、描画 backend は必要な method に入った時点で遅延 import する。

### 基本方針

可視化 backend は 1 つに固定しない。用途ごとに次を使い分ける。

- `matplotlib`: 論文・報告書・静的 PNG/PDF/SVG 出力の標準 backend。
- `hvplot` / `holoviews` / `bokeh`: notebook やブラウザ上の対話的探索の標準 backend。
- `datashader`: 大量点群、長期間時系列、orbit scatter、event density などを潰さず見るための集約 backend。
- `panel`: 複数 product を連動させる簡易 dashboard / review app 用。
- `cartopy`: 月面 map、投影、軌道・footprint などの静的地図描画用。
- `geoviews`: HoloViews 系で地理・月面投影を対話的に扱いたい場合の optional backend。
- `plotly` / `altair`: ユーザーが好む場合の出口としては許容するが、SOPRAN の第一 backend にはしない。

推奨は「Matplotlib を静的標準、HoloViz stack を探索標準」にすること。
Matplotlib だけに寄せると大量データ探索や dashboard が弱く、Plotly だけに寄せると
論文品質の細かい制御や巨大データ集約、Polars pipeline との設計が苦しくなる。

### Single product plot API

読み込み済みの `LoadedData`、`SopranArray`、`SurfaceProduct` は backend 非依存の `.plot()` を持つ。

```python
flux = kg.esa1.energy_flux.load(time)
flux.plot()                         # 既定 backend を使う
flux.plot(backend="matplotlib")     # 静的 figure
flux.plot(backend="hvplot")         # 対話的 plot
flux.plot(backend="datashader")     # 大量データ向け集約 plot
```

より明示的な出口も用意する。

```python
flux.to_matplotlib(ax=None)
flux.hvplot(...)
flux.explore()          # Panel / HoloViews based interactive view
flux.quicklook(...)
```

`VariableEndpoint.plot(time)` と `case.<...>.plot()` も許容する。この場合は `.plot()` が
内部で `.load()` する明示的な実行点であり、入力 dataset、time range、frame、cache/download
policy、downsample/datashade 条件を plan / log / provenance に残す。

```python
kg.esa1.energy_flux.plot(time, backend="matplotlib")
case.kaguya.esa1.energy_flux.plot(backend="hvplot")
```

`plot()` は小さなデータではそのまま描画するが、大きな dataset では勝手に全件
`collect()` しない。必要なら downsample、resample、datashade、期間制限を要求する。

### PlotStack

SPEDAS/tplot のように複数の時系列を縦に並べ、時間軸を共有して眺める用途は `PlotStack` を
第一級の object とする。単一 product の `.plot()` だけで表現しようとしない。

```python
stack = case.stack(
    case.kaguya.esa1.energy_flux.spectrogram(y="energy", log_color=True),
    case.kaguya.orbit.altitude.line(),
    case.artemis.p1.fgm.magnetic_field.lines(components="xyz", frame="SSE"),
)

stack.plan()
result = stack.plot(backend="matplotlib")
stack.explore(backend="panel")
stack.quicklook("wake_overview", formats=["png", "html"])
```

`spn.stack(...)` は case に依存しない補助 API として用意する。

```python
stack = spn.stack(
    kg.esa1.energy_flux.load(time).spectrogram(y="energy"),
    art.p1.fgm.magnetic_field.load(time).lines(components="xyz"),
)
```

`PlotStack` の規則:

- 描画では原則として各 product の native cadence を保ち、共有するのは UTC time axis にする。
- 解析用の resampling / interpolation / cadence 統一は `spn.align(...)` で明示する。
- `spn.align(...)` は `method`, `cadence`, `tolerance`, `join`, `fill` を必須級の引数として扱う。
- 大量データでは panel ごとに downsample / datashade してよいが、その条件を metadata に残す。
- 返り値は `PlotResult(fig=..., axes=..., backend=..., artifacts=..., metadata=...)` とする。
- `quicklook()` は PNG/HTML とともに dataset ID、time range、frame、backend、集約条件を保存する。

### Product type ごとの既定 plot

- `TimeSeriesProduct`: line / step / scatter。小規模は Matplotlib、大規模は hvPlot + Datashader。
- `SpectrogramProduct`: time-energy image。Matplotlib `pcolormesh` と HoloViews `QuadMesh/Image`。
- `DistributionProduct`: slice、projection、energy / angle cut。まずは Matplotlib と HoloViews。
- `OrbitProduct`: 2D/3D 軌道、月面 footprint、frame projection。
- `TableProduct`: histogram、scatter matrix、event timeline、quality summary。
- `RasterProduct` / `SurfaceProduct`: map image、contour、hillshade、overlay、projection、region crop。

### Pipeline との関係

Pipeline は保存だけでなく quicklook 生成も stage として扱えるようにする。

```python
(
    kaguya.esa1
    .select("2008-04")
    .decode()
    .energy_flux()
    .quicklook("energy_flux", backend="matplotlib")
    .write("kaguya/esa1/energy_flux", layer="features")
    .run()
)
```

`quicklook()` は PNG/HTML と metadata を dataset の `preview/` または `reports/` に保存する。
長時間 batch では shard ごと、日ごと、月ごとの quicklook を残し、異常検知や後日の監査に使う。

### 依存関係

可視化 backend は標準依存に含める。これは notebook / batch quicklook / 論文図作成を
同じ環境で扱いやすくするためである。一方で、実行時 import は遅延させ、
可視化を使わない loader や catalog 操作で重い backend を読み込まないようにする。

```text
sopran            # runtime dependency は基本的に全部入る
sopran[dev]       # pytest, ruff, mypy, build tools
```

`matplotlib`, `hvplot`, `holoviews`, `bokeh`, `datashader`, `panel`, `cartopy`,
`geoviews`, `rasterio`, `rioxarray`, `pyproj`, `shapely`, `geopandas`, `pyogrio` は
標準依存とするが、`product.plot()`, `product.explore()`, map 系 API などの必要箇所で
import する。

## 横断仕様

API と保存設計に加えて、以下は早い段階で仕様化しておく。実装後に変えると
データ互換性や解析再現性に影響しやすい。

### Licensing and porting policy

SOPRAN original code and documentation are licensed under Apache-2.0. Project
metadata, `LICENSE`, `NOTICE`, and `THIRD_PARTY_NOTICES.md` must stay in sync.

SPEDAS / PySPEDAS compatibility work is allowed, but copied or derivative
source must be tracked explicitly.

- MIT-licensed SPEDAS / PySPEDAS routines can be ported if the upstream
  copyright and MIT permission notice are retained.
- Ported files should identify the upstream routine, upstream commit or
  release, and whether the implementation is a clean-room reimplementation,
  behavior-compatible rewrite, or direct translation.
- GPL-licensed or NASA Open Source Agreement licensed external SPEDAS
  components must not be copied into the Apache-2.0 core package without
  a separate license review.
- Golden tests may compare SOPRAN output with SPEDAS output, but test data
  licenses must be recorded separately.
- `THIRD_PARTY_NOTICES.md` is the audit trail for third-party source and
  porting decisions.

### Dataset identity

保存される dataset / product / database は、人間が読める名前と機械的に安定した ID を分ける。

```text
display_name: "KAGUYA ESA1 energy flux"
dataset_id: "kaguya.esa1.energy_flux"
version: "0.1.0"
revision: "2026-07-02T130000Z"
```

`dataset_id` は原則として rename しない。表示名、説明、保存場所は変わってよい。
schema 互換を壊す変更は `version` を上げる。

### Schema evolution

Parquet / catalog / manifest は schema version を持つ。列の追加は minor、列名変更、
単位変更、意味変更、join key 変更は breaking change とする。

必須列の候補:

- `time`: 標準時刻列。内部表現は明示する。
- `time_unix` または `time_tai`: 高速 join 用の数値時刻。
- `source_file`: raw provenance。
- `quality`: product 共通の粗い品質指標。
- `flags`: instrument 固有 flag。
- `frame`: 座標系を持つ vector / position の場合。
- `unit`: manifest/schema に列単位として保持する。

### Time, unit, and frame conventions

時刻・単位・座標系は暗黙にしない。

- public API では ISO 8601 文字列、`datetime`, `astropy.time.Time` を受け付ける。
- 保存時の canonical time は dataset ごとに manifest へ書く。
- 物理量の単位は schema に保持し、可能なら `astropy.units` と対応できる名前にする。
- vector は component order と frame を schema に持つ。
- frame 変換済み product は、元 frame、出力 frame、backend、kernel/model を manifest に残す。

### Error handling

例外 class を分ける。

```text
SopranError
  ConfigError
  DatasetNotFoundError
  DownloadError
  DecodeError
  SchemaError
  FrameTransformError
  PipelineError
  BackendError
```

pipeline 実行では、単一 shard の失敗で全体を壊すか、failed shard として継続するかを
明示できるようにする。

```python
pipe.run(on_error="fail")
pipe.run(on_error="continue")
pipe.run(only_failed=True)
```

### Quality and missing data

欠損、fill value、instrument flag、calibration status、geometry status を共通的に扱う。

- raw の fill value は normalized で null / NaN へ変換する方針を manifest に書く。
- `quality` は全 product 共通の coarse flag とし、詳細は instrument 固有列に残す。
- calibration が未適用、推定、外挿、部分欠損の場合は product metadata に残す。
- 可視化では quality mask を簡単に重ねられるようにする。

### Provenance and reproducibility

保存される dataset は再生成に必要な情報を持つ。

- SOPRAN version。
- Python version。
- Rust backend version / binary hash。
- dependency lock file への参照がある場合はその path。
- pipeline stage list。
- stage parameters。
- input dataset IDs。
- raw source URLs / checksums。
- SPICE kernels / model files。
- command line または notebook/script path。

### Configuration

設定の優先順位を固定する。

1. 明示引数。
2. environment variables。
3. project config file。
4. user config file。
5. SOPRAN default。

設定候補:

- `SOPRAN_DATA_ROOT`
- `SOPRAN_CACHE_ROOT`
- `SOPRAN_ARTIFACT_ROOT`
- `SOPRAN_DOWNLOAD_MODE`
- `SOPRAN_OFFLINE`
- `SOPRAN_LOG_LEVEL`

### Download policy

download は副作用が大きいので、policy を明示する。

```python
kaguya = Kaguya(store=store, download="missing")
pipe.run(download="never")
pipe.run(download="always")
```

候補:

- `never`: ローカルにない場合は失敗。
- `missing`: 足りない raw だけ取得。
- `refresh`: remote metadata を確認し、必要なら更新。
- `always`: 明示時のみ再取得。

download した raw file は checksum または size / timestamp を catalog に残す。

### Logging and progress

長時間 pipeline は観測可能にする。

- pipeline run ID を発行する。
- stage / shard / row count / elapsed time を log に出す。
- `logs/` に stdout/stderr または structured log を保存する。
- `dry_run=True` で入出力計画を表示する。
- `resume=True` で catalog status から再開する。

### Rust backend contract

Rust は Python の細かい内側関数としてではなく、大きめの stage として呼ぶ。

Rust backend stage は次を満たす。

- 入力 manifest / catalog / shard path を受け取る。
- 出力 manifest / catalog / shard path を生成する。
- JSON など安定した config を受け取る。
- progress と error を machine-readable に返す。
- 小さな golden dataset で Python reference または公式仕様と比較する。

### Testing and validation

最初から重い end-to-end test に寄せない。

- unit test: store, time range, manifest, schema, pipeline stage。
- golden test: 小さな raw file から normalized / feature への変換。
- compatibility test: 外部ライブラリまたは SPEDAS/IDL 既存出力との比較。
- smoke test: import、dry-run、small sample decode。
- data safety test: download/cache/write が意図しない場所を書かないこと。

### API stability

`0.y.z` の間は破壊的変更を許すが、dataset schema と保存済み product の互換性は
API 以上に慎重に扱う。

- Python public API の破壊的変更は changelog に書く。
- saved dataset schema の破壊的変更は schema version を上げる。
- 古い product を読む migration / adapter を可能な範囲で用意する。

## 拡張 API

利用者が独自 mission、instrument、product、database を追加できるようにする。

### 独自 product

```python
@kaguya.esa1.product("custom_flux_ratio")
def custom_flux_ratio(q):
    return (
        q.energy_flux()
        .map_polars(lambda lf: lf.with_columns(
            (pl.col("flux_hi") / pl.col("flux_lo")).alias("flux_ratio")
        ))
    )
```

### 独自 database

```python
db = store.database("my_lunar_events", create=True)

events = db.product("events")

(
    kaguya.esa1
    .select(events.scan().select("start", "stop"))
    .energy_flux()
    .write(db.product("esa1_context"))
    .run()
)
```

### 独自 mission

初期から完全な plugin system は作らないが、将来的に次の protocol を用意する。

```python
class Mission:
    name: str
    store: Store

class Instrument:
    mission: Mission
    name: str
    def select(self, start, stop=None, **filters): ...
```

## 推奨する最初の実装単位

最初に全体を作り込みすぎず、次の順で薄く作る。

1. `Store` と dataset layout。
2. `Kaguya` mission object。
3. `kaguya.esa1.select(...).files()` で raw file discovery。
4. `VariableEndpoint` と `InstrumentSchema` の最小実装。
5. `kg.esa1.energy_flux.info()` / `.plan(time)` / `.load(time)` の形を作る。
6. `KaguyaESA1Data` など typed data object を返す。
7. raw PBF を小さく decode して `xarray.Dataset` と Polars DataFrame へ変換する。
8. parquet shard へ保存し、`scan()` で読めるようにする。
9. `Project` / `Case` の最小実装で `case.kaguya.esa1.energy_flux.load()` を実現する。
10. `PlotStack` の最小実装で `case.stack(...)` による複数 panel 可視化を実現する。
11. `Moon` / `SurfaceEndpoint` の最小実装で DEM/SVM の source discovery と load を実現する。
12. database namespace と user product registration を追加する。

## 未決事項

- `select("2008-04")` のような文字列 shorthand をどこまで許すか。
- `collect()` が返す Product と `scan()` が返す LazyFrame の境界。
- `xarray.Dataset` をどの product type まで第一級に扱うか。
- `kg.esa1.energy_flux` のような descriptor-based endpoint を static typing / IDE 補完でどこまで表現するか。
- Mission object に download policy を持たせるか、Store に寄せるか。
- raw download の provider ごとの mirror layout。
- pipeline graph を自前実装するか、まずは単純な stage list として実装するか。
- Rust backend を Python package に同梱する方式。PyO3、CLI、または両方。

## 現時点の判断

現時点では、SOPRAN は次の形を第一案とする。

- 利用者 API は domain-object-first。
- 主導線は `spn.Kaguya().esa1.energy_flux.load(time)` と
  `spn.Project(...).case(...).kaguya.esa1.energy_flux.load()`。
- 汎用 `spn.load("kaguya.esa1.energy_flux", time)` は CLI / batch / power-user 向けの補助 API に留める。
- 短い `eflux`, `b`, `pos` などは alias として残すが、README、docs、schema の主表記は
  `energy_flux`, `magnetic_field`, `spacecraft_position` のような意味の分かる名前にする。
- 処理 API は lazy pipeline。ただしこれは主に保存、正規化、feature DB、長時間 batch 用。
- 読み込み済み観測器 data は typed data object とし、内部表現は必要に応じて `xarray.Dataset`。
- 複数 mission / instrument の時系列可視化は `PlotStack` を第一級 object とする。
- DEM/SVM/shadow/illumination は mission-first ではなく `spn.Moon()` など body-first API を主導線にする。
- table backend は Polars / Parquet。
- data store は raw / normalized / features / databases の 4 層。
- database はユーザー拡張可能な logical namespace。
- Rust は大きめの batch stage として pipeline から呼び出す。
