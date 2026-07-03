# Use Moon Maps

## Checklist

- Choose the analysis region.
- Choose the longitude domain.
- Choose DEM, SVM, SZA, shadow, or illumination.
- Preserve DEM and solar-geometry provenance for shadow/illumination.

```python
moon = spn.Moon()
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")
```

## DEM And SZA

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

DEM/SVM loading and terrain-aware shadow status is tracked in
[Status](../reference/status.md).
