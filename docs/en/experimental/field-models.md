# Field Models And Orbit Tools

Experimental tools for comparing ER results with field models and environment conditions. They return results and never
write to the Store on their own.

| Tool | Module | Purpose |
|---|---|---|
| Test-particle orbits | `sopran.experimental.moon.test_particle` | Electron orbits in SVM3D plus a uniform external field (Boris, magnetic only) |
| Closed-field islands | `sopran.experimental.moon.closure` | Connected components of closed cells on a grid |
| Field residual and quiet baseline | `sopran.experimental.kaguya.field_residual` | Decomposition of observed minus model field; quiet-time median baseline |
| Environment-response regression | `sopran.experimental.statistics.ridge` | Standardized ridge, track-grouped cross-validation, external-field gain |

## Test-particle orbits

```python
import numpy as np
from sopran.experimental.moon.svm3d import SVM3DShellGrid
from sopran.experimental.moon.test_particle import (
    TestParticleSettings, electron_velocity_me, trace_test_particles,
)

grid = SVM3DShellGrid.load("svm3d_shell_grid.npz")
r0 = np.array([[1737.4 + 100.0, 0.0, 0.0]])              # MOON_ME [km]
b_external = np.array([[2.0, -1.0, 4.0]])                  # uniform external field [nT]
b_local = b_external + grid.field_at(r0)
v0 = electron_velocity_me([200.0], [150.0], [0.0], b_local)   # 200 eV, pitch angle 150°
settings = TestParticleSettings.for_field(float(np.linalg.norm(b_local)), gyrations=500.0)
result = trace_test_particles(grid, r0, v0, b_external, settings=settings)
result.status                       # "surface_hit" / "returned" / "escaped" / "max_steps" ...
result.arrays["spacecraft_shell_pitch_deg"]   # pitch angle where the orbit returned to the start radius
```

`for_field` uses $1/120$ of the gyro period as the time step and `gyrations` for the step budget. Reaching
`stop_altitude_km` (default 6.1 km, the lower shell) gives `surface_hit`, exceeding `escape_altitude_km` gives `escaped`,
and re-entering `return_radius_km` around the start gives `returned`. `spacecraft_shell_*` is the state at the first
upward crossing of the start radius, the quantity to compare with a reflected electron seen at the spacecraft.
There is no electric field, and outside the shell grid (`bounds="nan"`) the status is `invalid_field`.

## Closed-field islands

```python
from sopran.experimental.moon.closure import classify_closed_islands

islands = classify_closed_islands(
    lon_deg, lat_deg, closed_like, path_max_nT, footpoint_separation_deg,
    min_path_max_nT=10.0, min_footpoint_separation_deg=5.0, min_cells=3,
)
islands.island_id, islands.island_count
```

On a complete longitude × latitude grid, cells with `closed_like` true, path maximum and footpoint separation above the
thresholds are connected with four neighbours and longitude wraparound; components smaller than `min_cells` are dropped.
The physical meaning of the thresholds is the caller's.

## Field residual and quiet baseline

```python
from sopran.experimental.kaguya.field_residual import (
    quiet_field_baseline, residual_decomposition, svm3d_residual,
)

residual = svm3d_residual(grid, position_me_km, observed_nT)   # observed − SVM3D
residual.parallel_nT, residual.perpendicular_abs_nT, residual.fractional_abs
baseline = quiet_field_baseline(lon_deg, lat_deg, b_sc_nT, quiet_mask, grid_deg=10.0, min_events=5)
compression = b_sc_nT / baseline.value          # B_sc / B_quiet
```

`residual_decomposition(observed, base, direction)` returns the residual vector, its component along `direction`
(default: the observed direction), the perpendicular magnitude and $|\text{residual}|/|\text{base}|$.
`quiet_field_baseline` takes the median per `grid_deg` cell over the `quiet_mask` rows; cells with fewer than
`min_events` use the global median, then `fallback`, and `source` records which one. In the lunarsat analysis `quiet` meant
pressure and IMF below their medians outside the tail, and most of the ER field response to the solar wind was explained
by $B_\mathrm{sc}/B_\mathrm{quiet}$.

## Environment-response regression

```python
from sopran.experimental.statistics.ridge import (
    external_gain, feature_drop_diagnostics, grouped_cv_predictions, model_ladder,
)

ladder = model_ladder(
    frame, targets=["log_b_eff"],
    specs=[("local", ["log_b_sc"]), ("physical", ["log_b_sc", "log_pressure", "imf_abs"])],
    alpha=1.0, folds=5, seed=0, group_column="track_id",
)
ladder.metrics          # train_r2 / cv_r2 / n_rows
drops = feature_drop_diagnostics(
    frame, target="log_b_eff",
    feature_groups={"local": ["log_b_sc"], "upstream": ["log_pressure", "imf_abs"]},
    alpha=1.0, group_column="track_id",
)
gain = external_gain(base_x, physical_x, log_target, alpha=1.0, eps=0.25)
gain.external_gain, gain.corrected
```

Features are standardized with the training rows and the intercept is not penalized. With `group_column`, rows sharing a
value stay in one fold, so `cv_r2` measures prediction across tracks. `external_gain` takes the difference of the
log predictions of the base and physical models as the gain $\exp(\Delta)$ and returns
`corrected = max(exp(y − Δ) − eps, 0)`. The regression metrics describe correlation, not causation.

## Limits

- Test particles are valid for a magnetic-only, uniform external field within the interpolation accuracy of the SVM3D
  shell grid; the altitude range of the grid (default 6.1–200 km) cannot be left.
- The physical reading of a residual (external field, induced field, model error) does not follow from the decomposition.
- Regression outputs are not written to the Store; save them together with the settings and input provenance.
