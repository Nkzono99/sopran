//! de Hoffmann-Teller frame helpers for look-vector level pitch-angle work.
//!
//! These kernels sit below pitch-angle binning: they build the tangential
//! de Hoffmann-Teller velocity of a planar boundary and shift per-look electron
//! velocities into a supplied frame velocity before pitch and energy are
//! recomputed. Python owns the ephemeris, OMNI conventions and binning.

use numpy::{IntoPyArray, PyReadonlyArray2, PyUntypedArrayMethods};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

const RAD_TO_DEG: f64 = 180.0 / std::f64::consts::PI;
/// ``sqrt(2 e / m_e)`` in km/s per sqrt(eV).
pub(crate) const ELECTRON_SPEED_KM_S_PER_SQRT_EV: f64 = 593.096_782_217_350_9;

#[derive(Clone, Copy, Debug)]
pub(crate) struct DhtResult {
    pub(crate) velocity: [f64; 3],
    pub(crate) ok: bool,
    pub(crate) b_normal_fraction: f64,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct LookShiftResult {
    pub(crate) pitch_deg: f64,
    pub(crate) energy_ev: f64,
    pub(crate) ok: bool,
}

/// Tangential de Hoffmann-Teller velocity ``u - B (u.n)/(B.n)`` for a planar
/// boundary with normal ``n``. All vectors share one frame.
pub(crate) fn dht_tangential_velocity(
    plasma_velocity: [f64; 3],
    magnetic_field: [f64; 3],
    normal: [f64; 3],
    min_abs_b_normal_fraction: f64,
) -> DhtResult {
    let b_norm = norm(magnetic_field);
    let n_norm = norm(normal);
    if !finite3(plasma_velocity) || !finite3(magnetic_field) || !finite3(normal) {
        return bad_dht();
    }
    if b_norm <= 0.0 || n_norm <= 0.0 {
        return bad_dht();
    }
    let n_hat = scale(normal, 1.0 / n_norm);
    let b_normal = dot(magnetic_field, n_hat);
    let b_normal_fraction = b_normal.abs() / b_norm;
    if b_normal_fraction < min_abs_b_normal_fraction.max(0.0) {
        return DhtResult {
            velocity: [f64::NAN; 3],
            ok: false,
            b_normal_fraction,
        };
    }
    let u_normal = dot(plasma_velocity, n_hat);
    let velocity = sub(plasma_velocity, scale(magnetic_field, u_normal / b_normal));
    DhtResult {
        velocity,
        ok: finite3(velocity),
        b_normal_fraction,
    }
}

/// Shift one look direction (polar ``theta``, azimuth ``phi``, degrees) of an
/// electron with ``energy_ev`` into the frame moving at ``frame_velocity``.
/// ``look_sign`` is ``+1`` when the look vector is the particle velocity
/// direction and ``-1`` when it is the viewing direction.
pub(crate) fn shift_look_velocity(
    energy_ev: f64,
    theta_deg: f64,
    phi_deg: f64,
    magnetic_field: [f64; 3],
    frame_velocity: [f64; 3],
    look_sign: f64,
) -> LookShiftResult {
    if !energy_ev.is_finite()
        || energy_ev <= 0.0
        || !theta_deg.is_finite()
        || !phi_deg.is_finite()
        || !finite3(magnetic_field)
        || !finite3(frame_velocity)
    {
        return bad_look_shift();
    }
    let b_norm = norm(magnetic_field);
    if b_norm <= 0.0 {
        return bad_look_shift();
    }
    let look = look_unit(theta_deg, phi_deg);
    let particle_speed = ELECTRON_SPEED_KM_S_PER_SQRT_EV * energy_ev.sqrt();
    let sign = if look_sign.is_sign_negative() {
        -1.0
    } else {
        1.0
    };
    let velocity = scale(look, sign * particle_speed);
    let shifted = sub(velocity, frame_velocity);
    let shifted_speed = norm(shifted);
    if shifted_speed <= 0.0 || !shifted_speed.is_finite() {
        return bad_look_shift();
    }
    let b_hat = scale(magnetic_field, 1.0 / b_norm);
    let shifted_hat = scale(shifted, 1.0 / shifted_speed);
    let cos_pitch = dot(shifted_hat, b_hat).clamp(-1.0, 1.0);
    let pitch_deg = cos_pitch.acos() * RAD_TO_DEG;
    let energy_ev = (shifted_speed / ELECTRON_SPEED_KM_S_PER_SQRT_EV).powi(2);
    LookShiftResult {
        pitch_deg,
        energy_ev,
        ok: pitch_deg.is_finite() && energy_ev.is_finite() && energy_ev > 0.0,
    }
}

#[pyfunction]
pub(crate) fn dht_tangential_velocity_batch<'py>(
    py: Python<'py>,
    plasma_velocity_km_s: PyReadonlyArray2<'py, f64>,
    magnetic_field: PyReadonlyArray2<'py, f64>,
    normal: PyReadonlyArray2<'py, f64>,
    min_abs_b_normal_fraction: f64,
) -> PyResult<Bound<'py, PyDict>> {
    let plasma = plasma_velocity_km_s.as_array();
    let magnetic = magnetic_field.as_array();
    let normals = normal.as_array();
    if plasma.ndim() != 2 || plasma.shape().get(1) != Some(&3) {
        return Err(PyValueError::new_err(
            "plasma_velocity_km_s must have shape (rows, 3)",
        ));
    }
    if magnetic.shape() != plasma.shape() || normals.shape() != plasma.shape() {
        return Err(PyValueError::new_err(
            "magnetic_field and normal must match plasma_velocity_km_s shape",
        ));
    }
    if !min_abs_b_normal_fraction.is_finite() {
        return Err(PyValueError::new_err(
            "min_abs_b_normal_fraction must be finite",
        ));
    }
    let rows = plasma.shape()[0];
    let mut velocity = Vec::with_capacity(rows * 3);
    let mut ok = Vec::with_capacity(rows);
    let mut fraction = Vec::with_capacity(rows);
    for row in 0..rows {
        let result = dht_tangential_velocity(
            [plasma[[row, 0]], plasma[[row, 1]], plasma[[row, 2]]],
            [magnetic[[row, 0]], magnetic[[row, 1]], magnetic[[row, 2]]],
            [normals[[row, 0]], normals[[row, 1]], normals[[row, 2]]],
            min_abs_b_normal_fraction,
        );
        velocity.extend_from_slice(&result.velocity);
        ok.push(u8::from(result.ok));
        fraction.push(result.b_normal_fraction);
    }
    let output = PyDict::new(py);
    let velocity = ndarray::Array2::from_shape_vec((rows, 3), velocity)
        .map_err(|error| PyValueError::new_err(error.to_string()))?;
    output.set_item("velocity_km_s", velocity.into_pyarray(py))?;
    output.set_item("ok", ok.into_pyarray(py))?;
    output.set_item("b_normal_fraction", fraction.into_pyarray(py))?;
    Ok(output)
}

#[pyfunction]
pub(crate) fn shift_look_velocity_batch<'py>(
    py: Python<'py>,
    energy_ev: PyReadonlyArray2<'py, f64>,
    theta_deg: PyReadonlyArray2<'py, f64>,
    phi_deg: PyReadonlyArray2<'py, f64>,
    magnetic_field: PyReadonlyArray2<'py, f64>,
    frame_velocity_km_s: PyReadonlyArray2<'py, f64>,
    look_sign: f64,
) -> PyResult<Bound<'py, PyDict>> {
    let energy = energy_ev.as_array();
    let theta = theta_deg.as_array();
    let phi = phi_deg.as_array();
    let magnetic = magnetic_field.as_array();
    let frame = frame_velocity_km_s.as_array();
    if energy.ndim() != 2 || theta.shape() != energy.shape() || phi.shape() != energy.shape() {
        return Err(PyValueError::new_err(
            "energy_ev, theta_deg and phi_deg must share one (rows, looks) shape",
        ));
    }
    let rows = energy.shape()[0];
    let cols = energy.shape()[1];
    if magnetic.shape() != [rows, 3] || frame.shape() != [rows, 3] {
        return Err(PyValueError::new_err(
            "magnetic_field and frame_velocity_km_s must have shape (rows, 3)",
        ));
    }
    if !look_sign.is_finite() || look_sign == 0.0 {
        return Err(PyValueError::new_err("look_sign must be +1 or -1"));
    }
    let mut pitch = Vec::with_capacity(rows * cols);
    let mut shifted_energy = Vec::with_capacity(rows * cols);
    let mut ok = Vec::with_capacity(rows * cols);
    for row in 0..rows {
        let b = [magnetic[[row, 0]], magnetic[[row, 1]], magnetic[[row, 2]]];
        let v = [frame[[row, 0]], frame[[row, 1]], frame[[row, 2]]];
        for col in 0..cols {
            let result = shift_look_velocity(
                energy[[row, col]],
                theta[[row, col]],
                phi[[row, col]],
                b,
                v,
                look_sign,
            );
            pitch.push(result.pitch_deg);
            shifted_energy.push(result.energy_ev);
            ok.push(u8::from(result.ok));
        }
    }
    let output = PyDict::new(py);
    let to_matrix = |values: Vec<f64>| {
        ndarray::Array2::from_shape_vec((rows, cols), values)
            .map_err(|error| PyValueError::new_err(error.to_string()))
    };
    output.set_item("pitch_deg", to_matrix(pitch)?.into_pyarray(py))?;
    output.set_item("energy_eV", to_matrix(shifted_energy)?.into_pyarray(py))?;
    let ok = ndarray::Array2::from_shape_vec((rows, cols), ok)
        .map_err(|error| PyValueError::new_err(error.to_string()))?;
    output.set_item("ok", ok.into_pyarray(py))?;
    Ok(output)
}

fn look_unit(theta_deg: f64, phi_deg: f64) -> [f64; 3] {
    let theta = theta_deg.to_radians();
    let phi = phi_deg.to_radians();
    [
        phi.cos() * theta.cos(),
        phi.sin() * theta.cos(),
        theta.sin(),
    ]
}

fn bad_dht() -> DhtResult {
    DhtResult {
        velocity: [f64::NAN; 3],
        ok: false,
        b_normal_fraction: f64::NAN,
    }
}

fn bad_look_shift() -> LookShiftResult {
    LookShiftResult {
        pitch_deg: f64::NAN,
        energy_ev: f64::NAN,
        ok: false,
    }
}

fn finite3(value: [f64; 3]) -> bool {
    value.iter().all(|item| item.is_finite())
}

fn norm(value: [f64; 3]) -> f64 {
    dot(value, value).sqrt()
}

fn dot(left: [f64; 3], right: [f64; 3]) -> f64 {
    left[0] * right[0] + left[1] * right[1] + left[2] * right[2]
}

fn scale(value: [f64; 3], factor: f64) -> [f64; 3] {
    [value[0] * factor, value[1] * factor, value[2] * factor]
}

fn sub(left: [f64; 3], right: [f64; 3]) -> [f64; 3] {
    [left[0] - right[0], left[1] - right[1], left[2] - right[2]]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dht_velocity_is_tangential() {
        let result = dht_tangential_velocity(
            [400.0, 10.0, -5.0],
            [20.0, 4.0, 10.0],
            [0.0, 0.0, 1.0],
            0.01,
        );
        assert!(result.ok);
        assert!(result.velocity[2].abs() < 1.0e-9);
    }

    #[test]
    fn dht_rejects_tangent_field() {
        let result =
            dht_tangential_velocity([400.0, 0.0, 0.0], [1.0, 0.0, 0.001], [0.0, 0.0, 1.0], 0.15);
        assert!(!result.ok);
        assert!(result.b_normal_fraction < 0.15);
    }

    #[test]
    fn zero_frame_keeps_pitch_and_energy() {
        let result = shift_look_velocity(100.0, 0.0, 0.0, [1.0, 0.0, 0.0], [0.0, 0.0, 0.0], 1.0);
        assert!(result.ok);
        assert!(result.pitch_deg.abs() < 1.0e-9);
        assert!((result.energy_ev - 100.0).abs() < 1.0e-9);
    }

    #[test]
    fn opposing_frame_raises_energy() {
        let speed = ELECTRON_SPEED_KM_S_PER_SQRT_EV * 100.0_f64.sqrt();
        let result = shift_look_velocity(
            100.0,
            0.0,
            0.0,
            [1.0, 0.0, 0.0],
            [-0.1 * speed, 0.0, 0.0],
            1.0,
        );
        assert!(result.ok);
        assert!((result.energy_ev - 121.0).abs() < 1.0e-6);
    }
}
