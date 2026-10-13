# 月面マップ

地形（DEM）、表面磁場（SVM）、太陽天頂角、日照・影のような月面に固定された地図は、ミッションではなく天体`spn.moon`から扱います。
どのミッション由来の地図でも、使うときの意味は「月の経度・緯度の上の量」として同じだからです。
地図はGeoTIFFの読み込みに`rasterio`を使います（`moon` extra）。

```python
moon = spn.moon
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

dem = moon.dem.load(source="lro.lola.dem_118m", region=region)
sza = moon.sza.compute(like=dem, subsolar_lon_lat=(0.0, 0.0))
shadow = moon.shadow.compute(method="terrain_ray", dem=dem, sza=sza)
```

## 地図の種類

| 入口 | 別名 | 単位 | 内容 |
|---|---|---|---|
| `moon.dem` | `elevation`、`height` | m | 標高 |
| `moon.svm` | `surface_vector_map`、`svm_tsunakawa2015` | nT | Tsunakawa et al. (2015)の表面磁場マップ。既定のSVM |
| `moon.svm_ravat2020` | — | nT | Ravat et al. (2020)の表面磁場モデル。成分を選べる |
| `moon.sza` | `solar_zenith_angle` | deg | 太陽天頂角 |
| `moon.illumination` | `illumination_map` | fraction | 日照 |
| `moon.shadow` | `shadow_map` | fraction | 影 |

`moon.map("elevation")`のように名前の文字列からも選べます。読み込んだ地図は`RasterLayer`で、
`dem.sample(lat=0.5, lon=10.5)`で任意の点の値を取り出せます。各地図の`info()`、`guide()`、`example()`、
`sources()`で、説明と利用できる取得元を確かめられます。

## 座標の約束

地図の経度・緯度の定義は暗黙にせず、計画（`plan()`）と結果のメタデータに残します。

| キー | 値の例 | 既定 |
|---|---|---|
| `lon_domain` | `0_360`、`-180_180` | `0_360` |
| `lon_direction` | `east_positive`、`west_positive` | `east_positive` |
| `lat_type` | `planetocentric`、`planetographic` | `planetocentric` |
| `shape` | `spherical`、`spice_body_radii` | `spherical` |
| `projection` | `native`、`polar_stereographic` | `native` |
| `area_or_point` | `area`、`point` | `area` |

0/360度をまたぐ領域は`spn.Region(lon=(350, 10), ...)`のように書けます（[期間・領域・解析条件](../../guide/views-cases.md#領域は経度の定義域と一緒に持つ)）。

```python
plan = moon.dem.plan(source="lro.lola.dem_118m", region=region, projection="polar_stereo")
plan.to_metadata()      # 読む前に、座標の約束と入力を確かめる
```

## DEM

| `source` | 内容 | 大きさ |
|---|---|---|
| `lro.lola.dem_118m`（`lro.lola.dem`） | LRO LOLAの全球DEM。256 pixel/deg（赤道で118 m） | 約8 GB |
| `lro.lola.sldem2015_59m`（`kaguya.tc.dem`） | SLDEM2015。LOLAとKAGUYA地形カメラの合成、512 pixel/deg、南北60度まで | 約22 GB |

どちらもUSGSから直接ダウンロードでき、Storeの`raw/moon/dem/`に置きます。

```python
path = moon.dem.download(source="lro.lola.dem_118m")      # 既定のStoreへ
dem = moon.dem.load(path=path, source="lro.lola.dem_118m", region=region)
```

`path=`を省くと、Storeの`raw/moon/dem/`にあるファイルを読みます。無いときの動作は他のデータと同じダウンロード方針
（[設定](../../guide/configuration.md#ダウンロード方針)、既定`missing`）に従い、取得してから読みます。
DEMは8〜22 GBあるので、取得したくないときは`download="never"`を渡すか、セッションやViewの方針を`never`にしてください。
その場合はファイルが無いと`DatasetNotFoundError`になります。
Storeは`store=`で指定でき、省略時は`spn.moon`ならセッションの設定、`view.moon`ならそのProjectのStoreです。

`region=`を渡すと、ファイル全体ではなく領域に対応する部分だけを読みます。
0/360度をまたぐ領域はまだ分割して読めないため、ファイル全体を読みます。

## 表面磁場（SVM）

Tsunakawa SVM（`LunarSVM_000_02_v02.dat`）は、安定した直接ダウンロードのURLを確認できていません。
手で入手して`path=`に渡すか、Storeの`raw/moon/svm/`に置いてください。元の公開先は
`http://www.geo.titech.ac.jp/lab/tsunakawa/Kaguya_LMAG`です。

```python
svm = moon.svm.load(path="/path/to/LunarSVM_000_02_v02.dat")
svm = moon.svm.load(download="never")          # Storeの raw/moon/svm/ から読む
svm.sample(lat=-0.5, lon=0.0)
```

Ravat et al. (2020)のモデル（`moon.svm_ravat2020`）は、Lunar ProspectorとKAGUYAの磁場の軌道方向の勾配から求めた表面磁場です。
月の楕円体面（赤道半径1738.1 km、極半径1736.0 km）上の0.1度格子で、成分を`component=`で選びます。

| `component` | 内容 |
|---|---|
| `"total"`（既定） | 全磁力 |
| `"br"` | 動径成分（外向きが正） |
| `"btheta"` | 余緯度方向の成分（南向きが正） |
| `"bphi"` | 経度方向の成分（東向きが正） |

配布元のケンタッキー大学のリポジトリ（[DOI 10.13023/9wpe-tt68](https://doi.org/10.13023/9wpe-tt68)、CC0）は、
プログラムからの取得をブラウザ確認で止めるため、自動取得できません。ブラウザで本体の
`Ravatetal_JGR2020_LunarL1MagneticModelFields_LPgrad.dat`（約88 MB）を取得し、Storeの`raw/moon/svm/`に置くか`path=`に渡してください。
読み込みは約650万行の表から格子を組み立てるため、数秒かかります。

```python
br = moon.svm_ravat2020.load(component="br")    # Storeの raw/moon/svm/ から読む
br.sample(lat=8.0, lon=302.0)                   # Reiner Gamma付近
```

## 太陽天頂角・日照・影

`moon.sza.compute()`は、球の月の上で太陽天頂角を計算します。格子は既存の地図（`like=`）か、`lon=`・`lat=`・`region=`で与えます。
太陽の位置は次のどれかで与えます。

| 引数 | 太陽の位置 |
|---|---|
| `sun_vector=` | 月固定座標の太陽方向ベクトル |
| `subsolar_lon_lat=` | 太陽直下点の経度・緯度 |
| `time=`と`spice_kernels=` | SPICEで計算（時刻・月の座標系・天体暦のカーネルが必要） |

```python
sza = moon.sza.compute(like=dem, subsolar_lon_lat=(0.0, 0.0))
illumination = moon.illumination.compute(sza=sza, threshold_deg=90.0)   # sza <= 90 を1
shadow = moon.shadow.compute(sza=sza, threshold_deg=90.0)               # sza > 90 を1
```

しきい値による日照・影は、地形を考えない二値の地図です。地形の起伏による影は`method="terrain_ray"`で、
DEMの上を太陽方向へ地平線をたどって計算します。

```python
sza = moon.sza.compute(
    like=dem,
    time="2008-02-01T12:00:00Z",
    spice_kernels=("kernels/naif0012.tls", "kernels/de421.bsp", "kernels/moon_pa.bpc"),
)
shadow = moon.shadow.compute(method="terrain_ray", dem=dem, sza=sza)
```

## 制約

- 投影変換（reproject）と双線形補間は未実装です。`projection`は記録と計画に使います。
- 太陽を点光源として扱い、半影（penumbra）による部分的な影は計算しません。
- `terrain_ray`は大きなDEMでは遅く、公開DEMと実際のSPICEカーネルによる数値検証はまだ行っていません。

磁気異常の位置を論文の表から検索するには[磁気異常カタログ](magnetic-anomalies.md)を使います。
