# 月面マップを使う

## チェックリスト

- 解析 region を決める
- longitude domain を決める
- DEM/SVM/SZA/shadow のどれを使うか決める
- shadow/illumination では DEM と太陽位置を provenance に残す

```python
moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")
```

## DEM と SZA

```python
dem_plan = moon.dem.plan(
    source="lro.lola.dem_118m",
    region=region,
    resolution="256ppd",
    projection="native",
)

sza_plan = moon.sza.plan(
    time="2008-02-01T12:00:00Z",
    region=region,
)
```

`time=` だけから太陽位置を解く SPICE backend はまだ未実装です。計算する場合は
`sun_vector=` または `subsolar_lon_lat=` を明示します。

## DEM を download / load する

DEM GeoTIFF は `rasterio` で読み込みます。未導入の場合は次で入れます。

```powershell
pip install -e ".[moon]"
```

USGS の LRO LOLA 118m DEM は直接 URL があるため、Store の `raw/moon/dem/` に保存できます。
ファイルは約 8 GB です。

```python
store = spn.Store(r"F:/sopran-data")
moon = spn.Moon()

dem_path = moon.dem.download(source="lro.lola.dem_118m", store=store)
dem = moon.dem.load(path=dem_path, source="lro.lola.dem_118m", region=region)
dem.sample(lat=0.5, lon=10.5)
```

`region=` を渡すと、GeoTIFF 全体ではなく region に対応する raster window だけを読みます。
0/360 度境界をまたぐ region はまだ単一 window に分割せず、従来通り全体読み込みに戻します。

## Tsunakawa SVM を読む

`moon.svm` は現在の既定 SVM として `moon.svm_tsunakawa2015` を指します。
Tsunakawa SVM (`LunarSVM_000_02_v02.dat`) は安定した直接 download URL を確認できていないため、
手動で取得して `path=` に渡すか、Store に配置してください。
original upstream URL は `http://www.geo.titech.ac.jp/lab/tsunakawa/Kaguya_LMAG` です。

```python
svm = moon.svm_tsunakawa2015.load(path=r"C:/data/LunarSVM_000_02_v02.dat")
svm.sample(lat=-0.5, lon=0.0)
```

```text
<store>/raw/moon/svm/LunarSVM_000_02_v02.dat
```

```python
svm = moon.svm.load(store=store, download="never")
```

## Shadow

```python
sza = moon.sza.compute(like=dem, subsolar_lon_lat=(0.0, 0.0))
illumination = moon.illumination.compute(sza=sza, threshold_deg=90.0)
shadow = moon.shadow.compute(sza=sza, threshold_deg=90.0)
```

この `shadow` は `sza > threshold_deg` を 1 にする二値 map です。DEM の horizon を使った
terrain-aware shadow は未実装で、今後 `method=` を分けて追加する想定です。

## 0/360 度境界

```python
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")
region.contains(355, 0)
region.to_lon_domain("-180_180")
```

terrain-aware shadow 計算など未実装 backend の現状は [実装状況](../reference/status.md)
に集約しています。
