# Surface Products

Surface products are body-first:

```python
moon = spn.Moon()
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")

moon.dem.sources()
moon.map("svm")
normalized = region.to_lon_domain("-180_180")
dem_plan = moon.dem.plan(
    source="kaguya.tc.dem",
    region=normalized,
    projection="polar_stereo",
    area_or_point="point",
)
metadata = dem_plan.to_metadata()
```

`SurfacePlan` metadata always records `projection` and `area_or_point`.
Defaults are `projection="native"` and `area_or_point="area"`; the
`polar_stereo` alias is canonicalized to `polar_stereographic`.

Regions understand longitude-domain wrapping:

```python
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")
region.crosses_lon_boundary  # True
region.lon_span              # 20.0
region.contains(355, 0)      # True
region.contains(-5, 0)       # True
spn.Region(lon=(-10, 10), lat=(-5, 5), lon_domain="0_360").lon  # (350.0, 10.0)
region.to_metadata()["lon_direction"]  # "east_positive"
spn.Region(lon=(120, 160), lat=(-45, -10), lon_direction="west_positive")
region.to_metadata()["lat_type"]       # "planetocentric"
spn.Region(lon=(120, 160), lat=(-45, -10), lat_type="planetographic")
region.to_lon_domain("minus180_180").lon_domain  # "-180_180"
```

Mission modules may discover provider files, but body-fixed semantics belong to
`sopran.bodies` and map utilities belong to `sopran.maps`.

Terrain-aware shadow and illumination products must eventually record DEM,
solar position, body shape, projection, and longitude-domain metadata.
