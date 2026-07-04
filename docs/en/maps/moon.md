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
| `moon.svm` | `surface_vector_map`, `svm_tsunakawa2015` | Tsunakawa lunar magnetic anomaly SVM |
| `moon.svm_tsunakawa2015` | `tsunakawa_svm2015` | Explicit Tsunakawa 2015 SVM |
| `moon.sza` | `solar_zenith_angle` | Solar zenith angle |
| `moon.shadow` | `shadow_map` | Terrain-aware shadow fraction |
| `moon.illumination` | `illumination_map` | Illumination fraction |

## Select By Product Name

```python
moon.map("dem")
moon.map("elevation")
moon.map("svm_tsunakawa2015")
moon.map("shadow_map")
moon.map("solar_zenith_angle")
```

## Load DEM / SVM

DEM GeoTIFF files are loaded through `rasterio`. If it is missing, install the
Moon optional dependencies:

```powershell
pip install -e ".[moon]"
```

```python
moon = spn.Moon()

dem_path = moon.dem.download(source="lro.lola.dem_118m")
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")
dem = moon.dem.load(path=dem_path, source="lro.lola.dem_118m", region=region)
height = dem.sample(lat=0.5, lon=10.5)
```

For a single longitude / latitude region, GeoTIFF DEM files are read with a
raster window rather than loading the whole file.

`moon.svm` points to the default Tsunakawa SVM endpoint. SOPRAN does not
currently ship a verified stable direct download URL for
`LunarSVM_000_02_v02.dat`, so acquire it manually and pass `path=`, or place it
under the Store raw directory.
The original upstream URL is `http://www.geo.titech.ac.jp/lab/tsunakawa/Kaguya_LMAG`.

```python
svm = moon.svm_tsunakawa2015.load(path=r"C:/data/LunarSVM_000_02_v02.dat")
bt = svm.sample(lat=-0.5, lon=0.0)
```

## Plan Metadata

```python
plan = moon.dem.plan(
    source="lro.lola.dem_118m",
    region=spn.Region(lon=(120, 160), lat=(-45, -10), body="moon"),
    lon_domain="0_360",
    projection="polar_stereo",
)
plan.to_metadata()
```
