# Use Moon Surface Products

```python
moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")
sources = moon.dem.sources()

dem_plan = moon.dem.plan(
    source="kaguya.tc.dem",
    region=region,
    resolution="512ppd",
    projection="native",
    area_or_point="area",
)

shadow_plan = moon.shadow.plan(
    time="2008-02-01T12:00:00Z",
    dem=dem_plan,
)
metadata = shadow_plan.to_metadata()
```

`projection` and `area_or_point` are written to every surface plan. Use
`projection="polar_stereo"` as a short alias when you want
`polar_stereographic` metadata.

For regions that cross the 0/360 degree boundary:

```python
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")
region.contains(355, 0)
spn.Region(lon=(-10, 10), lat=(-5, 5), body="moon", lon_domain="0_360").lon
spn.Region(lon=(120, 160), lat=(-45, -10), body="moon", lon_direction="west_positive")
spn.Region(lon=(120, 160), lat=(-45, -10), body="moon", lat_type="planetographic")
region.to_lon_domain("-180_180")
region.to_lon_domain("minus180_180")  # accepted config alias
```

These endpoints are planning skeletons for now. Full terrain-aware computation
is planned after DEM, projection, body shape, and solar geometry semantics are
locked down.
