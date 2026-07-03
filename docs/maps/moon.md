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
| `moon.svm` | `surface_vector_map` | classified map layer |
| `moon.sza` | `solar_zenith_angle` | solar zenith angle |
| `moon.shadow` | `shadow_map` | terrain-aware shadow fraction |
| `moon.illumination` | `illumination_map` | illumination fraction |

## product を名前で選ぶ

```python
moon.map("dem")
moon.map("elevation")
moon.map("shadow_map")
moon.map("solar_zenith_angle")
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
    source="kaguya.tc.dem",
    region=spn.Region(lon=(120, 160), lat=(-45, -10), body="moon"),
    lon_domain="0_360",
    projection="polar_stereo",
)
plan.to_metadata()
```

実データ読み込みや計算 backend の状況は [実装状況](../reference/status.md) を参照してください。
