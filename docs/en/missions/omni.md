# OMNI

Loading requires `xarray`; plotting requires `matplotlib`.
Install these optional dependencies with `pip install xarray matplotlib`.

SOPRAN supports NASA OMNI2 **hourly ASCII** data, with automatic annual-file downloads
to `Store.raw_path("omni", "omni2_YYYY.dat")`. Existing ER-run caches are reusable.

```python
import sopran as spn

spn.config.use(store="F:/sopran_data", download="missing")
time = spn.day("2008-05-01")
data = spn.omni.load(time)
frame = data.to_dataframe()  # scalar variables, UTC pandas index
dataset = data.to_xarray()  # includes the GSE magnetic vector
result = spn.omni.pressure.plot(time)
result = spn.view(time=time).omni.magnetic_field.plot()

context = spn.omni.at(["2008-05-01T00:10:00Z", "2008-05-01T01:00:00Z"])
```

Main endpoints include `pressure` (nPa), `speed` (km/s), proton `density` (cm^-3),
proton `temperature` (K), GSE `magnetic_field` (nT), `b_magnitude` (nT), `bz_gsm` (nT),
`kp`, `dst`, `ae`, `beta`, and `alfven_mach`.
`b_magnitude` is the average scalar field strength, not the magnitude of the average vector.
The published pressure is retained, not recalculated. Kp×10 is converted to Kp.

Additional scalar fields are available through `data["name"]` and
`spn.omni.variable("name")`: `bx_gse`, `by_gse`, `bz_gse`, `by_gsm`,
`alpha_proton_ratio`, `electric_field`, `al`, `au`, `magnetosonic_mach`,
`imf_spacecraft_id`, `plasma_spacecraft_id`, `imf_sample_count`, `plasma_sample_count`.
Variables return `SopranArray` with units and applicable GSE/GSM metadata.

`at()` matches the containing UTC hour, without interpolation or forward filling.
Input order and duplicate timestamps are preserved. `source_time` is `NaT` for a
missing source-hour record; individual missing values remain `NaN`. Naive input times
mean UTC. NaT targets are rejected.
`load(start, stop)` selects hourly labels in `[start, stop)`, so a 00:30 start excludes
the 00:00 label; use `at()` for interval-based context matching.

Downloads support `missing` (default), `never`, and `always`. Successful downloads
are validated before atomic replacement and receive a Store checksum manifest.
Use `always` to refresh a changing annual product. Failed downloads preserve prior data.
Explicit clients use `spn.Omni(store=..., download=..., timeout_seconds=90)`.

Only hourly ASCII and the listed fields are supported, not 1/5-minute OMNI or CDF.
View frame settings do not rotate OMNI data. OMNI is near-Earth context, not a direct
local lunar upstream measurement; no additional lunar propagation shift or regime
classification is performed. The existing ER runner and its reader are unchanged.

Sources: [NASA OMNI documentation](https://omniweb.gsfc.nasa.gov/html/ow_data.html),
[SPDF public files](https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/).
