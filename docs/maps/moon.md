# 月面マップ

月面マップは `spn.Moon()` から扱います。ミッション由来の地図でも、利用時の意味は
Moon body-fixed な product として整理します。

```python
moon = spn.Moon()
moon.info()
moon.schema()
```

## Endpoint

| endpoint | alias | product |
| --- | --- | --- |
| `moon.dem` | `elevation`, `height` | Digital elevation model |
| `moon.svm` | `surface_vector_map`, `svm_tsunakawa2015` | Tsunakawa lunar magnetic anomaly SVM |
| `moon.svm_tsunakawa2015` | `tsunakawa_svm2015` | 明示的な Tsunakawa 2015 SVM |
| `moon.sza` | `solar_zenith_angle` | solar zenith angle |
| `moon.shadow` | `shadow_map` | SZA-threshold or terrain-ray shadow fraction |
| `moon.illumination` | `illumination_map` | SZA-threshold illumination fraction |

## product を名前で選ぶ

```python
moon.map("dem")
moon.map("elevation")
moon.map("svm_tsunakawa2015")
moon.map("shadow_map")
moon.map("solar_zenith_angle")
```

## DEM / SVM を読む

GeoTIFF の DEM は `rasterio` を backend として読み込みます。未導入の場合は
`pip install -e ".[moon]"` で `rasterio` を入れてください。

```python
moon = spn.Moon()

dem_path = moon.dem.download(source="lro.lola.dem_118m")
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")
dem = moon.dem.load(path=dem_path, source="lro.lola.dem_118m", region=region)
height = dem.sample(lat=0.5, lon=10.5)
```

`region=` が単一の longitude / latitude 範囲なら、GeoTIFF は window read されます。

Tsunakawa SVM は `moon.svm` の既定 endpoint です。直接 download URL が安定確認できないため、
`LunarSVM_000_02_v02.dat` を手動で取得して `path=` を渡すか、Store の
`raw/moon/svm/` に配置します。
original upstream URL は `http://www.geo.titech.ac.jp/lab/tsunakawa/Kaguya_LMAG` です。

```python
svm = moon.svm_tsunakawa2015.load(path=r"C:/data/LunarSVM_000_02_v02.dat")
bt = svm.sample(lat=-0.5, lon=0.0)
```

## 磁気異常の文献カタログを検索する

`spn.moon.magnetic_anomalies()` は、論文の位置表をもとにした軽量カタログを
`pandas.DataFrame` で返します。ネットワーク接続や SVM ファイルは不要です。
`spn.Moon()` からも同じメソッドを呼べます。

```python
import sopran as spn

sites = spn.moon.magnetic_anomalies()  # Blewett 2011 の訂正版、15件
print(sites[["name", "lon_deg", "lat_deg", "peak_field_30km_nt", "swirl"]])

# 名前・feature_id の部分一致。Gamma / γ、ハイフン、下線に対応
reiner = spn.moon.magnetic_anomalies("all", name="Reiner Gamma")

# (東経, 緯度)。西経57.5°は -57.5 でも 302.5 でも指定可能
nearby = spn.moon.magnetic_anomalies("all", near=(-57.5, 7.5), radius_deg=5)
nearby.to_csv("nearby_anomalies.csv", index=False)

# 孤立異常の解析中心と、論文で使った観測領域の半径
isolated = spn.moon.magnetic_anomalies("oliveira2017")
```

| `catalog` | 件数・内容 | 出典 |
| --- | --- | --- |
| `blewett2011`（既定） | 15件。概略位置、30 kmでの磁場ピーク、地形区分、当時のスワール分類 | [Blewett (2011), 訂正版 Table 1](https://doi.org/10.1029/2011JE003852) |
| `oliveira2017` | 15件。孤立異常の解析中心、観測半径 $r_o$、双極子配置半径 $r_d$ | [Oliveira & Wieczorek (2017), Table 1](https://doi.org/10.1002/2016JE005199) |
| `all` | 計30行、23個の `feature_id`。同じ地域の異なる文献値を保持 | 上記2表 |

これは文献で選ばれた地域の一覧であり、全球の全磁気異常を網羅しません。
`name` は文献の表記を保ち、`feature_id` で Reiner-γ / Reiner Gamma、
Sirsalis / Rima Sirsalis を対応付けます。座標の異なる行を平均・統合しません。
Blewett の元論文には座標の誤りがあるため、訂正版を採用しています。

| 列 | 意味 |
| --- | --- |
| `lon_deg`, `lat_deg` | 東経0–360°、北緯正。文献の月固定座標。精密な MOON_ME / MOON_PA 変換は行わない |
| `position_kind` | `approximate_anomaly_location` は概略位置、`analysis_center` は解析領域の中心 |
| `peak_field_30km_nt` | 高度30 kmでの地域内の推定ピーク $\lvert B\rvert$ [nT]。月面値や掲載座標での点値とは異なる |
| `setting`, `swirl` | Blewett 表の地形・スワール分類。`not_recognized` は2011年時点の未確認を表す |
| `observation_radius_deg`, `dipole_radius_deg` | Oliveira 論文の解析領域の角半径。磁気異常の物理的な境界・サイズではない |
| `reference_doi`, `note` | 行ごとの出典と注記。Marginis は LP MAG の被覆が乏しい |
| `distance_deg`, `distance_km` | `near` 指定時のみ。掲載座標への大円距離。km換算には月半径1737.4 kmを使用 |

文献にない値は欠損値で返します。`near` は距離順に並べ、`radius_deg` は
掲載点までの角距離で絞り込みます。領域との交差判定には使いません。
`radius_deg` は `near` と一緒に指定し、0–180°とします。
空の検索結果も列と `DataFrame.attrs` のメタデータを保ちます。

位置表と SVM を併用する場合は、既存の `sample()` に座標を渡せます。
以下の追加列は SVM の点値であり、文献の地域内ピークとは別の量です。

```python
# svm は上の例などで読み込んだ月面 SVM RasterLayer
sites["svm_surface_point_nt"] = svm.sample(lat=sites.lat_deg, lon=sites.lon_deg)
```

## SZA / illumination / shadow を計算する

`moon.sza.compute()` は既存 raster と同じ grid、または `lon=` / `lat=` / `region=` から
球面近似の solar zenith angle を計算します。太陽位置は `sun_vector=`、
`subsolar_lon_lat=`、または `time=` と `spice_kernels=` から与えます。

```python
sza = moon.sza.compute(like=dem, subsolar_lon_lat=(0.0, 0.0))
illumination = moon.illumination.compute(sza=sza, threshold_deg=90.0)
shadow = moon.shadow.compute(sza=sza, threshold_deg=90.0)
```

`illumination` は `sza <= threshold_deg` を 1、`shadow` は `sza > threshold_deg` を 1 にする
二値 raster です。DEM の地形 horizon を追う場合は `method="terrain_ray"` を使います。

```python
sza = moon.sza.compute(
    like=dem,
    time="2008-02-01T12:00:00Z",
    spice_kernels=("kernels/naif0012.tls", "kernels/de421.bsp", "kernels/moon_pa.bpc"),
)
shadow = moon.shadow.compute(method="terrain_ray", dem=dem, sza=sza)
```

## guide と example

```python
moon.guide(language="ja")
moon.dem.guide(language="en")

moon.example()
moon.dem.example()
moon.shadow.example()
moon.sza.example()
```

## plan metadata

Map plan は shape、datum、projection、longitude domain、area/point の扱いを
metadata として残します。

```python
plan = moon.dem.plan(
    source="lro.lola.dem_118m",
    region=spn.Region(lon=(120, 160), lat=(-45, -10), body="moon"),
    lon_domain="0_360",
    projection="polar_stereo",
)
plan.to_metadata()
```

shadow/illumination など計算 backend の状況は [実装状況](../reference/status.md) を参照してください。
