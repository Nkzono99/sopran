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
| `moon.shadow` | `shadow_map` | terrain-aware shadow fraction |
| `moon.illumination` | `illumination_map` | illumination fraction |

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
dem = moon.dem.load(path=dem_path, source="lro.lola.dem_118m")
height = dem.sample(lat=0.5, lon=10.5)
```

Tsunakawa SVM は `moon.svm` の既定 endpoint です。直接 download URL が安定確認できないため、
`LunarSVM_000_02_v02.dat` を手動で取得して `path=` を渡すか、Store の
`raw/moon/svm/` に配置します。
original upstream URL は `http://www.geo.titech.ac.jp/lab/tsunakawa/Kaguya_LMAG` です。

```python
svm = moon.svm_tsunakawa2015.load(path=r"C:/data/LunarSVM_000_02_v02.dat")
bt = svm.sample(lat=-0.5, lon=0.0)
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
