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
sza_plan = moon.sza.plan(time="2008-02-01T12:00:00Z", region=region)
```

Implemented endpoints:

- `moon.dem`
- `moon.svm`
- `moon.shadow`
- `moon.illumination`
- `moon.sza`

The body and surface endpoints expose bilingual package guides:

```python
moon.guide(language="ja")
moon.dem.guide(language="en")
```

They also expose short runnable examples as `GuidePage` snippets:

```python
moon.example()
moon.dem.example()
moon.shadow.example()
moon.sza.example()
```

Machine-readable schema objects use the same core `InstrumentSchema` and
`VariableSchema` classes as mission products:

```python
moon.schema()
moon.dem.schema()
moon.shadow.schema()
```

The current implementation records plans only. Full terrain-aware shadow and
illumination calculation will require DEM data, solar geometry, body shape,
projection metadata, and explicit longitude-domain handling.

Every surface plan records `shape`, `lon_domain`, `lon_direction`, `lat_type`,
`projection`, and `area_or_point`. Region-backed plans inherit coordinate
conventions from `region`, and derived plans such as `moon.shadow.plan(dem=...)`
inherit shape, datum, coordinate conventions, projection, and area-or-point
metadata from the DEM plan. Omitted values default to `spherical`, `0_360`,
`east_positive`, `planetocentric`, `native`, and `area`.
