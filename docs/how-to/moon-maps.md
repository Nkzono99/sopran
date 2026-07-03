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
    source="kaguya.tc.dem",
    region=region,
    resolution="512ppd",
    projection="native",
)

sza_plan = moon.sza.plan(
    time="2008-02-01T12:00:00Z",
    region=region,
)
```

## Shadow

```python
shadow_plan = moon.shadow.plan(
    time="2008-02-01T12:00:00Z",
    dem=dem_plan,
    geometry_source="spice",
)

metadata = shadow_plan.to_metadata()
```

## 0/360 度境界

```python
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")
region.contains(355, 0)
region.to_lon_domain("-180_180")
```

実 DEM/SVM 読み込みと terrain-aware shadow 計算の現状は
[実装状況](../reference/status.md) に集約しています。
