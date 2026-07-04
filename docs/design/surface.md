# SOPRAN Surface Spec

Status: draft

Surface products cover body-fixed map data such as Moon DEM, SVM, SZA, albedo,
geology maps, shadow maps, illumination maps, footprints, and projected
overlays.

The public API is body-first:

```python
moon = spn.Moon()
region = spn.maps.Region(lon=(120, 160), lat=(-45, -10), body="moon")

dem = moon.dem.load(source="lro.lola.dem_118m", region=region)
svm = moon.svm_tsunakawa2015.load(path="LunarSVM_000_02_v02.dat")
sza = moon.sza.plan(time="2008-02-01T12:00:00", region=region)
shadow = moon.shadow.compute(time="2008-02-01T12:00:00", dem=dem)
```

Mission modules provide provider-specific discovery and decoding:

```text
sopran.missions.kaguya   KAGUYA-derived DEM/SVM source discovery
sopran.bodies.moon       Moon surface semantics and body-fixed metadata
sopran.maps              raster/vector/projection/region utilities
```

DEM GeoTIFF load/download and Tsunakawa SVM text/npy load are implemented.
Full terrain-aware shadow and illumination calculation is a later milestone.

Surface products must preserve body, datum/shape, lon domain, lon direction,
lat type, projection, CRS, resolution, area-or-point, and geometry_source
metadata when geometry is involved. `geometry` is accepted as a compatibility
alias and normalized to the same value as `geometry_source`. `ephemeris` is also
accepted as a geometry input and normalized to `geometry_source`.

The current `Region` utility supports longitude-domain conversion,
0/360-boundary detection, longitude span, and simple point containment:

```python
region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")
region.contains(355, 0)
region.to_lon_domain("-180_180")
```
