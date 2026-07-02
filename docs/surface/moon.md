# Moon Surface Products

Surface products are body-first rather than mission-first:

```python
moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

dem_plan = moon.dem.plan(
    source="kaguya.tc.dem",
    region=region,
    resolution="512ppd",
    projection="native",
    area_or_point="area",
)
shadow_plan = moon.shadow.plan(time="2008-02-01T12:00:00Z", dem=dem_plan)
```

Implemented endpoints:

- `moon.dem`
- `moon.svm`
- `moon.shadow`
- `moon.illumination`

The body and surface endpoints expose bilingual package guides:

```python
moon.guide(language="ja")
moon.dem.guide(language="en")
```

The current implementation records plans only. Full terrain-aware shadow and
illumination calculation will require DEM data, solar geometry, body shape,
projection metadata, and explicit longitude-domain handling.

Every surface plan records `projection` and `area_or_point`; omitted values
default to `native` and `area`.
