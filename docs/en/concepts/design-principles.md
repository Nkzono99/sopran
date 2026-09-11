# An API That Explains the Data

SOPRAN aims to make observation structure understandable through use, provide
a standard path to labeled plots, and retain direct access to native data.

`spn.kaguya.esa1.energy_flux` follows mission, instrument and physical quantity.
Types, completion, `info()`, units, frames and bin metadata should tell the same
story. Acquisition, calibration and caching are automated according to settings,
but sources, corrections and missing values remain inspectable.

```python
import sopran as spn

time = spn.day("2008-04-26")
plot = spn.kaguya.esa1.energy_flux.plot(time, calibration="auto")
data = spn.Kaguya().esa1.load(time)
source_files = data.files
native = data.pace
```

`files` identifies source files. `pace` exposes native headers and record arrays
and may be `None` for absent input. Keep these distinct from calibrated, rebinned,
or integrated products. `missions.kaguya.read_pace_pbf(files)` also reads supplied
files directly. Use `spn.view(...)` when several operations share context.

Heavy kernels use coarse-grained PyO3/Rust calls and return normal Python data
objects. Implementation details should not dictate the scientific API.
Reusable trials live in [experimental](../experimental/index.md), never as
dependencies of standard readers. Individual runs and reports belong in `working/`.
