# Maps

Body-fixed maps such as DEM, SVM, SZA, shadow, and illumination are body-first,
not mission-first.

```python
moon = spn.Moon()
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")

dem = moon.dem.plan(source="lro.lola.dem_118m", region=region)
svm = moon.svm_tsunakawa2015.plan(region=region)
sza = moon.sza.plan(time="2008-02-01T12:00:00Z", region=region)
shadow = moon.shadow.plan(time="2008-02-01T12:00:00Z", dem=dem)
```

## Responsibilities

| Element | Owner |
| --- | --- |
| Provider discovery | mission module |
| Body-fixed semantics | `sopran.bodies` |
| Region, projection, longitude domain | `sopran.maps` |
| DEM/SVM/shadow API | `spn.Moon()` |

Moon map endpoints are listed in [Moon Maps](../maps/moon.md).
