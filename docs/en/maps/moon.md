# Moon Maps

Moon maps are accessed through `spn.Moon()`. Mission-derived map products are
still represented as Moon body-fixed products at use time.

```python
moon = spn.Moon()
moon.info()
moon.schema()
```

## Endpoints

| Endpoint | Alias | Product |
| --- | --- | --- |
| `moon.dem` | `elevation`, `height` | Digital elevation model |
| `moon.svm` | `surface_vector_map` | Classified map layer |
| `moon.sza` | `solar_zenith_angle` | Solar zenith angle |
| `moon.shadow` | `shadow_map` | Terrain-aware shadow fraction |
| `moon.illumination` | `illumination_map` | Illumination fraction |

## Select By Product Name

```python
moon.map("dem")
moon.map("elevation")
moon.map("shadow_map")
moon.map("solar_zenith_angle")
```

## Plan Metadata

```python
plan = moon.dem.plan(
    source="kaguya.tc.dem",
    region=spn.Region(lon=(120, 160), lat=(-45, -10), body="moon"),
    lon_domain="0_360",
    projection="polar_stereo",
)
plan.to_metadata()
```
