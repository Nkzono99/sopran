# Moon Maps

Maps fixed to the lunar surface, such as terrain (DEM), surface magnetic field (SVM), solar zenith angle, illumination, and shadow,
are handled through the body `spn.moon` rather than a mission. Whichever mission a map comes from, it means the same thing in use:
a quantity on lunar longitude and latitude. GeoTIFF maps are read with `rasterio` (`moon` extra).

```python
moon = spn.moon
region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")

dem = moon.dem.load(source="lro.lola.dem_118m", region=region)
sza = moon.sza.compute(like=dem, subsolar_lon_lat=(0.0, 0.0))
shadow = moon.shadow.compute(method="terrain_ray", dem=dem, sza=sza)
```

## Map types

| Entry point | Aliases | Units | Meaning |
|---|---|---|---|
| `moon.dem` | `elevation`, `height` | m | Elevation |
| `moon.svm` | `surface_vector_map`, `svm_tsunakawa2015` | nT | Tsunakawa et al. (2015) surface magnetic field map; the default SVM |
| `moon.svm_ravat2020` | — | nT | Ravat et al. (2020) surface field model with a selectable component |
| `moon.sza` | `solar_zenith_angle` | deg | Solar zenith angle |
| `moon.illumination` | `illumination_map` | fraction | Illumination |
| `moon.shadow` | `shadow_map` | fraction | Shadow |

Maps can also be selected by name, as in `moon.map("elevation")`. Loaded maps are `RasterLayer` objects, and
`dem.sample(lat=0.5, lon=10.5)` returns values at arbitrary points. Each map's `info()`, `guide()`, `example()`,
and `sources()` describe it and its available sources.

## Coordinate conventions

Longitude and latitude definitions are never implicit; they are kept in the plan (`plan()`) and in result metadata.

| Key | Example values | Default |
|---|---|---|
| `lon_domain` | `0_360`, `-180_180` | `0_360` |
| `lon_direction` | `east_positive`, `west_positive` | `east_positive` |
| `lat_type` | `planetocentric`, `planetographic` | `planetocentric` |
| `shape` | `spherical`, `spice_body_radii` | `spherical` |
| `projection` | `native`, `polar_stereographic` | `native` |
| `area_or_point` | `area`, `point` | `area` |

Regions crossing 0/360 can be written as `spn.Region(lon=(350, 10), ...)` ([Time, Regions, And Cases](../../guide/views-cases.md#regions-carry-their-longitude-convention)).

```python
plan = moon.dem.plan(source="lro.lola.dem_118m", region=region, projection="polar_stereo")
plan.to_metadata()      # check conventions and inputs before reading
```

## DEM

| `source` | Contents | Size |
|---|---|---|
| `lro.lola.dem_118m` (`lro.lola.dem`) | LRO LOLA global DEM, 256 pixels/deg (118 m at the equator) | About 8 GB |
| `lro.lola.sldem2015_59m` (`kaguya.tc.dem`) | SLDEM2015, merged LOLA and KAGUYA Terrain Camera, 512 pixels/deg, 60°S–60°N | About 22 GB |

Both download directly from USGS into the Store's `raw/moon/dem/`.

```python
path = moon.dem.download(source="lro.lola.dem_118m")      # into the default Store
dem = moon.dem.load(path=path, source="lro.lola.dem_118m", region=region)
```

Without `path=`, `load()` reads the file in the Store's `raw/moon/dem/`. When it is missing, the same download policy as other data applies
([Configuration](../../guide/configuration.md#download-policy), default `missing`), so the file is retrieved first.
DEMs are 8–22 GB; to avoid retrieval, pass `download="never"` or set the session or View policy to `never`.
Missing files then raise `DatasetNotFoundError`.
Choose the Store with `store=`; otherwise `spn.moon` uses the session settings and `view.moon` the Store of its Project.

With `region=`, only the part of the file covering the region is read.
Regions crossing 0/360 cannot be split into windows yet, so the whole file is read.

## Surface magnetic field (SVM)

The Tsunakawa SVM (`LunarSVM_000_02_v02.dat`, ver. 2) gives the three surface components of the lunar magnetic anomalies
derived from low-altitude Kaguya and Lunar Prospector magnetometer data
([Tsunakawa et al. 2015](https://doi.org/10.1002/2014JE004785); ver. 2 in [Tsunakawa et al. 2023](https://doi.org/10.20637/00049167)).
`moon.svm.download()` fetches the file that the LMAG team distributes on Google Drive as a supplement of the 2023 paper and
places it in the Store's `raw/moon/svm/` only when it matches the registered SHA-256. With the default download policy
(`missing`), `load()` fetches it when the file is absent.

```python
path = moon.svm.download()                      # about 165 MB, into the Store
svm = moon.svm.load()                           # read from the Store, fetching it if absent
svm = moon.svm.load(path="/path/to/LunarSVM_000_02_v02.dat")
svm.sample(lat=-0.5, lon=0.0)
```

The distributor's folder ([globalSVM_v02_2022](https://drive.google.com/drive/folders/108u0-lGucZ5yXKA-rVksGPGR8sj0SF8U))
also holds the files below. SOPRAN does not fetch them automatically; download them in a browser when you need them.

| File | Contents |
|---|---|
| `LunarSVM_SHC_v02.dat` | Spherical harmonic coefficients $g_n^m, h_n^m$ ($n\le450$, $R=1737.4$ km). About 4 MB; regenerates the grid and the field at any altitude |
| `Bcal_v02.f90` | The official Fortran program that computes the field above the surface from the surface Br |
| `Positions.dat`, `B_Positions_v02.rst` | Example input and output of `Bcal_v02.f90`, used to validate SVM3D |
| `Readme_v02.txt` | Outline of the ver. 2 data selection and processing |

Ver. 1 (2015) is in [globalSVM_v01_2015](https://drive.google.com/drive/folders/1eCsFu5h3ZsZ2b0sadX6uQLfOHGHb6_Zz) of the same
supplement, together with the lists of observation periods used (`Periods_KGused.dat`, `Periods_LPused.dat`).
The original location `http://www.geo.titech.ac.jp/lab/tsunakawa/Kaguya_LMAG` was unreachable as of October 2026.

The distributor states no license. SOPRAN neither bundles nor redistributes the files; it only links to the distributor and
provides the download procedure. Cite Tsunakawa et al. (2015, 2023) when you use the map.

The Ravat et al. (2020) model (`moon.svm_ravat2020`) is a surface field derived from along-track magnetic field gradients
of Lunar Prospector and KAGUYA. It is given on a 0.1-degree grid on the lunar ellipsoid (equatorial radius 1738.1 km,
polar radius 1736.0 km), and `component=` selects the component.

| `component` | Meaning |
|---|---|
| `"total"` (default) | Total field |
| `"br"` | Radial component (positive outward) |
| `"btheta"` | Colatitudinal component (positive southward) |
| `"bphi"` | Azimuthal component (positive eastward) |

The University of Kentucky repository that distributes it ([DOI 10.13023/9wpe-tt68](https://doi.org/10.13023/9wpe-tt68), CC0)
stops scripted downloads with a browser check, so SOPRAN cannot retrieve it. Download the main file
`Ravatetal_JGR2020_LunarL1MagneticModelFields_LPgrad.dat` (about 88 MB) in a web browser and place it in the Store's `raw/moon/svm/`
or pass it as `path=`. Loading builds the grid from about 6.5 million rows and takes a few seconds.

```python
br = moon.svm_ravat2020.load(component="br")    # read from the Store's raw/moon/svm/
br.sample(lat=8.0, lon=302.0)                   # near Reiner Gamma
```

## Solar zenith angle, illumination, and shadow

`moon.sza.compute()` computes the solar zenith angle on a spherical Moon. Give the grid as an existing map (`like=`) or with `lon=`, `lat=`, `region=`.
Give the Sun position with one of:

| Argument | Sun position |
|---|---|
| `sun_vector=` | Sun direction vector in Moon-fixed coordinates |
| `subsolar_lon_lat=` | Longitude and latitude of the subsolar point |
| `time=` and `spice_kernels=` | Computed with SPICE (needs leap-second, lunar frame, and ephemeris kernels) |

```python
sza = moon.sza.compute(like=dem, subsolar_lon_lat=(0.0, 0.0))
illumination = moon.illumination.compute(sza=sza, threshold_deg=90.0)   # 1 where sza <= 90
shadow = moon.shadow.compute(sza=sza, threshold_deg=90.0)               # 1 where sza > 90
```

Threshold illumination and shadow are binary maps without terrain. Shadows cast by topography use `method="terrain_ray"`,
which follows the horizon over the DEM toward the Sun.

```python
sza = moon.sza.compute(
    like=dem,
    time="2008-02-01T12:00:00Z",
    spice_kernels=("kernels/naif0012.tls", "kernels/de421.bsp", "kernels/moon_pa.bpc"),
)
shadow = moon.shadow.compute(method="terrain_ray", dem=dem, sza=sza)
```

## Limitations

- Reprojection and bilinear interpolation are not implemented; `projection` is used for records and plans.
- The Sun is treated as a point source, so partial shadow (penumbra) is not computed.
- `terrain_ray` is slow on large DEMs, and numerical validation with public DEMs and real SPICE kernels has not been done.

To search anomaly locations from published tables, use the [Magnetic Anomaly Catalog](magnetic-anomalies.md).
