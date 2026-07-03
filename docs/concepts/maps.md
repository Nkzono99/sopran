# Maps

DEM、SVM、SZA、shadow、illumination のような天体固定の地図は mission ではなく
body-first に扱います。

```python
moon = spn.Moon()
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")

dem = moon.dem.plan(source="kaguya.tc.dem", region=region)
sza = moon.sza.plan(time="2008-02-01T12:00:00Z", region=region)
shadow = moon.shadow.plan(time="2008-02-01T12:00:00Z", dem=dem)
```

## 地図の責務

| 要素 | 置き場所 |
| --- | --- |
| provider file discovery | mission module |
| body-fixed coordinate semantics | `sopran.bodies` |
| region、projection、longitude domain | `sopran.maps` |
| DEM/SVM/shadow product API | `spn.Moon()` |

## 座標 convention

Map plan は次の metadata を残します。

| key | 例 |
| --- | --- |
| `shape` | `spherical`, `spice_body_radii` |
| `lon_domain` | `0_360`, `-180_180` |
| `lon_direction` | `east_positive`, `west_positive` |
| `lat_type` | `planetocentric`, `planetographic` |
| `projection` | `native`, `polar_stereographic` |
| `area_or_point` | `area`, `point` |

0/360 度をまたぐ region も扱えます。

```python
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")
region.crosses_lon_boundary
region.contains(355, 0)
region.to_lon_domain("-180_180")
```

月面マップの endpoint は [月面マップ](../maps/moon.md) を参照してください。
