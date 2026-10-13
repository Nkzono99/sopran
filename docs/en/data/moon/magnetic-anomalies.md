# Magnetic Anomaly Catalog

`spn.moon.magnetic_anomalies()` returns a list of lunar magnetic anomalies built from published location tables, as a `pandas.DataFrame`.
The tables are bundled with the package, so no network access or SVM file is needed.

```python
import sopran as spn

sites = spn.moon.magnetic_anomalies()       # corrected Blewett (2011) table, 15 entries
sites[["name", "lon_deg", "lat_deg", "peak_field_30km_nt", "swirl"]]

# substring match on name and feature_id; handles Gamma/γ, hyphens, and underscores
reiner = spn.moon.magnetic_anomalies("all", name="Reiner Gamma")

# search near (east longitude, latitude); 57.5°W can be -57.5 or 302.5
nearby = spn.moon.magnetic_anomalies("all", near=(-57.5, 7.5), radius_deg=5)

# analysis centers of isolated anomalies and the observation radii used in the paper
isolated = spn.moon.magnetic_anomalies("oliveira2017")
```

## Included tables

| `catalog` | Contents | Source |
|---|---|---|
| `blewett2011` (default) | 15 entries: approximate location, peak field at 30 km altitude, terrain setting, swirl classification at the time | [Blewett et al. (2011), corrected Table 1](https://doi.org/10.1029/2011JE003852) |
| `oliveira2017` | 15 entries: analysis centers of isolated anomalies, observation radius $r_o$, dipole placement radius $r_d$ | [Oliveira & Wieczorek (2017), Table 1](https://doi.org/10.1002/2016JE005199) |
| `all` | 30 rows from both tables, 23 `feature_id` values; different published values for the same region stay in separate rows | Both tables |

This is the list of regions chosen in the literature, not a complete inventory of lunar magnetic anomalies.
`name` keeps the published spelling, and `feature_id` links Reiner-γ with Reiner Gamma and Sirsalis with Rima Sirsalis.
Rows with different coordinates are never averaged or merged. Blewett's original paper has coordinate errors, so the corrected table is used.

## Columns

| Column | Meaning |
|---|---|
| `lon_deg`, `lat_deg` | Published Moon-fixed coordinates, east longitude 0–360°, north latitude positive. No precise MOON_ME/MOON_PA conversion is applied |
| `position_kind` | `approximate_anomaly_location` for approximate locations, `analysis_center` for the center of an analysis region |
| `peak_field_30km_nt` | Estimated regional peak $\lvert B\rvert$ at 30 km altitude (nT); not a surface value or a point value at the listed coordinates |
| `setting`, `swirl` | Terrain and swirl classification from Blewett's table; `not_recognized` means not recognized as of 2011 |
| `observation_radius_deg`, `dipole_radius_deg` | Angular radii of the analysis regions in Oliveira's paper; not physical boundaries or sizes of the anomalies |
| `reference_doi`, `note` | Per-row source and notes; Marginis has sparse Lunar Prospector magnetometer coverage |
| `distance_deg`, `distance_km` | Only with `near`: great-circle distance to the listed coordinates; km uses a lunar radius of 1737.4 km |

Values absent from the literature are missing. With `near`, rows are sorted by distance, and `radius_deg` keeps rows whose listed point is within that angular distance.
It cannot test intersections with regions. Give `radius_deg` together with `near`, between 0 and 180°.
Empty results keep their columns and the `DataFrame.attrs` metadata.

## Combining with the SVM

To combine the location table with the SVM, pass the coordinates to the SVM's `sample()`. The added column is the SVM point value,
a different quantity from the published regional peak.

```python
svm = spn.moon.svm.load(path="/path/to/LunarSVM_000_02_v02.dat")
sites["svm_surface_point_nt"] = svm.sample(lat=sites.lat_deg, lon=sites.lon_deg)
```
