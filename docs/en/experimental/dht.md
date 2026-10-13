# Pitch-Angle Spectra In The dHT Frame

`sopran.experimental.kaguya.dht` moves each KAGUYA ESA look velocity into the de Hoffmann–Teller (dHT) frame, in which the
motional electric field of the solar-wind flow vanishes, and recomputes pitch angle and energy from there.
It is meant for reading the electron distribution under the condition that the loss-cone boundary is fixed to the lunar surface.
Records whose field is nearly tangent to the surface have no dHT velocity, so the usable sample is much smaller than the plain
distribution. Keep the plain pitch-angle spectrum as the reference and use the dHT version as a comparison.

## Velocity convention

The order fixed by the September 2026 lunarsat validation (20-minute interval, 59 records) is implemented as is.

| Step | Content |
|---|---|
| 1 | Take $\boldsymbol V_\mathrm{GSE}$ from the OMNI HRO 5-minute sample whose lunar arrival time is nearest the record (within `omni_tolerance_seconds`) |
| 2 | Restore the Earth orbital aberration that NASA removed, once, as `+29.8 km/s` in $V_y$ (`restore_omni_aberration`) |
| 3 | Rotate GSE→J2000 with the Sun direction at the OMNI epoch, then J2000→`MOON_ME` at the record time |
| 4 | Subtract the Moon's geocentric velocity and build the HT velocity $\boldsymbol H_M=\boldsymbol u_M-\frac{\boldsymbol u_M\cdot\boldsymbol n}{\boldsymbol B\cdot\boldsymbol n}\boldsymbol B$ with the local radial as the normal |
| 5 | Subtract the spacecraft's selenocentric velocity and rotate into the look frame (default `SELENE_M_SPACECRAFT`) |
| 6 | Subtract this boost from every look velocity and recompute the pitch angle $\alpha'$ and energy $E'$ |

The lunar arrival time is $t_\mathrm{arrival}=t_\mathrm{OMNI}+(R_E\,\mathrm{BSN}_x-x_\mathrm{Moon,GSE})/V_\mathrm{sw}$;
`arrival_shift="none"` disables it. Moon and spacecraft velocities come from SPICE `spkezr` (DE421 and the SELENE SPK)
in inertial axes, and only 3×3 `pxform` rotations are applied.

Records with $|\boldsymbol B\cdot\boldsymbol n|/|\boldsymbol B|$ below `min_abs_b_normal_fraction` (default 0.15) are dropped as
`field_tangent`. In the April 2026 lunarsat full-period runs the dHT branch kept about 27% of the non-dHT fits.

## Usage

```python
import numpy as np
import sopran as spn
from sopran.experimental.kaguya.dht import DhtSettings, dht_pitch_angle_spectrum
from sopran.frames import FrameContext
from sopran.missions.kaguya.geometry import lmag_position, lmag_position_gse
from sopran.missions.kaguya.spice import selene_spice_kernels

kg = spn.Kaguya()
time = spn.period("2008-04-02T08:20", "2008-04-02T08:50")
calibration = kg.esa1.load_calibration()
esa1 = kg.esa1.load(time, calibration=calibration)
lmag = kg.lmag.load(time)
omni = spn.omni.hro.load(spn.period("2008-04-02T07:00", "2008-04-02T09:00"))
frames = FrameContext(spice_kernels=selene_spice_kernels(kg.store, time), default_backend="spiceypy")

result = dht_pitch_angle_spectrum(
    pace=esa1.pace,
    time=time,
    calibration=calibration,
    magnetic_field=lmag.magnetic_field,
    position=lmag_position(lmag),
    position_gse=lmag_position_gse(lmag),
    omni=omni,
    frame_context=frames,
    energy_edges_eV=np.geomspace(20.0, 1500.0, 10),
    pitch_bins=16,
    settings=DhtSettings(),
)
result.spectrum            # counts on time x energy band x pitch_angle (SopranArray)
result.frame.coverage()    # {"records": ..., "ok": ..., "field_tangent": ..., "omni_missing": ...}
result.frame.to_pandas()   # per-record boost, |B.n|/|B|, OMNI time offset
```

Shifted energies fall into the `energy_edges_eV` bands, so every record shares one grid. The `exposure` coordinate is the
look response summed with the factor $(E/E')^2$, so `counts / exposure` approximates the differential energy flux in the dHT
frame (Liouville's theorem). `exposure_unshifted` is the plain sum, `look_samples` the number of looks per cell, and
`shifted_energy_mean_eV` and `unshifted_pitch_mean_deg` the cell means.

The parts are available on their own: `frame_velocity()` gives the boost and diagnostics per record, `shift_looks()` the
per-look shift, `dht_tangential_velocity()` the HT velocity and `lunar_arrival_times()` the arrival times.

## Limits

- Only the motional electric field is removed; electrostatic potentials are not treated. `DhtSettings.look_sign` treats the look
  direction as the particle velocity direction (+1).
- Reasons for dropped records stay in `frame.status` (`ok`, `omni_missing`, `geometry_missing`, `field_tangent`, `spice_failed`).
  Report `coverage()` before plotting or fitting.
- The SPICE kernels must cover Earth, Moon and Sun (DE421), the spacecraft (SELENE SPK), the lunar orientation (`MOON_ME`) and
  the attitude (CK); `selene_spice_kernels` provides them.
- Sources: OMNI HRO documentation Appendix 4 (aberration), NAIF `spkezr`/`pxform`,
  lunarsat `working/kgy-er/notes/er-dht-velocity-convention-2026-09-27.md`.
