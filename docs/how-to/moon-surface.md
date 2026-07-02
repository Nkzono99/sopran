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

For notebook exploration, `moon.example()`, `moon.dem.example()`,
`moon.shadow.example()`, and `moon.sza.example()` return short Markdown
`GuidePage` snippets with the same planning pattern.
Use `moon.schema()` and endpoint-level `schema()` calls when a workflow needs
machine-readable variable names, dimensions, units, frames, and aliases.

With a project case, configured region and case start time can be used as
defaults:

```python
case = spn.Project("projects/lunar_wake").case("wake_20080201")
dem_plan = case.moon.dem.plan(source="kaguya.tc.dem")
shadow_plan = case.moon.shadow.plan(dem=dem_plan)
sza_plan = case.moon.sza.plan()
```

`shape`, `lon_domain`, `lon_direction`, `lat_type`, `projection`, and
`area_or_point` are written to every surface plan. Plans inherit coordinate
conventions from `region`, and derived shadow or illumination plans inherit
shape, datum, coordinate conventions, projection, and area-or-point metadata
from `dem=<SurfacePlan>` unless you pass explicit values. Use
`shape="sphere"`, `lon_domain="minus180_180"`, and `projection="polar_stereo"`
as short aliases for `spherical`, `-180_180`, and `polar_stereographic`
metadata.
SZA plans default to `geometry_source="spice"` so the intended geometry backend
is recorded even before the SPICE-backed computation backend is implemented.
Passing the compatibility alias `geometry="spice"` writes the same value to
`geometry_source`. Passing `ephemeris="kaguya.spice"` records the same geometry
source value.

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
