# Use Moon Surface Products

```python
moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

dem_plan = moon.dem.plan(
    source="kaguya.tc.dem",
    region=region,
    resolution="512ppd",
)

shadow_plan = moon.shadow.plan(
    time="2008-02-01T12:00:00Z",
    dem=dem_plan,
)
```

These endpoints are planning skeletons for now. Full terrain-aware computation
is planned after DEM, projection, body shape, and solar geometry semantics are
locked down.
