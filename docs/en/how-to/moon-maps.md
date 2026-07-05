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
    source="lro.lola.dem_118m",
    region=region,
    resolution="256ppd",
    projection="native",
)

sza_plan = moon.sza.plan(
    time="2008-02-01T12:00:00Z",
    region=region,
)
```

The SPICE backend that derives solar geometry from `time=` alone is not
implemented yet. For computed products, pass `sun_vector=` or
`subsolar_lon_lat=` explicitly.

## Download / Load DEM

DEM GeoTIFF files are loaded through `rasterio`. If it is missing, install:

```powershell
pip install -e ".[moon]"
```

The USGS LRO LOLA 118m DEM has a direct URL and can be stored under
`raw/moon/dem/`. The file is about 8 GB.

```python
store = spn.Store(r"F:/sopran-data")
moon = spn.Moon()

dem_path = moon.dem.download(source="lro.lola.dem_118m", store=store)
dem = moon.dem.load(path=dem_path, source="lro.lola.dem_118m", region=region)
dem.sample(lat=0.5, lon=10.5)
```

When `region=` is provided, SOPRAN reads only the matching GeoTIFF raster window.
Regions crossing the 0/360-degree longitude boundary currently fall back to the
full raster read instead of being split into multiple windows.

## Load Tsunakawa SVM

`moon.svm` currently points to `moon.svm_tsunakawa2015`. SOPRAN does not have a
verified stable direct download URL for `LunarSVM_000_02_v02.dat`, so acquire it
manually and pass `path=`, or place it in the Store.
The original upstream URL is `http://www.geo.titech.ac.jp/lab/tsunakawa/Kaguya_LMAG`.

```python
svm = moon.svm_tsunakawa2015.load(path=r"C:/data/LunarSVM_000_02_v02.dat")
svm.sample(lat=-0.5, lon=0.0)
```

```text
<store>/raw/moon/svm/LunarSVM_000_02_v02.dat
```

```python
svm = moon.svm.load(store=store, download="never")
```

## Shadow

```python
sza = moon.sza.compute(like=dem, subsolar_lon_lat=(0.0, 0.0))
illumination = moon.illumination.compute(sza=sza, threshold_deg=90.0)
shadow = moon.shadow.compute(sza=sza, threshold_deg=90.0)
```

This `shadow` product is a binary map where `sza > threshold_deg` is 1.
DEM-horizon terrain-aware shadowing is still pending and is expected to be added
behind a separate `method=`.

Terrain-aware shadow and other remaining backend status is tracked in
[Status](../reference/status.md).
