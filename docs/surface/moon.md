# Moon Surface Products

Surface products are body-first rather than mission-first:

```python
moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

dem_plan = moon.dem.plan(source="kaguya.tc.dem", region=region, resolution="512ppd")
shadow_plan = moon.shadow.plan(time="2008-02-01T12:00:00Z", dem=dem_plan)
```

Implemented endpoints:

- `moon.dem`
- `moon.svm`
- `moon.shadow`
- `moon.illumination`

The current implementation records plans only. Full terrain-aware shadow and
illumination calculation will require DEM data, solar geometry, body shape,
projection metadata, and explicit longitude-domain handling.
