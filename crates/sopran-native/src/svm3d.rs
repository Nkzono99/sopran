use ndarray::Array2;
use numpy::{
    IntoPyArray, PyReadonlyArray1, PyReadonlyArray2, PyReadonlyArray4, PyUntypedArrayMethods,
};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use rayon::prelude::*;
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};

const MOON_RADIUS_KM: f64 = 1737.4;
const SVM_STEP_DEG: f64 = 0.2;

#[derive(Debug)]
struct DirectSources {
    positions: Vec<[f64; 3]>,
    weights: Vec<f64>,
    longitude_count: usize,
    latitude_count: usize,
    longitude_min_deg: f64,
    latitude_min_deg: f64,
}

impl DirectSources {
    fn load(path: &Path) -> Result<Self, std::io::Error> {
        let reader = BufReader::new(File::open(path)?);
        let mut rows = Vec::new();
        let mut longitude_min_deg = f64::INFINITY;
        let mut longitude_max_deg = f64::NEG_INFINITY;
        let mut latitude_min_deg = f64::INFINITY;
        let mut latitude_max_deg = f64::NEG_INFINITY;
        let cell_area = SVM_STEP_DEG.to_radians().powi(2);

        for line in reader.lines() {
            let line = line?;
            let values: Vec<f64> = line
                .split_whitespace()
                .filter_map(|part| part.parse::<f64>().ok())
                .collect();
            if values.len() < 5 {
                continue;
            }
            let lon_deg = values[0];
            let lat_deg = values[1];
            let radial_nt = values[4];
            rows.push((lon_deg, lat_deg, radial_nt));
            longitude_min_deg = longitude_min_deg.min(lon_deg);
            longitude_max_deg = longitude_max_deg.max(lon_deg);
            latitude_min_deg = latitude_min_deg.min(lat_deg);
            latitude_max_deg = latitude_max_deg.max(lat_deg);
        }
        let longitude_count = grid_count(longitude_min_deg, longitude_max_deg)?;
        let latitude_count = grid_count(latitude_min_deg, latitude_max_deg)?;
        let mut positions = vec![[f64::NAN; 3]; longitude_count * latitude_count];
        let mut weights = vec![f64::NAN; longitude_count * latitude_count];
        for (lon_deg, lat_deg, radial_nt) in rows {
            let lon_index = (((lon_deg - longitude_min_deg) / SVM_STEP_DEG).round() as isize)
                .rem_euclid(longitude_count as isize) as usize;
            let lat_index = ((lat_deg - latitude_min_deg) / SVM_STEP_DEG).round() as isize;
            if !(0..latitude_count as isize).contains(&lat_index) {
                continue;
            }
            let index = lon_index * latitude_count + lat_index as usize;
            let lon = lon_deg.to_radians();
            let lat = lat_deg.to_radians();
            positions[index] = [lon.cos() * lat.cos(), lon.sin() * lat.cos(), lat.sin()];
            weights[index] = radial_nt * lat.cos() * cell_area / (2.0 * std::f64::consts::PI);
        }
        Ok(Self {
            positions,
            weights,
            longitude_count,
            latitude_count,
            longitude_min_deg,
            latitude_min_deg,
        })
    }

    fn field_at(&self, position_km: [f64; 3], min_altitude_km: f64) -> Option<[f64; 3]> {
        let radius_km = norm(position_km);
        let altitude_km = radius_km - MOON_RADIUS_KM;
        if !radius_km.is_finite() || altitude_km < min_altitude_km || altitude_km <= 0.0 {
            return None;
        }
        let position = scale(position_km, 1.0 / MOON_RADIUS_KM);
        let position_norm = norm(position);
        let threshold = 10.0 * altitude_km / MOON_RADIUS_KM;
        let angular_radius = if threshold >= 2.0 {
            std::f64::consts::PI
        } else {
            2.0 * (0.5 * threshold).asin()
        };
        let lon0 = position[1]
            .atan2(position[0])
            .rem_euclid(2.0 * std::f64::consts::PI)
            .to_degrees();
        let lat0 = position[2]
            .atan2((position[0] * position[0] + position[1] * position[1]).sqrt())
            .to_degrees();
        let radius_deg = angular_radius.to_degrees();
        let lat_min = (((lat0 - radius_deg).max(self.latitude_min_deg) - self.latitude_min_deg)
            / SVM_STEP_DEG)
            .floor() as isize;
        let latitude_max_deg =
            self.latitude_min_deg + (self.latitude_count - 1) as f64 * SVM_STEP_DEG;
        let lat_max = (((lat0 + radius_deg).min(latitude_max_deg) - self.latitude_min_deg)
            / SVM_STEP_DEG)
            .ceil() as isize;
        let mut output = [0.0; 3];
        let mut used = 0_usize;

        for lat_index in lat_min.max(0)..=lat_max.min(self.latitude_count as isize - 1) {
            let source_lat_deg = self.latitude_min_deg + lat_index as f64 * SVM_STEP_DEG;
            let lon_width =
                spherical_cap_longitude_width_deg(lat0, source_lat_deg, radius_deg + SVM_STEP_DEG);
            if lon_width >= 180.0 {
                for lon_index in 0..self.longitude_count {
                    self.accumulate(
                        position,
                        position_norm,
                        threshold,
                        lon_index,
                        lat_index as usize,
                        &mut output,
                        &mut used,
                    );
                }
            } else {
                let lon_start =
                    ((lon0 - lon_width - self.longitude_min_deg) / SVM_STEP_DEG).floor() as isize;
                let lon_stop =
                    ((lon0 + lon_width - self.longitude_min_deg) / SVM_STEP_DEG).ceil() as isize;
                for raw_lon in lon_start..=lon_stop {
                    self.accumulate(
                        position,
                        position_norm,
                        threshold,
                        raw_lon.rem_euclid(self.longitude_count as isize) as usize,
                        lat_index as usize,
                        &mut output,
                        &mut used,
                    );
                }
            }
        }
        (used > 0 && output.iter().all(|value| value.is_finite())).then_some(output)
    }

    #[allow(clippy::too_many_arguments)]
    fn accumulate(
        &self,
        position: [f64; 3],
        position_norm: f64,
        threshold: f64,
        lon_index: usize,
        lat_index: usize,
        output: &mut [f64; 3],
        used: &mut usize,
    ) {
        let index = lon_index * self.latitude_count + lat_index;
        let source = self.positions[index];
        let weight = self.weights[index];
        if !source[0].is_finite() || !weight.is_finite() {
            return;
        }
        let difference = subtract(position, source);
        let distance = norm(difference);
        if !distance.is_finite() || distance <= 0.0 || distance >= threshold {
            return;
        }
        let denominator = (position_norm + distance + 1.0) * (position_norm + distance - 1.0);
        if denominator.abs() <= 1.0e-15 {
            return;
        }
        for axis in 0..3 {
            let gradient = difference[axis] / distance.powi(3)
                - (position[axis] / position_norm + difference[axis] / distance) / denominator;
            output[axis] += gradient * weight;
        }
        *used += 1;
    }
}

fn grid_count(minimum: f64, maximum: f64) -> Result<usize, std::io::Error> {
    if !minimum.is_finite() || !maximum.is_finite() || maximum < minimum {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "SVM source contains no regular numeric grid",
        ));
    }
    Ok(((maximum - minimum) / SVM_STEP_DEG).round() as usize + 1)
}

fn spherical_cap_longitude_width_deg(
    center_latitude_deg: f64,
    source_latitude_deg: f64,
    angular_radius_deg: f64,
) -> f64 {
    if angular_radius_deg >= 180.0 {
        return 180.0;
    }
    let center = center_latitude_deg.to_radians();
    let source = source_latitude_deg.to_radians();
    let denominator = center.cos() * source.cos();
    if denominator.abs() < 1.0e-12 {
        return 180.0;
    }
    let cosine_width =
        (angular_radius_deg.to_radians().cos() - center.sin() * source.sin()) / denominator;
    if cosine_width <= -1.0 {
        180.0
    } else if cosine_width >= 1.0 {
        0.0
    } else {
        cosine_width.acos().to_degrees()
    }
}

fn direct_cache() -> &'static Mutex<HashMap<PathBuf, Arc<DirectSources>>> {
    static CACHE: OnceLock<Mutex<HashMap<PathBuf, Arc<DirectSources>>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

fn load_direct_sources(path: &Path) -> Result<Arc<DirectSources>, std::io::Error> {
    if let Ok(cache) = direct_cache().lock() {
        if let Some(source) = cache.get(path) {
            return Ok(Arc::clone(source));
        }
    }
    let source = Arc::new(DirectSources::load(path)?);
    if let Ok(mut cache) = direct_cache().lock() {
        cache.insert(path.to_path_buf(), Arc::clone(&source));
    }
    Ok(source)
}

#[pyfunction]
pub(crate) fn evaluate_tsunakawa_svm3d<'py>(
    py: Python<'py>,
    path: String,
    positions_km: PyReadonlyArray2<'py, f64>,
    min_altitude_km: f64,
) -> PyResult<Bound<'py, numpy::PyArray2<f64>>> {
    let positions = positions_km.as_array();
    if positions.shape().get(1) != Some(&3) {
        return Err(PyValueError::new_err(
            "positions_km must have shape (rows, 3)",
        ));
    }
    if !min_altitude_km.is_finite() || min_altitude_km < 0.0 {
        return Err(PyValueError::new_err(
            "min_altitude_km must be finite and non-negative",
        ));
    }
    let rows = positions.shape()[0];
    let values: Vec<[f64; 3]> = positions
        .outer_iter()
        .map(|row| [row[0], row[1], row[2]])
        .collect();
    let result = py
        .detach(move || {
            let sources = load_direct_sources(Path::new(&path))?;
            Ok::<Vec<[f64; 3]>, std::io::Error>(
                values
                    .into_par_iter()
                    .map(|position| {
                        sources
                            .field_at(position, min_altitude_km)
                            .unwrap_or([f64::NAN; 3])
                    })
                    .collect(),
            )
        })
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    let flat = result.into_iter().flatten().collect();
    let array = Array2::from_shape_vec((rows, 3), flat)
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    Ok(array.into_pyarray(py))
}

#[derive(Debug, Clone)]
struct ShellGrid {
    longitude_deg: Vec<f64>,
    latitude_deg: Vec<f64>,
    altitude_km: Vec<f64>,
    field_nt: Vec<f64>,
    longitude_step_deg: f64,
}

impl ShellGrid {
    fn new(
        longitude_deg: Vec<f64>,
        latitude_deg: Vec<f64>,
        altitude_km: Vec<f64>,
        field_nt: Vec<f64>,
    ) -> Result<Self, String> {
        if longitude_deg.len() < 2 || latitude_deg.len() < 2 || altitude_km.len() < 2 {
            return Err("shell coordinates must each contain at least two values".to_string());
        }
        let expected = longitude_deg.len() * latitude_deg.len() * altitude_km.len() * 3;
        if field_nt.len() != expected {
            return Err(format!(
                "field_me_nT contains {} values, expected {expected}",
                field_nt.len()
            ));
        }
        validate_increasing(&longitude_deg, "longitude_deg")?;
        validate_increasing(&latitude_deg, "latitude_deg")?;
        validate_increasing(&altitude_km, "altitude_km")?;
        let longitude_step_deg = longitude_deg[1] - longitude_deg[0];
        let latitude_step_deg = latitude_deg[1] - latitude_deg[0];
        validate_uniform(&longitude_deg, longitude_step_deg, "longitude_deg")?;
        validate_uniform(&latitude_deg, latitude_step_deg, "latitude_deg")?;
        Ok(Self {
            longitude_deg,
            latitude_deg,
            altitude_km,
            field_nt,
            longitude_step_deg,
        })
    }

    fn field_at(&self, position_km: [f64; 3], clamp_below_grid: bool) -> Option<[f64; 3]> {
        let radius = norm(position_km);
        if !radius.is_finite() || radius <= 0.0 {
            return None;
        }
        let longitude = position_km[1].atan2(position_km[0]).to_degrees();
        let latitude = (position_km[2] / radius)
            .clamp(-1.0, 1.0)
            .asin()
            .to_degrees();
        let mut altitude = radius - MOON_RADIUS_KM;
        if clamp_below_grid && altitude < self.altitude_km[0] {
            altitude = self.altitude_km[0];
        }
        self.interpolate(longitude, latitude, altitude)
    }

    fn interpolate(&self, longitude: f64, latitude: f64, altitude: f64) -> Option<[f64; 3]> {
        if !longitude.is_finite() || !latitude.is_finite() || !altitude.is_finite() {
            return None;
        }
        let (lat0, lat1, latitude_fraction) = bracket(&self.latitude_deg, latitude)?;
        let (alt0, alt1, altitude_fraction) = bracket(&self.altitude_km, altitude)?;
        let period = self.longitude_step_deg * self.longitude_deg.len() as f64;
        let longitude_position =
            (longitude - self.longitude_deg[0]).rem_euclid(period) / self.longitude_step_deg;
        let lon0 = longitude_position.floor() as usize % self.longitude_deg.len();
        let lon1 = (lon0 + 1) % self.longitude_deg.len();
        let longitude_fraction = longitude_position - longitude_position.floor();
        let mut output = [0.0; 3];
        for axis in 0..3 {
            let c000 = self.value(alt0, lat0, lon0, axis);
            let c001 = self.value(alt0, lat0, lon1, axis);
            let c010 = self.value(alt0, lat1, lon0, axis);
            let c011 = self.value(alt0, lat1, lon1, axis);
            let c100 = self.value(alt1, lat0, lon0, axis);
            let c101 = self.value(alt1, lat0, lon1, axis);
            let c110 = self.value(alt1, lat1, lon0, axis);
            let c111 = self.value(alt1, lat1, lon1, axis);
            let c00 = lerp(c000, c001, longitude_fraction);
            let c01 = lerp(c010, c011, longitude_fraction);
            let c10 = lerp(c100, c101, longitude_fraction);
            let c11 = lerp(c110, c111, longitude_fraction);
            output[axis] = lerp(
                lerp(c00, c01, latitude_fraction),
                lerp(c10, c11, latitude_fraction),
                altitude_fraction,
            );
        }
        output
            .iter()
            .all(|value| value.is_finite())
            .then_some(output)
    }

    fn value(&self, altitude: usize, latitude: usize, longitude: usize, axis: usize) -> f64 {
        let index = (((altitude * self.latitude_deg.len() + latitude) * self.longitude_deg.len()
            + longitude)
            * 3)
            + axis;
        self.field_nt[index]
    }
}

fn validate_increasing(values: &[f64], name: &str) -> Result<(), String> {
    if values
        .windows(2)
        .any(|pair| !pair[0].is_finite() || pair[1] <= pair[0])
    {
        return Err(format!("{name} must be finite and strictly increasing"));
    }
    Ok(())
}

fn validate_uniform(values: &[f64], step: f64, name: &str) -> Result<(), String> {
    let tolerance = step.abs().max(1.0) * 1.0e-9;
    if values
        .windows(2)
        .any(|pair| ((pair[1] - pair[0]) - step).abs() > tolerance)
    {
        return Err(format!("{name} must be uniformly spaced"));
    }
    Ok(())
}

fn bracket(values: &[f64], value: f64) -> Option<(usize, usize, f64)> {
    if value < values[0] || value > values[values.len() - 1] {
        return None;
    }
    if value == values[values.len() - 1] {
        return Some((values.len() - 2, values.len() - 1, 1.0));
    }
    let upper = values.partition_point(|candidate| *candidate <= value);
    let lower = upper.saturating_sub(1).min(values.len() - 2);
    let upper = lower + 1;
    Some((
        lower,
        upper,
        (value - values[lower]) / (values[upper] - values[lower]),
    ))
}

#[derive(Debug, Clone, Copy)]
struct TraceResult {
    valid: bool,
    footpoint: [f64; 3],
    steps: u32,
    path_km: f64,
    fail_code: i16,
    svm_spacecraft: [f64; 3],
    maximum_svm_nt: f64,
    maximum_svm_position: [f64; 3],
    maximum_total_nt: f64,
    maximum_total_position: [f64; 3],
    target_crossed: bool,
    target_position: [f64; 3],
    target_path_km: f64,
    target_svm_nt: f64,
}

impl TraceResult {
    fn invalid(fail_code: i16, svm_spacecraft: [f64; 3]) -> Self {
        Self {
            valid: false,
            footpoint: [f64::NAN; 3],
            steps: 0,
            path_km: f64::NAN,
            fail_code,
            svm_spacecraft,
            maximum_svm_nt: f64::NAN,
            maximum_svm_position: [f64::NAN; 3],
            maximum_total_nt: f64::NAN,
            maximum_total_position: [f64::NAN; 3],
            target_crossed: false,
            target_position: [f64::NAN; 3],
            target_path_km: f64::NAN,
            target_svm_nt: f64::NAN,
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn trace_one(
    grid: &ShellGrid,
    start: [f64; 3],
    external_nt: [f64; 3],
    sign: i32,
    target_nt: f64,
    step_km: f64,
    max_steps: usize,
    stop_altitude_km: f64,
) -> TraceResult {
    let Some(svm_spacecraft) = grid.field_at(start, false) else {
        return TraceResult::invalid(2, [f64::NAN; 3]);
    };
    if sign != -1 && sign != 1
        || !start.iter().all(|value| value.is_finite())
        || !external_nt.iter().all(|value| value.is_finite())
    {
        return TraceResult::invalid(1, svm_spacecraft);
    }
    let stop_radius = MOON_RADIUS_KM + stop_altitude_km;
    let mut position = start;
    let Some((initial_svm, mut previous_total)) = fields(grid, position, external_nt) else {
        return TraceResult::invalid(2, svm_spacecraft);
    };
    let mut result = TraceResult::invalid(4, svm_spacecraft);
    result.maximum_svm_nt = norm(initial_svm);
    result.maximum_svm_position = position;
    result.maximum_total_nt = norm(previous_total);
    result.maximum_total_position = position;
    if target_nt.is_finite() && target_nt > 0.0 && result.maximum_total_nt >= target_nt {
        result.target_crossed = true;
        result.target_position = position;
        result.target_path_km = 0.0;
        result.target_svm_nt = result.maximum_svm_nt;
    }

    for step in 1..=max_steps {
        let previous_position = position;
        let Some(next) = rk4_step(grid, position, external_nt, sign, step_km) else {
            result.fail_code = 2;
            result.steps = (step - 1) as u32;
            return result;
        };
        let next_radius = norm(next);
        let (sample_position, segment_fraction, reached_surface) = if next_radius <= stop_radius {
            (
                surface_intersection(previous_position, next, stop_radius),
                surface_fraction(previous_position, next, stop_radius),
                true,
            )
        } else {
            (next, 1.0, false)
        };
        let Some((sample_svm, sample_total)) = fields_clamped(grid, sample_position, external_nt)
        else {
            result.fail_code = 2;
            result.steps = (step - 1) as u32;
            return result;
        };
        let sample_svm_norm = norm(sample_svm);
        let sample_total_norm = norm(sample_total);
        let path_at_sample = (step as f64 - 1.0 + segment_fraction) * step_km;
        if sample_svm_norm > result.maximum_svm_nt {
            result.maximum_svm_nt = sample_svm_norm;
            result.maximum_svm_position = sample_position;
        }
        if sample_total_norm > result.maximum_total_nt {
            result.maximum_total_nt = sample_total_norm;
            result.maximum_total_position = sample_position;
        }
        if !result.target_crossed
            && target_nt.is_finite()
            && target_nt > norm(previous_total)
            && sample_total_norm >= target_nt
        {
            let lower = norm(previous_total);
            let fraction = ((target_nt - lower) / (sample_total_norm - lower)).clamp(0.0, 1.0);
            let target_position = lerp3(previous_position, sample_position, fraction);
            result.target_crossed = true;
            result.target_position = target_position;
            result.target_path_km = (step as f64 - 1.0 + fraction * segment_fraction) * step_km;
            result.target_svm_nt = grid
                .field_at(target_position, true)
                .map(norm)
                .unwrap_or(f64::NAN);
        }
        previous_total = sample_total;
        if reached_surface {
            result.valid = true;
            result.footpoint = sample_position;
            result.steps = step as u32;
            result.path_km = path_at_sample;
            result.fail_code = 0;
            return result;
        }
        position = next;
        if next_radius - MOON_RADIUS_KM > grid.altitude_km[grid.altitude_km.len() - 1] {
            result.fail_code = 3;
            result.steps = step as u32;
            result.path_km = step as f64 * step_km;
            return result;
        }
    }
    result.steps = max_steps as u32;
    result.path_km = max_steps as f64 * step_km;
    result
}

fn fields(
    grid: &ShellGrid,
    position: [f64; 3],
    external_nt: [f64; 3],
) -> Option<([f64; 3], [f64; 3])> {
    let svm = grid.field_at(position, false)?;
    Some((svm, add(svm, external_nt)))
}

fn fields_clamped(
    grid: &ShellGrid,
    position: [f64; 3],
    external_nt: [f64; 3],
) -> Option<([f64; 3], [f64; 3])> {
    let svm = grid.field_at(position, true)?;
    Some((svm, add(svm, external_nt)))
}

fn unit_total_field(
    grid: &ShellGrid,
    position: [f64; 3],
    external_nt: [f64; 3],
    sign: i32,
) -> Option<[f64; 3]> {
    let (_, total) = fields_clamped(grid, position, external_nt)?;
    let magnitude = norm(total);
    (magnitude.is_finite() && magnitude > 0.0).then(|| scale(total, sign as f64 / magnitude))
}

fn rk4_step(
    grid: &ShellGrid,
    position: [f64; 3],
    external_nt: [f64; 3],
    sign: i32,
    step_km: f64,
) -> Option<[f64; 3]> {
    let k1 = unit_total_field(grid, position, external_nt, sign)?;
    let k2 = unit_total_field(
        grid,
        add(position, scale(k1, step_km * 0.5)),
        external_nt,
        sign,
    )?;
    let k3 = unit_total_field(
        grid,
        add(position, scale(k2, step_km * 0.5)),
        external_nt,
        sign,
    )?;
    let k4 = unit_total_field(grid, add(position, scale(k3, step_km)), external_nt, sign)?;
    Some(add(
        position,
        scale(
            add(add(k1, scale(k2, 2.0)), add(scale(k3, 2.0), k4)),
            step_km / 6.0,
        ),
    ))
}

fn surface_fraction(start: [f64; 3], stop: [f64; 3], radius: f64) -> f64 {
    let delta = subtract(stop, start);
    let a = dot(delta, delta);
    let b = 2.0 * dot(start, delta);
    let c = dot(start, start) - radius * radius;
    let discriminant = (b * b - 4.0 * a * c).max(0.0);
    ((-b - discriminant.sqrt()) / (2.0 * a)).clamp(0.0, 1.0)
}

fn surface_intersection(start: [f64; 3], stop: [f64; 3], radius: f64) -> [f64; 3] {
    lerp3(start, stop, surface_fraction(start, stop, radius))
}

#[allow(clippy::too_many_arguments)]
#[pyfunction]
pub(crate) fn trace_svm3d_shell_grid<'py>(
    py: Python<'py>,
    positions_km: PyReadonlyArray2<'py, f64>,
    external_field_nt: PyReadonlyArray2<'py, f64>,
    connection_sign: PyReadonlyArray1<'py, i32>,
    target_field_nt: PyReadonlyArray1<'py, f64>,
    longitude_deg: PyReadonlyArray1<'py, f64>,
    latitude_deg: PyReadonlyArray1<'py, f64>,
    altitude_km: PyReadonlyArray1<'py, f64>,
    field_me_nt: PyReadonlyArray4<'py, f64>,
    step_km: f64,
    max_steps: usize,
    stop_altitude_km: f64,
) -> PyResult<Bound<'py, PyDict>> {
    let positions_view = positions_km.as_array();
    let external_view = external_field_nt.as_array();
    if positions_view.ndim() != 2 || positions_view.shape().get(1) != Some(&3) {
        return Err(PyValueError::new_err(
            "positions_km must have shape (rows, 3)",
        ));
    }
    if external_view.shape() != positions_view.shape() {
        return Err(PyValueError::new_err(
            "external_field_nT must match positions_km shape",
        ));
    }
    let rows = positions_view.shape()[0];
    if connection_sign.len() != rows || target_field_nt.len() != rows {
        return Err(PyValueError::new_err(
            "connection_sign and target_field_nT must match positions_km rows",
        ));
    }
    if !step_km.is_finite()
        || step_km <= 0.0
        || max_steps == 0
        || !stop_altitude_km.is_finite()
        || stop_altitude_km < 0.0
    {
        return Err(PyValueError::new_err("invalid trace settings"));
    }
    let longitude = longitude_deg.as_slice()?.to_vec();
    let latitude = latitude_deg.as_slice()?.to_vec();
    let altitude = altitude_km.as_slice()?.to_vec();
    let field_shape = field_me_nt.shape();
    let expected_shape = [altitude.len(), latitude.len(), longitude.len(), 3];
    if field_shape != expected_shape {
        return Err(PyValueError::new_err(format!(
            "field_me_nT shape must be {expected_shape:?}, got {field_shape:?}"
        )));
    }
    let field = field_me_nt.as_array().iter().copied().collect();
    let positions: Vec<[f64; 3]> = positions_view
        .outer_iter()
        .map(|row| [row[0], row[1], row[2]])
        .collect();
    let external: Vec<[f64; 3]> = external_view
        .outer_iter()
        .map(|row| [row[0], row[1], row[2]])
        .collect();
    let signs = connection_sign.as_slice()?.to_vec();
    let targets = target_field_nt.as_slice()?.to_vec();
    let results = py
        .detach(move || {
            let grid = ShellGrid::new(longitude, latitude, altitude, field)?;
            Ok::<Vec<TraceResult>, String>(
                (0..rows)
                    .into_par_iter()
                    .map(|index| {
                        trace_one(
                            &grid,
                            positions[index],
                            external[index],
                            signs[index],
                            targets[index],
                            step_km,
                            max_steps,
                            stop_altitude_km,
                        )
                    })
                    .collect(),
            )
        })
        .map_err(PyValueError::new_err)?;
    trace_results_to_python(py, results)
}

fn trace_results_to_python<'py>(
    py: Python<'py>,
    results: Vec<TraceResult>,
) -> PyResult<Bound<'py, PyDict>> {
    let output = PyDict::new(py);
    let valid: Vec<u8> = results.iter().map(|row| u8::from(row.valid)).collect();
    let target_crossed: Vec<u8> = results
        .iter()
        .map(|row| u8::from(row.target_crossed))
        .collect();
    let steps: Vec<u32> = results.iter().map(|row| row.steps).collect();
    let fail_code: Vec<i16> = results.iter().map(|row| row.fail_code).collect();
    output.set_item("valid", valid.into_pyarray(py))?;
    output.set_item("steps", steps.into_pyarray(py))?;
    output.set_item("fail_code", fail_code.into_pyarray(py))?;
    output.set_item("target_crossed", target_crossed.into_pyarray(py))?;
    set_scalar(py, &output, "path_km", &results, |row| row.path_km)?;
    set_scalar(py, &output, "maximum_svm_nT", &results, |row| {
        row.maximum_svm_nt
    })?;
    set_scalar(py, &output, "maximum_total_nT", &results, |row| {
        row.maximum_total_nt
    })?;
    set_scalar(py, &output, "target_path_km", &results, |row| {
        row.target_path_km
    })?;
    set_scalar(py, &output, "target_svm_nT", &results, |row| {
        row.target_svm_nt
    })?;
    set_position(py, &output, "footpoint", &results, |row| row.footpoint)?;
    set_vector(py, &output, "svm_spacecraft", &results, |row| {
        row.svm_spacecraft
    })?;
    set_position(py, &output, "maximum_svm", &results, |row| {
        row.maximum_svm_position
    })?;
    set_position(py, &output, "maximum_total", &results, |row| {
        row.maximum_total_position
    })?;
    set_position(py, &output, "target", &results, |row| row.target_position)?;
    Ok(output)
}

fn set_scalar<'py, F>(
    py: Python<'py>,
    output: &Bound<'py, PyDict>,
    name: &str,
    results: &[TraceResult],
    value: F,
) -> PyResult<()>
where
    F: Fn(&TraceResult) -> f64,
{
    let values: Vec<f64> = results.iter().map(value).collect();
    output.set_item(name, values.into_pyarray(py))
}

fn set_position<'py, F>(
    py: Python<'py>,
    output: &Bound<'py, PyDict>,
    name: &str,
    results: &[TraceResult],
    value: F,
) -> PyResult<()>
where
    F: Fn(&TraceResult) -> [f64; 3],
{
    let mut lon = Vec::with_capacity(results.len());
    let mut lat = Vec::with_capacity(results.len());
    let mut alt = Vec::with_capacity(results.len());
    for result in results {
        let position = value(result);
        let converted = lon_lat_alt(position);
        lon.push(converted[0]);
        lat.push(converted[1]);
        alt.push(converted[2]);
    }
    output.set_item(format!("{name}_longitude_deg"), lon.into_pyarray(py))?;
    output.set_item(format!("{name}_latitude_deg"), lat.into_pyarray(py))?;
    output.set_item(format!("{name}_altitude_km"), alt.into_pyarray(py))?;
    Ok(())
}

fn set_vector<'py, F>(
    py: Python<'py>,
    output: &Bound<'py, PyDict>,
    name: &str,
    results: &[TraceResult],
    value: F,
) -> PyResult<()>
where
    F: Fn(&TraceResult) -> [f64; 3],
{
    let mut x = Vec::with_capacity(results.len());
    let mut y = Vec::with_capacity(results.len());
    let mut z = Vec::with_capacity(results.len());
    for result in results {
        let vector = value(result);
        x.push(vector[0]);
        y.push(vector[1]);
        z.push(vector[2]);
    }
    output.set_item(format!("{name}_x_nT"), x.into_pyarray(py))?;
    output.set_item(format!("{name}_y_nT"), y.into_pyarray(py))?;
    output.set_item(format!("{name}_z_nT"), z.into_pyarray(py))?;
    Ok(())
}

fn lon_lat_alt(position: [f64; 3]) -> [f64; 3] {
    let radius = norm(position);
    if !radius.is_finite() || radius <= 0.0 {
        return [f64::NAN; 3];
    }
    [
        position[1].atan2(position[0]).to_degrees(),
        (position[2] / radius).clamp(-1.0, 1.0).asin().to_degrees(),
        radius - MOON_RADIUS_KM,
    ]
}

fn norm(value: [f64; 3]) -> f64 {
    dot(value, value).sqrt()
}

fn dot(left: [f64; 3], right: [f64; 3]) -> f64 {
    left[0] * right[0] + left[1] * right[1] + left[2] * right[2]
}

fn add(left: [f64; 3], right: [f64; 3]) -> [f64; 3] {
    [left[0] + right[0], left[1] + right[1], left[2] + right[2]]
}

fn subtract(left: [f64; 3], right: [f64; 3]) -> [f64; 3] {
    [left[0] - right[0], left[1] - right[1], left[2] - right[2]]
}

fn scale(value: [f64; 3], factor: f64) -> [f64; 3] {
    [value[0] * factor, value[1] * factor, value[2] * factor]
}

fn lerp(left: f64, right: f64, fraction: f64) -> f64 {
    left + fraction * (right - left)
}

fn lerp3(left: [f64; 3], right: [f64; 3], fraction: f64) -> [f64; 3] {
    [
        lerp(left[0], right[0], fraction),
        lerp(left[1], right[1], fraction),
        lerp(left[2], right[2], fraction),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn radial_test_grid() -> ShellGrid {
        let longitude = vec![0.0, 180.0];
        let latitude = vec![-90.0, 0.0, 90.0];
        let altitude = vec![6.0, 100.0, 200.0];
        let mut field = Vec::new();
        for altitude_km in &altitude {
            for _ in &latitude {
                for _ in &longitude {
                    field.extend_from_slice(&[-(2.0 - altitude_km / 100.0), 0.0, 0.0]);
                }
            }
        }
        ShellGrid::new(longitude, latitude, altitude, field).unwrap()
    }

    #[test]
    fn shell_interpolation_is_periodic_and_linear_in_altitude() {
        let grid = radial_test_grid();
        let field = grid
            .field_at([MOON_RADIUS_KM + 50.0, 0.0, 0.0], false)
            .unwrap();
        assert!((field[0] + 1.5).abs() < 1.0e-12);
        assert_eq!(grid.interpolate(360.0, 0.0, 50.0), Some(field));
    }

    #[test]
    fn spherical_cap_window_tightens_equatorial_longitudes() {
        assert!((spherical_cap_longitude_width_deg(0.0, 0.0, 2.0) - 2.0).abs() < 1.0e-10);
        assert_eq!(spherical_cap_longitude_width_deg(89.0, 89.0, 2.1), 180.0);
    }

    #[test]
    fn trace_reaches_surface_and_locates_target_crossing() {
        let grid = radial_test_grid();
        let result = trace_one(
            &grid,
            [MOON_RADIUS_KM + 100.0, 0.0, 0.0],
            [0.0; 3],
            1,
            1.5,
            1.0,
            150,
            6.0,
        );
        assert!(result.valid);
        assert!(result.target_crossed);
        assert!((result.path_km - 94.0).abs() < 1.0e-6);
        assert!((lon_lat_alt(result.target_position)[2] - 50.0).abs() < 0.1);
    }
}
