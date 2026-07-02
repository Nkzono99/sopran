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
sza_plan = moon.sza.plan(
    time="2008-02-01T12:00:00Z",
    region=region,
)
metadata = shadow_plan.to_metadata()
```

With a project case, configured region and case start time can be used as
defaults:

```python
case = spn.Project("projects/lunar_wake").case("wake_20080201")
dem_plan = case.moon.dem.plan(source="kaguya.tc.dem")
shadow_plan = case.moon.shadow.plan(dem=dem_plan)
sza_plan = case.moon.sza.plan()
```

`projection` and `area_or_point` are written to every surface plan. Use
`projection="polar_stereo"` as a short alias when you want
`polar_stereographic` metadata.
SZA plans default to `geometry_source="spice"` so the intended geometry backend
is recorded even before the SPICE-backed computation backend is implemented.

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
