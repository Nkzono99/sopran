//! Test-particle (Boris) electron orbits in ``B_external + B_SVM3D`` fields.
//!
//! A pilot-grade magnetic-only forward model: no electric field, a spatially
//! uniform external field plus the SVM3D shell grid. Python owns the source
//! sampling and the physical interpretation; this module integrates orbits and
//! records where each particle ended.

use crate::svm3d::{ShellGrid, MOON_RADIUS_KM};
use numpy::{
    IntoPyArray, PyReadonlyArray1, PyReadonlyArray2, PyReadonlyArray4, PyUntypedArrayMethods,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use rayon::prelude::*;

const RAD_TO_DEG: f64 = 180.0 / std::f64::consts::PI;
/// Electron charge-to-mass ratio in C/kg (negative charge).
const ELECTRON_Q_OVER_M_C_PER_KG: f64 = -1.758_820_010_76e11;
/// ``0.5 * q/m * 1e-9`` converts ``dt [s] * B [nT]`` to the Boris rotation vector.
const HALF_QM_B_NT_TO_DIMLESS: f64 = 0.5e-9 * ELECTRON_Q_OVER_M_C_PER_KG;

pub(crate) const STATUS_INVALID_INPUT: i32 = 0;
pub(crate) const STATUS_RETURNED: i32 = 1;
pub(crate) const STATUS_SURFACE_HIT: i32 = 2;
pub(crate) const STATUS_ESCAPED: i32 = 3;
pub(crate) const STATUS_MAX_STEPS: i32 = 4;
pub(crate) const STATUS_INVALID_FIELD: i32 = 5;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum GridBounds {
    Nan,
    Clamp,
}

impl GridBounds {
    fn parse(value: &str) -> Result<Self, String> {
        match value {
            "nan" => Ok(Self::Nan),
            "clamp" => Ok(Self::Clamp),
            other => Err(format!("bounds must be 'nan' or 'clamp', got {other}")),
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct TestParticleTrace {
    pub(crate) status_code: i32,
    pub(crate) steps: u32,
    pub(crate) flight_time_s: f64,
    pub(crate) path_km: f64,
    pub(crate) closest_sc_distance_km: f64,
    pub(crate) min_alt_km: f64,
    pub(crate) max_alt_km: f64,
    pub(crate) spacecraft_shell_crossed: bool,
    pub(crate) spacecraft_shell_cross_time_s: f64,
    pub(crate) spacecraft_shell_distance_to_sc_km: f64,
    pub(crate) spacecraft_shell_r_me_km: [f64; 3],
    pub(crate) spacecraft_shell_v_me_km_s: [f64; 3],
    pub(crate) spacecraft_shell_b_me_nt: [f64; 3],
    pub(crate) spacecraft_shell_pitch_deg: f64,
    pub(crate) final_r_me_km: [f64; 3],
    pub(crate) final_v_me_km_s: [f64; 3],
    pub(crate) final_b_me_nt: [f64; 3],
    pub(crate) final_pitch_deg: f64,
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct TraceSettings {
    pub(crate) dt_s: f64,
    pub(crate) max_steps: usize,
    pub(crate) stop_alt_km: f64,
    pub(crate) escape_alt_km: f64,
    pub(crate) return_radius_km: f64,
    pub(crate) min_return_steps: usize,
    pub(crate) svm_scale: f64,
    pub(crate) bounds: GridBounds,
}

impl TraceSettings {
    fn validate(&self) -> Result<(), String> {
        if !self.dt_s.is_finite() || self.dt_s <= 0.0 {
            return Err("dt_s must be finite and positive".to_string());
        }
        if self.max_steps == 0 {
            return Err("max_steps must be positive".to_string());
        }
        if !self.stop_alt_km.is_finite()
            || !self.escape_alt_km.is_finite()
            || self.escape_alt_km <= self.stop_alt_km
        {
            return Err("escape_alt_km must be finite and greater than stop_alt_km".to_string());
        }
        if !self.return_radius_km.is_finite() || self.return_radius_km <= 0.0 {
            return Err("return_radius_km must be finite and positive".to_string());
        }
        if !self.svm_scale.is_finite() {
            return Err("svm_scale must be finite".to_string());
        }
        Ok(())
    }
}

pub(crate) fn simulate_batch(
    grid: &ShellGrid,
    r0_me_km: &[[f64; 3]],
    v0_me_km_s: &[[f64; 3]],
    b_external_nt: &[[f64; 3]],
    return_center_me_km: Option<&[[f64; 3]]>,
    settings: TraceSettings,
) -> Result<Vec<TestParticleTrace>, String> {
    settings.validate()?;
    if r0_me_km.len() != v0_me_km_s.len() || r0_me_km.len() != b_external_nt.len() {
        return Err("r0, v0 and b_external must have the same number of rows".to_string());
    }
    if let Some(center) = return_center_me_km {
        if center.len() != r0_me_km.len() {
            return Err("return_center must match r0 rows".to_string());
        }
    }
    Ok((0..r0_me_km.len())
        .into_par_iter()
        .map(|row| {
            simulate_one(
                grid,
                r0_me_km[row],
                v0_me_km_s[row],
                b_external_nt[row],
                return_center_me_km.map_or(r0_me_km[row], |center| center[row]),
                settings,
            )
        })
        .collect())
}

fn simulate_one(
    grid: &ShellGrid,
    r0: [f64; 3],
    v0: [f64; 3],
    b_external: [f64; 3],
    return_center: [f64; 3],
    settings: TraceSettings,
) -> TestParticleTrace {
    let invalid = || invalid_trace(r0, v0);
    if !finite3(r0) || !finite3(v0) || !finite3(b_external) || !finite3(return_center) {
        return invalid();
    }
    let speed0 = norm3(v0);
    let alt0 = norm3(r0) - MOON_RADIUS_KM;
    if !speed0.is_finite() || speed0 <= 0.0 || !alt0.is_finite() {
        return invalid();
    }
    let stop_radius = MOON_RADIUS_KM + settings.stop_alt_km;
    let escape_radius = MOON_RADIUS_KM + settings.escape_alt_km;
    let dt_s = settings.dt_s;
    let mut r = r0;
    let mut v = v0;
    let mut path_km = 0.0;
    let mut closest_sc_distance_km = f64::INFINITY;
    let mut min_alt_km = alt0;
    let mut max_alt_km = alt0;
    let spacecraft_radius = norm3(return_center);
    let mut shell_cross = ShellCrossing::default();
    let mut went_below_spacecraft_shell = false;
    let mut went_outside_return_sphere = false;

    for step in 1..=settings.max_steps {
        let Some(b_prev) = total_field(grid, r, b_external, settings) else {
            return invalid_field_trace(
                step - 1,
                path_km,
                closest_sc_distance_km,
                min_alt_km,
                max_alt_km,
                shell_cross,
                r,
                v,
            );
        };
        let v_next = boris_rotate(v, b_prev, dt_s);
        let r_next = add3(r, scale3(v_next, dt_s));
        if !finite3(r_next) || !finite3(v_next) {
            return invalid_field_trace(
                step - 1,
                path_km,
                closest_sc_distance_km,
                min_alt_km,
                max_alt_km,
                shell_cross,
                r,
                v,
            );
        }
        path_km += distance3(r, r_next);
        let next_radius = norm3(r_next);
        let alt_next = next_radius - MOON_RADIUS_KM;
        min_alt_km = min_alt_km.min(alt_next);
        max_alt_km = max_alt_km.max(alt_next);
        let dist_next = distance3(return_center, r_next);
        closest_sc_distance_km = closest_sc_distance_km.min(dist_next);
        let prev_radius = norm3(r);
        if dist_next > settings.return_radius_km {
            went_outside_return_sphere = true;
        }
        if next_radius < spacecraft_radius {
            went_below_spacecraft_shell = true;
        }
        if !shell_cross.crossed
            && step >= settings.min_return_steps
            && went_below_spacecraft_shell
            && prev_radius < spacecraft_radius
            && next_radius >= spacecraft_radius
        {
            let cross_r = interpolate_sphere_crossing(r, r_next, [0.0; 3], spacecraft_radius)
                .unwrap_or(r_next);
            let cross_b = total_field(grid, cross_r, b_external, settings).unwrap_or([f64::NAN; 3]);
            shell_cross = ShellCrossing::from_state(
                step,
                dt_s,
                cross_r,
                v_next,
                cross_b,
                distance3(return_center, cross_r),
            );
        }
        if next_radius <= stop_radius {
            let hit =
                interpolate_sphere_crossing(r, r_next, [0.0; 3], stop_radius).unwrap_or(r_next);
            let b_hit = total_field(grid, hit, b_external, settings).unwrap_or([f64::NAN; 3]);
            return finish_trace(
                STATUS_SURFACE_HIT,
                step,
                dt_s,
                path_km,
                closest_sc_distance_km,
                min_alt_km,
                max_alt_km,
                shell_cross,
                hit,
                v_next,
                b_hit,
            );
        }
        if step >= settings.min_return_steps && went_outside_return_sphere {
            let prev_dist = distance3(return_center, r);
            if dist_next <= settings.return_radius_km
                || (prev_dist > settings.return_radius_km && dist_next < settings.return_radius_km)
            {
                let hit = interpolate_sphere_crossing(
                    r,
                    r_next,
                    return_center,
                    settings.return_radius_km,
                )
                .unwrap_or(r_next);
                let b_hit = total_field(grid, hit, b_external, settings).unwrap_or([f64::NAN; 3]);
                return finish_trace(
                    STATUS_RETURNED,
                    step,
                    dt_s,
                    path_km,
                    closest_sc_distance_km,
                    min_alt_km,
                    max_alt_km,
                    shell_cross,
                    hit,
                    v_next,
                    b_hit,
                );
            }
        }
        if next_radius >= escape_radius {
            let hit =
                interpolate_sphere_crossing(r, r_next, [0.0; 3], escape_radius).unwrap_or(r_next);
            let b_hit = total_field(grid, hit, b_external, settings).unwrap_or([f64::NAN; 3]);
            return finish_trace(
                STATUS_ESCAPED,
                step,
                dt_s,
                path_km,
                closest_sc_distance_km,
                min_alt_km,
                max_alt_km,
                shell_cross,
                hit,
                v_next,
                b_hit,
            );
        }
        r = r_next;
        v = v_next;
    }
    let b_final = total_field(grid, r, b_external, settings).unwrap_or([f64::NAN; 3]);
    finish_trace(
        STATUS_MAX_STEPS,
        settings.max_steps,
        dt_s,
        path_km,
        closest_sc_distance_km,
        min_alt_km,
        max_alt_km,
        shell_cross,
        r,
        v,
        b_final,
    )
}

fn total_field(
    grid: &ShellGrid,
    r_me_km: [f64; 3],
    b_external_nt: [f64; 3],
    settings: TraceSettings,
) -> Option<[f64; 3]> {
    let b_svm = if settings.svm_scale == 0.0 {
        [0.0; 3]
    } else {
        grid.field_at(r_me_km, settings.bounds == GridBounds::Clamp)?
    };
    Some(add3(b_external_nt, scale3(b_svm, settings.svm_scale)))
}

fn boris_rotate(v_me_km_s: [f64; 3], b_me_nt: [f64; 3], dt_s: f64) -> [f64; 3] {
    let t = scale3(b_me_nt, HALF_QM_B_NT_TO_DIMLESS * dt_s);
    let t2 = dot3(t, t);
    let s = scale3(t, 2.0 / (1.0 + t2));
    let v_prime = add3(v_me_km_s, cross3(v_me_km_s, t));
    add3(v_me_km_s, cross3(v_prime, s))
}

#[allow(clippy::too_many_arguments)]
fn finish_trace(
    status_code: i32,
    steps: usize,
    dt_s: f64,
    path_km: f64,
    closest_sc_distance_km: f64,
    min_alt_km: f64,
    max_alt_km: f64,
    shell_cross: ShellCrossing,
    final_r_me_km: [f64; 3],
    final_v_me_km_s: [f64; 3],
    final_b_me_nt: [f64; 3],
) -> TestParticleTrace {
    TestParticleTrace {
        status_code,
        steps: steps as u32,
        flight_time_s: steps as f64 * dt_s,
        path_km,
        closest_sc_distance_km,
        min_alt_km,
        max_alt_km,
        spacecraft_shell_crossed: shell_cross.crossed,
        spacecraft_shell_cross_time_s: shell_cross.time_s,
        spacecraft_shell_distance_to_sc_km: shell_cross.distance_to_sc_km,
        spacecraft_shell_r_me_km: shell_cross.r_me_km,
        spacecraft_shell_v_me_km_s: shell_cross.v_me_km_s,
        spacecraft_shell_b_me_nt: shell_cross.b_me_nt,
        spacecraft_shell_pitch_deg: shell_cross.pitch_deg,
        final_r_me_km,
        final_v_me_km_s,
        final_b_me_nt,
        final_pitch_deg: pitch_deg(final_v_me_km_s, final_b_me_nt),
    }
}

fn invalid_trace(final_r_me_km: [f64; 3], final_v_me_km_s: [f64; 3]) -> TestParticleTrace {
    TestParticleTrace {
        status_code: STATUS_INVALID_INPUT,
        steps: 0,
        flight_time_s: 0.0,
        path_km: 0.0,
        closest_sc_distance_km: f64::NAN,
        min_alt_km: f64::NAN,
        max_alt_km: f64::NAN,
        spacecraft_shell_crossed: false,
        spacecraft_shell_cross_time_s: f64::NAN,
        spacecraft_shell_distance_to_sc_km: f64::NAN,
        spacecraft_shell_r_me_km: [f64::NAN; 3],
        spacecraft_shell_v_me_km_s: [f64::NAN; 3],
        spacecraft_shell_b_me_nt: [f64::NAN; 3],
        spacecraft_shell_pitch_deg: f64::NAN,
        final_r_me_km,
        final_v_me_km_s,
        final_b_me_nt: [f64::NAN; 3],
        final_pitch_deg: f64::NAN,
    }
}

#[allow(clippy::too_many_arguments)]
fn invalid_field_trace(
    steps: usize,
    path_km: f64,
    closest_sc_distance_km: f64,
    min_alt_km: f64,
    max_alt_km: f64,
    shell_cross: ShellCrossing,
    final_r_me_km: [f64; 3],
    final_v_me_km_s: [f64; 3],
) -> TestParticleTrace {
    TestParticleTrace {
        status_code: STATUS_INVALID_FIELD,
        steps: steps as u32,
        flight_time_s: f64::NAN,
        path_km,
        closest_sc_distance_km,
        min_alt_km,
        max_alt_km,
        spacecraft_shell_crossed: shell_cross.crossed,
        spacecraft_shell_cross_time_s: shell_cross.time_s,
        spacecraft_shell_distance_to_sc_km: shell_cross.distance_to_sc_km,
        spacecraft_shell_r_me_km: shell_cross.r_me_km,
        spacecraft_shell_v_me_km_s: shell_cross.v_me_km_s,
        spacecraft_shell_b_me_nt: shell_cross.b_me_nt,
        spacecraft_shell_pitch_deg: shell_cross.pitch_deg,
        final_r_me_km,
        final_v_me_km_s,
        final_b_me_nt: [f64::NAN; 3],
        final_pitch_deg: f64::NAN,
    }
}

fn pitch_deg(v_me_km_s: [f64; 3], b_me_nt: [f64; 3]) -> f64 {
    let speed = norm3(v_me_km_s);
    let b_norm = norm3(b_me_nt);
    if !speed.is_finite() || speed <= 0.0 || !b_norm.is_finite() || b_norm <= 0.0 {
        return f64::NAN;
    }
    let cos_pitch = (dot3(v_me_km_s, b_me_nt) / (speed * b_norm)).clamp(-1.0, 1.0);
    cos_pitch.acos() * RAD_TO_DEG
}

fn interpolate_sphere_crossing(
    prev: [f64; 3],
    next: [f64; 3],
    center: [f64; 3],
    radius: f64,
) -> Option<[f64; 3]> {
    let p0 = sub3(prev, center);
    let p1 = sub3(next, center);
    let d = sub3(p1, p0);
    let a = dot3(d, d);
    let b = 2.0 * dot3(p0, d);
    let c = dot3(p0, p0) - radius * radius;
    if !a.is_finite() || a <= 0.0 {
        return None;
    }
    let disc = b * b - 4.0 * a * c;
    if !disc.is_finite() || disc < 0.0 {
        return None;
    }
    let sqrt_disc = disc.sqrt();
    let t = [(-b - sqrt_disc) / (2.0 * a), (-b + sqrt_disc) / (2.0 * a)]
        .into_iter()
        .filter(|value| value.is_finite() && *value >= 0.0 && *value <= 1.0)
        .min_by(|left, right| left.total_cmp(right))?;
    Some(add3(prev, scale3(sub3(next, prev), t)))
}

#[derive(Debug, Clone, Copy)]
struct ShellCrossing {
    crossed: bool,
    time_s: f64,
    distance_to_sc_km: f64,
    r_me_km: [f64; 3],
    v_me_km_s: [f64; 3],
    b_me_nt: [f64; 3],
    pitch_deg: f64,
}

impl Default for ShellCrossing {
    fn default() -> Self {
        Self {
            crossed: false,
            time_s: f64::NAN,
            distance_to_sc_km: f64::NAN,
            r_me_km: [f64::NAN; 3],
            v_me_km_s: [f64::NAN; 3],
            b_me_nt: [f64::NAN; 3],
            pitch_deg: f64::NAN,
        }
    }
}

impl ShellCrossing {
    fn from_state(
        step: usize,
        dt_s: f64,
        r_me_km: [f64; 3],
        v_me_km_s: [f64; 3],
        b_me_nt: [f64; 3],
        distance_to_sc_km: f64,
    ) -> Self {
        Self {
            crossed: true,
            time_s: step as f64 * dt_s,
            distance_to_sc_km,
            r_me_km,
            v_me_km_s,
            b_me_nt,
            pitch_deg: pitch_deg(v_me_km_s, b_me_nt),
        }
    }
}

#[allow(clippy::too_many_arguments)]
#[pyfunction]
pub(crate) fn trace_test_particles_shell_grid<'py>(
    py: Python<'py>,
    r0_me_km: PyReadonlyArray2<'py, f64>,
    v0_me_km_s: PyReadonlyArray2<'py, f64>,
    b_external_nt: PyReadonlyArray2<'py, f64>,
    return_center_me_km: Option<PyReadonlyArray2<'py, f64>>,
    longitude_deg: PyReadonlyArray1<'py, f64>,
    latitude_deg: PyReadonlyArray1<'py, f64>,
    altitude_km: PyReadonlyArray1<'py, f64>,
    field_me_nt: PyReadonlyArray4<'py, f64>,
    dt_s: f64,
    max_steps: usize,
    stop_alt_km: f64,
    escape_alt_km: f64,
    return_radius_km: f64,
    min_return_steps: usize,
    svm_scale: f64,
    bounds: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let r0 = rows3(&r0_me_km, "r0_me_km")?;
    let v0 = rows3(&v0_me_km_s, "v0_me_km_s")?;
    let b_external = rows3(&b_external_nt, "b_external_nT")?;
    if v0.len() != r0.len() || b_external.len() != r0.len() {
        return Err(PyValueError::new_err(
            "v0_me_km_s and b_external_nT must match r0_me_km rows",
        ));
    }
    let center = match &return_center_me_km {
        Some(values) => Some(rows3(values, "return_center_me_km")?),
        None => None,
    };
    let longitude = longitude_deg.as_slice()?.to_vec();
    let latitude = latitude_deg.as_slice()?.to_vec();
    let altitude = altitude_km.as_slice()?.to_vec();
    let expected_shape = [altitude.len(), latitude.len(), longitude.len(), 3];
    if field_me_nt.shape() != expected_shape {
        return Err(PyValueError::new_err(format!(
            "field_me_nT shape must be {expected_shape:?}, got {:?}",
            field_me_nt.shape()
        )));
    }
    let field: Vec<f64> = field_me_nt.as_array().iter().copied().collect();
    let settings = TraceSettings {
        dt_s,
        max_steps,
        stop_alt_km,
        escape_alt_km,
        return_radius_km,
        min_return_steps,
        svm_scale,
        bounds: GridBounds::parse(bounds).map_err(PyValueError::new_err)?,
    };
    let traces = py
        .detach(move || {
            let grid = ShellGrid::new(longitude, latitude, altitude, field)?;
            simulate_batch(&grid, &r0, &v0, &b_external, center.as_deref(), settings)
        })
        .map_err(PyValueError::new_err)?;
    traces_to_python(py, traces)
}

fn rows3(values: &PyReadonlyArray2<'_, f64>, name: &str) -> PyResult<Vec<[f64; 3]>> {
    let view = values.as_array();
    if view.ndim() != 2 || view.shape().get(1) != Some(&3) {
        return Err(PyValueError::new_err(format!(
            "{name} must have shape (rows, 3)"
        )));
    }
    Ok(view
        .outer_iter()
        .map(|row| [row[0], row[1], row[2]])
        .collect())
}

fn traces_to_python<'py>(
    py: Python<'py>,
    traces: Vec<TestParticleTrace>,
) -> PyResult<Bound<'py, PyDict>> {
    let output = PyDict::new(py);
    let status: Vec<i32> = traces.iter().map(|t| t.status_code).collect();
    let steps: Vec<u32> = traces.iter().map(|t| t.steps).collect();
    let crossed: Vec<u8> = traces
        .iter()
        .map(|t| u8::from(t.spacecraft_shell_crossed))
        .collect();
    output.set_item("status_code", status.into_pyarray(py))?;
    output.set_item("steps", steps.into_pyarray(py))?;
    output.set_item("spacecraft_shell_crossed", crossed.into_pyarray(py))?;
    set_scalar(py, &output, "flight_time_s", &traces, |t| t.flight_time_s)?;
    set_scalar(py, &output, "path_km", &traces, |t| t.path_km)?;
    set_scalar(py, &output, "closest_sc_distance_km", &traces, |t| {
        t.closest_sc_distance_km
    })?;
    set_scalar(py, &output, "min_alt_km", &traces, |t| t.min_alt_km)?;
    set_scalar(py, &output, "max_alt_km", &traces, |t| t.max_alt_km)?;
    set_scalar(py, &output, "spacecraft_shell_cross_time_s", &traces, |t| {
        t.spacecraft_shell_cross_time_s
    })?;
    set_scalar(
        py,
        &output,
        "spacecraft_shell_distance_to_sc_km",
        &traces,
        |t| t.spacecraft_shell_distance_to_sc_km,
    )?;
    set_scalar(py, &output, "spacecraft_shell_pitch_deg", &traces, |t| {
        t.spacecraft_shell_pitch_deg
    })?;
    set_scalar(py, &output, "final_pitch_deg", &traces, |t| {
        t.final_pitch_deg
    })?;
    set_vector(py, &output, "spacecraft_shell_r_me_km", &traces, |t| {
        t.spacecraft_shell_r_me_km
    })?;
    set_vector(py, &output, "spacecraft_shell_v_me_km_s", &traces, |t| {
        t.spacecraft_shell_v_me_km_s
    })?;
    set_vector(py, &output, "spacecraft_shell_b_me_nT", &traces, |t| {
        t.spacecraft_shell_b_me_nt
    })?;
    set_vector(py, &output, "final_r_me_km", &traces, |t| t.final_r_me_km)?;
    set_vector(py, &output, "final_v_me_km_s", &traces, |t| {
        t.final_v_me_km_s
    })?;
    set_vector(py, &output, "final_b_me_nT", &traces, |t| t.final_b_me_nt)?;
    Ok(output)
}

fn set_scalar<'py, F>(
    py: Python<'py>,
    output: &Bound<'py, PyDict>,
    name: &str,
    traces: &[TestParticleTrace],
    value: F,
) -> PyResult<()>
where
    F: Fn(&TestParticleTrace) -> f64,
{
    let values: Vec<f64> = traces.iter().map(value).collect();
    output.set_item(name, values.into_pyarray(py))
}

fn set_vector<'py, F>(
    py: Python<'py>,
    output: &Bound<'py, PyDict>,
    name: &str,
    traces: &[TestParticleTrace],
    value: F,
) -> PyResult<()>
where
    F: Fn(&TestParticleTrace) -> [f64; 3],
{
    let mut flat = Vec::with_capacity(traces.len() * 3);
    for trace in traces {
        flat.extend_from_slice(&value(trace));
    }
    let array = ndarray::Array2::from_shape_vec((traces.len(), 3), flat)
        .map_err(|error| PyValueError::new_err(error.to_string()))?;
    output.set_item(name, array.into_pyarray(py))
}

#[inline]
fn finite3(value: [f64; 3]) -> bool {
    value.iter().all(|item| item.is_finite())
}

#[inline]
fn add3(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}

#[inline]
fn sub3(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

#[inline]
fn scale3(a: [f64; 3], factor: f64) -> [f64; 3] {
    [a[0] * factor, a[1] * factor, a[2] * factor]
}

#[inline]
fn cross3(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}

#[inline]
fn dot3(a: [f64; 3], b: [f64; 3]) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

#[inline]
fn norm3(v: [f64; 3]) -> f64 {
    dot3(v, v).sqrt()
}

#[inline]
fn distance3(a: [f64; 3], b: [f64; 3]) -> f64 {
    norm3(sub3(a, b))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn zero_shell_grid() -> ShellGrid {
        let lon = vec![0.0, 180.0];
        let lat = vec![-90.0, 90.0];
        let alt = vec![0.0, 1000.0];
        let field = vec![0.0; lon.len() * lat.len() * alt.len() * 3];
        ShellGrid::new(lon, lat, alt, field).unwrap()
    }

    fn settings(
        dt_s: f64,
        max_steps: usize,
        stop: f64,
        radius: f64,
        min_steps: usize,
    ) -> TraceSettings {
        TraceSettings {
            dt_s,
            max_steps,
            stop_alt_km: stop,
            escape_alt_km: 5000.0,
            return_radius_km: radius,
            min_return_steps: min_steps,
            svm_scale: 0.0,
            bounds: GridBounds::Clamp,
        }
    }

    #[test]
    fn uniform_field_returns_particle_to_the_spacecraft_ring() {
        let grid = zero_shell_grid();
        let b_z = 10.0;
        let omega = ELECTRON_Q_OVER_M_C_PER_KG.abs() * 1.0e-9 * b_z;
        let period = 2.0 * std::f64::consts::PI / omega;
        let traces = simulate_batch(
            &grid,
            &[[MOON_RADIUS_KM + 100.0, 0.0, 0.0]],
            &[[1000.0, 0.0, 0.0]],
            &[[0.0, 0.0, b_z]],
            None,
            settings(period / 120.0, 300, 1.0, 0.75, 20),
        )
        .unwrap();
        assert_eq!(traces[0].status_code, STATUS_RETURNED);
        assert!(traces[0].closest_sc_distance_km < 0.75);
    }

    #[test]
    fn straight_line_hits_the_surface_without_field() {
        let grid = zero_shell_grid();
        let traces = simulate_batch(
            &grid,
            &[[MOON_RADIUS_KM + 30.0, 0.0, 0.0]],
            &[[-2.0, 0.0, 0.0]],
            &[[0.0, 0.0, 0.0]],
            None,
            settings(1.0, 50, 5.0, 5.0, 10),
        )
        .unwrap();
        assert_eq!(traces[0].status_code, STATUS_SURFACE_HIT);
        assert!(traces[0].min_alt_km <= 5.0);
    }

    #[test]
    fn boris_rotation_preserves_speed() {
        let v = [100.0, 20.0, -5.0];
        let rotated = boris_rotate(v, [3.0, -4.0, 12.0], 1.0e-6);
        assert!((norm3(rotated) - norm3(v)).abs() < 1.0e-9);
    }
}
