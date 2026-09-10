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
| `moon.shadow` | `shadow_map` | SZA-threshold or terrain-ray shadow fraction |
| `moon.illumination` | `illumination_map` | SZA-threshold illumination fraction |

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

## Search Literature Magnetic Anomaly Catalogs

`spn.moon.magnetic_anomalies()` returns a fresh `pandas.DataFrame` of published
reference locations without network access or SVM files. The same method is
available on `spn.Moon()`.

```python
import sopran as spn

sites = spn.moon.magnetic_anomalies()  # 15 corrected Blewett 2011 entries
print(sites[["name", "lon_deg", "lat_deg", "peak_field_30km_nt", "swirl"]])
reiner = spn.moon.magnetic_anomalies("all", name="Reiner Gamma")
nearby = spn.moon.magnetic_anomalies("all", near=(-57.5, 7.5), radius_deg=5)
nearby.to_csv("nearby_anomalies.csv", index=False)
isolated = spn.moon.magnetic_anomalies("oliveira2017")
```

| `catalog` | Contents | Reference |
| --- | --- | --- |
| `blewett2011` (default) | 15 approximate locations, regional peak field at 30 km, terrain and historical swirl classifications | [Blewett (2011), corrected Table 1](https://doi.org/10.1029/2011JE003852) |
| `oliveira2017` | 15 isolated-anomaly analysis centers, observation radii $r_o$ and dipole-domain radii $r_d$ | [Oliveira & Wieczorek (2017), Table 1](https://doi.org/10.1002/2016JE005199) |
| `all` | 30 source rows, 23 distinct `feature_id` values; source differences are retained | Both tables |

These study selections are not an exhaustive global inventory. `name` preserves
the published label; `feature_id` associates Reiner-γ / Reiner Gamma and
Sirsalis / Rima Sirsalis across sources. Coordinates are not averaged or merged.
The original Blewett article has coordinate errors; SOPRAN uses the correction.

| Column | Meaning |
| --- | --- |
| `lon_deg`, `lat_deg` | East longitude [0, 360), north-positive latitude; published lunar body-fixed positions, without precision MOON_ME / MOON_PA conversion |
| `position_kind` | `approximate_anomaly_location` or `analysis_center` |
| `peak_field_30km_nt` | Estimated regional peak $\lvert B\rvert$ at **30 km altitude**, in nT; neither a surface field nor a point sample at the listed location |
| `setting`, `swirl` | Blewett terrain and swirl classifications; `not_recognized` refers to 2011, not proof of absence |
| `observation_radius_deg`, `dipole_radius_deg` | Oliveira inversion-domain angular radii, not physical anomaly boundaries or sizes |
| `reference_doi`, `note` | Per-row source and caveats, including limited LP MAG coverage at Marginis |
| `distance_deg`, `distance_km` | Added with `near`; great-circle distance to the reference point, using a 1737.4 km lunar radius |

Unreported quantities remain missing. `name` searches literal substrings of names
or feature IDs, ignoring case and normalizing gamma (γ), hyphens and underscores.
`near=(east_longitude, latitude)` accepts negative longitudes and sorts by distance.
`radius_deg` requires `near`, accepts 0–180°, and filters reference points inclusively;
it does not test intersections with anomaly boundaries. Empty results retain
columns and `DataFrame.attrs` metadata.

To sample a previously loaded surface SVM raster at these positions:

```python
sites["svm_surface_point_nt"] = svm.sample(lat=sites.lat_deg, lon=sites.lon_deg)
```

Keep these point samples separate from the published regional peaks at 30 km.

## Compute SZA / Illumination / Shadow

`moon.sza.compute()` computes a spherical solar-zenith-angle raster on an
existing raster grid, or on axes supplied through `lon=` / `lat=` / `region=`.
Solar geometry can be supplied with `sun_vector=`, `subsolar_lon_lat=`, or
`time=` plus `spice_kernels=`.

```python
sza = moon.sza.compute(like=dem, subsolar_lon_lat=(0.0, 0.0))
illumination = moon.illumination.compute(sza=sza, threshold_deg=90.0)
shadow = moon.shadow.compute(sza=sza, threshold_deg=90.0)
```

`illumination` marks `sza <= threshold_deg` as 1, and `shadow` marks
`sza > threshold_deg` as 1. Use `method="terrain_ray"` for DEM-horizon shadowing.

```python
sza = moon.sza.compute(
    like=dem,
    time="2008-02-01T12:00:00Z",
    spice_kernels=("kernels/naif0012.tls", "kernels/de421.bsp", "kernels/moon_pa.bpc"),
)
shadow = moon.shadow.compute(method="terrain_ray", dem=dem, sza=sza)
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
