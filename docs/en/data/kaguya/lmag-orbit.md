# LMAG And Orbit

LMAG (Lunar MAGnetometer) measures the magnetic field at the spacecraft. The public files (`MAG_TS*.dat`) contain both the field and the spacecraft position,
so SOPRAN also computes orbit geometry (altitude, sub-spacecraft point, solar zenith angle) and whether field lines reach the surface from the same files.
Orbit geometry uses the LMAG sample times as they are.

## Variables

| Entry point | Dimensions | Units | Frame | Meaning |
|---|---|---|---|---|
| `kg.lmag.magnetic_field` | `time, component` | nT | `MOON_ME` | Magnetic field vector; alias `b` |
| `kg.lmag.magnetic_field_gse` | `time, component` | nT | `GSE` | GSE field contained in the files; alias `bgse` |
| `kg.lmag.magnetic_field_magnitude` | `time` | nT | | Field strength $\lvert B\rvert$; alias `bmag` |
| `kg.lmag.magnetic_connection` | `time` | | `MOON_ME` | Connection of field lines to the surface (below) |
| `kg.orbit.position` | `time, component` | km | `MOON_ME` | Spacecraft position |
| `kg.orbit.position_gse` | `time, component` | km | `GSE` | Spacecraft position |
| `kg.orbit.radial_distance` | `time` | km | | Distance from the lunar center |
| `kg.orbit.altitude` | `time` | km | | Altitude above a 1737.4 km sphere |
| `kg.orbit.subpoint` | `time, component` | deg | `MOON_ME` | Longitude and latitude of the sub-spacecraft point on the sphere |
| `kg.orbit.sza` | `time` | deg | | Solar zenith angle at the sub-spacecraft point |

```python
kg = spn.kaguya
time = spn.day("2008-01-01")

b = kg.lmag.magnetic_field.load(time)
altitude = kg.orbit.altitude.load(time)
spn.stack(kg.lmag.bmag.load(time).line(), altitude.line()).plot()
```

Orbit geometry and field-line connection are saved to the Store by default (`cache="use"`), so later loads only read them back.
Results loaded with `missing="empty"` or `"warn"` while source files were missing are not saved.

## Solar zenith angle

`kg.orbit.sza` computes the solar zenith angle at the sub-spacecraft point from the Sun direction given by SPICE.
When no kernels are passed and the download policy is not `never`, NAIF generic kernels are fetched automatically ([Coordinate Frames](../../guide/frames.md#getting-spice-kernels)).
To give the Sun direction yourself, use `sun_vector=`.

```python
sza = kg.orbit.sza.load(time)
sza = kg.orbit.sza.load(time, sun_vector=[1.0, 0.0, 0.0], sun_frame="MOON_ME")
```

Orbit positions can be transformed to another frame while loading by passing `frame=` and `context=` (a `FrameContext`).

## Field-line connection to the surface

`magnetic_connection` extends a straight line from the spacecraft along the local field direction and checks whether it meets a sphere of radius `radius_km` (default 1737.4 km).
Both the field direction (plus) and the opposite direction (minus) are checked (`direction="both"`).

```python
conn = kg.lmag.magnetic_connection.load(time)
conn.plot(kind="footpoint")      # footpoint, altitude, incidence, distance
conn.to_xarray()
```

| Variable | Meaning |
|---|---|
| `connected_any`, `connected_plus`, `connected_minus` | Whether either or each direction meets the sphere |
| `footpoint_plus_lon`, `footpoint_plus_lat`, … | Longitude and latitude of the intersection (deg) |
| `distance_plus_km`, `distance_minus_km` | Distance to the intersection |
| `incidence_angle_plus_deg`, `incidence_angle_minus_deg` | Acute angle between the field line and the surface normal |
| `altitude_km` | Spacecraft altitude |

This is a straight-line geometry and does not include field-line bending by crustal magnetic anomalies.
Tracing through a surface field model is available as an experimental API (`sopran.experimental.moon.svm3d`).

## Matching another instrument's times

To match the times of another instrument such as PACE, use `resample_like`.

```python
esa1 = kg.esa1.counts.load(time, missing="warn")
conn_on_esa1 = conn.resample_like(esa1, method="nearest", tolerance="2s")
altitude_on_esa1 = altitude.resample_like(esa1, method="linear", tolerance="10s")
```

The methods are listed in [Time Alignment](../../guide/alignment.md).

## Limitations

- There are no tests comparing the SPICE Sun direction and frame transforms with SPEDAS geometry yet.
- Altitude and sub-spacecraft points use a spherical Moon without terrain (DEM).
