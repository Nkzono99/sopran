# Surface Products

Surface products are body-first:

```python
moon = spn.Moon()
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")

moon.dem.sources()
normalized = region.to_lon_domain("-180_180")
dem_plan = moon.dem.plan(source="kaguya.tc.dem", region=normalized)
metadata = dem_plan.to_metadata()
```

Regions understand longitude-domain wrapping:

```python
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")
region.crosses_lon_boundary  # True
region.lon_span              # 20.0
region.contains(355, 0)      # True
region.contains(-5, 0)       # True
region.to_lon_domain("minus180_180").lon_domain  # "-180_180"
```

Mission modules may discover provider files, but body-fixed semantics belong to
`sopran.bodies` and map utilities belong to `sopran.maps`.

Terrain-aware shadow and illumination products must eventually record DEM,
solar position, body shape, projection, and longitude-domain metadata.
