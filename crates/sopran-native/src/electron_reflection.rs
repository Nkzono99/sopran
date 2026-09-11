use libm::lgamma;
use numpy::{IntoPyArray, PyReadonlyArray1, PyReadonlyArray2};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};
use rayon::prelude::*;

const INVALID_OBJECTIVE: f64 = 1.0e30;

#[derive(Clone, Copy)]
enum CandidateModel {
    NoEdge,
    MirrorOnly,
    Electrostatic,
}

#[derive(Clone, Copy)]
enum ContrastModel {
    None,
    Constant,
    Band,
}

#[derive(Clone, Copy)]
struct ParameterRange {
    start: usize,
    stop: usize,
}

struct Interpolation {
    left: usize,
    fraction: f64,
}

enum DetectorResponse {
    Identity,
    Diagonal(Vec<f64>),
    Dense(Vec<f64>),
}

struct Observation {
    sensor_index: usize,
    b_sc_n_t: f64,
    energy_count: usize,
    pitch_count: usize,
    pitch_sample_count: usize,
    energy_sample_count: usize,
    energy_response_e_v: Vec<f64>,
    energy_response_weights: Vec<f64>,
    spectrum_interpolation: Vec<Interpolation>,
    baseline_interpolation: Vec<Interpolation>,
    pitch_edges_deg: Vec<f64>,
    folded_pitch_response_deg: Vec<f64>,
    pitch_response_weights: Vec<f64>,
    physical_energy_row: Vec<bool>,
    affected: Vec<bool>,
    counts: Vec<f64>,
    exposure: Vec<f64>,
    known_background_counts: Vec<f64>,
    live_time_capacity_seconds: Vec<f64>,
    dead_time_seconds: f64,
    valid: Vec<bool>,
    detector_response: DetectorResponse,
}

#[pyclass(module = "sopran._native")]
pub struct GlobalHardProblem {
    model: CandidateModel,
    contrast_model: ContrastModel,
    physical: ParameterRange,
    spectrum: ParameterRange,
    baseline: ParameterRange,
    contrast: Option<ParameterRange>,
    beam: Option<ParameterRange>,
    gains: ParameterRange,
    backgrounds: ParameterRange,
    dispersions: ParameterRange,
    parameter_count: usize,
    bounds: Vec<(f64, f64)>,
    spacecraft_potential_e_v: f64,
    spectrum_smoothness: f64,
    observations: Vec<Observation>,
}

#[pymethods]
impl GlobalHardProblem {
    #[new]
    fn new(payload: &Bound<'_, PyDict>) -> PyResult<Self> {
        let model = match required(payload, "model")?.extract::<String>()?.as_str() {
            "no_edge" => CandidateModel::NoEdge,
            "mirror_only" => CandidateModel::MirrorOnly,
            "electrostatic" => CandidateModel::Electrostatic,
            value => return Err(value_error(format!("unsupported model: {value}"))),
        };
        let contrast_model = match required(payload, "contrast_model")?
            .extract::<String>()?
            .as_str()
        {
            "none" => ContrastModel::None,
            "constant" => ContrastModel::Constant,
            "band" => ContrastModel::Band,
            value => return Err(value_error(format!("unsupported contrast_model: {value}"))),
        };
        let physical = extract_range(payload, "physical")?;
        let spectrum = extract_range(payload, "spectrum")?;
        let baseline = extract_range(payload, "baseline")?;
        let contrast = if required(payload, "contrast")?.is_none() {
            None
        } else {
            Some(extract_range(payload, "contrast")?)
        };
        let beam = if required(payload, "beam")?.is_none() {
            None
        } else {
            Some(extract_range(payload, "beam")?)
        };
        let gains = extract_range(payload, "gains")?;
        let backgrounds = extract_range(payload, "backgrounds")?;
        let dispersions = extract_range(payload, "dispersions")?;
        let sensor_count = required(payload, "sensor_count")?.extract::<usize>()?;
        if sensor_count == 0 {
            return Err(value_error("sensor_count must be positive"));
        }
        let parameter_count = required(payload, "parameter_count")?.extract::<usize>()?;
        let bounds = extract_bounds(payload, parameter_count)?;
        let spectrum_knots = extract_vec_f64(payload, "log_energy_knots")?;
        let baseline_knots = extract_vec_f64(payload, "log_baseline_knots")?;
        validate_layout(
            parameter_count,
            model,
            contrast_model,
            physical,
            spectrum,
            baseline,
            contrast,
            beam,
            gains,
            backgrounds,
            dispersions,
            spectrum_knots.len(),
            baseline_knots.len(),
        )?;

        let observation_items = required(payload, "observations")?;
        let observation_items = observation_items.cast::<PyList>()?;
        if observation_items.is_empty() {
            return Err(value_error("observations must not be empty"));
        }
        if gains.stop - gains.start != sensor_count.saturating_sub(1)
            || dispersions.stop - dispersions.start != sensor_count
            || (!backgrounds.is_empty() && backgrounds.stop - backgrounds.start != sensor_count)
        {
            return Err(value_error(
                "sensor parameter ranges do not match observations",
            ));
        }
        let mut observations = Vec::with_capacity(observation_items.len());
        for item in observation_items.iter() {
            let item = item.cast::<PyDict>()?;
            let observation = Observation::from_python(item, &spectrum_knots, &baseline_knots)?;
            if observation.sensor_index >= sensor_count {
                return Err(value_error("observation sensor_index is out of range"));
            }
            observations.push(observation);
        }

        Ok(Self {
            model,
            contrast_model,
            physical,
            spectrum,
            baseline,
            contrast,
            beam,
            gains,
            backgrounds,
            dispersions,
            parameter_count,
            bounds,
            spacecraft_potential_e_v: required(payload, "spacecraft_potential_eV")?
                .extract::<f64>()?,
            spectrum_smoothness: required(payload, "spectrum_smoothness")?.extract::<f64>()?,
            observations,
        })
    }

    fn objective(&self, py: Python<'_>, parameters: PyReadonlyArray1<'_, f64>) -> PyResult<f64> {
        let parameters = parameters.as_slice()?.to_vec();
        if parameters.len() != self.parameter_count {
            return Err(value_error(format!(
                "parameters must have length {}, got {}",
                self.parameter_count,
                parameters.len()
            )));
        }
        Ok(py.detach(|| self.evaluate(&parameters)))
    }

    fn value_and_gradient<'py>(
        &self,
        py: Python<'py>,
        parameters: PyReadonlyArray1<'_, f64>,
    ) -> PyResult<(f64, Bound<'py, numpy::PyArray1<f64>>)> {
        let parameters = parameters.as_slice()?.to_vec();
        if parameters.len() != self.parameter_count {
            return Err(value_error(format!(
                "parameters must have length {}, got {}",
                self.parameter_count,
                parameters.len()
            )));
        }
        let (value, gradient) = py.detach(|| self.evaluate_with_gradient(&parameters));
        Ok((value, gradient.into_pyarray(py)))
    }

    fn value_and_gradient_indices<'py>(
        &self,
        py: Python<'py>,
        parameters: PyReadonlyArray1<'_, f64>,
        indices: Vec<usize>,
    ) -> PyResult<(f64, Bound<'py, numpy::PyArray1<f64>>)> {
        let parameters = parameters.as_slice()?.to_vec();
        if parameters.len() != self.parameter_count {
            return Err(value_error(format!(
                "parameters must have length {}, got {}",
                self.parameter_count,
                parameters.len()
            )));
        }
        if indices.iter().any(|index| *index >= self.parameter_count) {
            return Err(value_error("gradient index is out of range"));
        }
        let (value, gradient) =
            py.detach(|| self.evaluate_with_gradient_indices(&parameters, &indices));
        Ok((value, gradient.into_pyarray(py)))
    }
}

impl GlobalHardProblem {
    fn evaluate(&self, parameters: &[f64]) -> f64 {
        let mut likelihood = 0.0;
        for observation in &self.observations {
            let sensor_likelihood =
                self.sensor_log_likelihood(parameters, observation.sensor_index, observation);
            if !sensor_likelihood.is_finite() {
                return INVALID_OBJECTIVE;
            }
            likelihood += sensor_likelihood;
        }
        let spectrum = &parameters[self.spectrum.start..self.spectrum.stop];
        let roughness = spectrum
            .windows(3)
            .map(|values| {
                let second_difference = values[2] - 2.0 * values[1] + values[0];
                second_difference * second_difference
            })
            .sum::<f64>();
        let objective = -likelihood + 0.5 * self.spectrum_smoothness * roughness;
        if objective.is_finite() {
            objective
        } else {
            INVALID_OBJECTIVE
        }
    }

    fn evaluate_with_gradient(&self, parameters: &[f64]) -> (f64, Vec<f64>) {
        let indices = (0..parameters.len()).collect::<Vec<_>>();
        self.evaluate_with_gradient_indices(parameters, &indices)
    }

    fn evaluate_with_gradient_indices(
        &self,
        parameters: &[f64],
        indices: &[usize],
    ) -> (f64, Vec<f64>) {
        let value = self.evaluate(parameters);
        let gradient = indices
            .par_iter()
            .map(|index| {
                if self.bounds[*index].0 == self.bounds[*index].1 {
                    return 0.0;
                }
                let mut shifted = parameters.to_vec();
                let step = finite_difference_step(
                    parameters[*index],
                    self.bounds[*index].0,
                    self.bounds[*index].1,
                );
                shifted[*index] += step;
                let actual_step = shifted[*index] - parameters[*index];
                (self.evaluate(&shifted) - value) / actual_step
            })
            .collect();
        (value, gradient)
    }

    fn sensor_log_likelihood(
        &self,
        parameters: &[f64],
        sensor_index: usize,
        observation: &Observation,
    ) -> f64 {
        let cell_count = observation.energy_count * observation.pitch_count;
        let mut rates = vec![0.0; cell_count];
        let gain = if sensor_index == 0 {
            0.0
        } else {
            parameters[self.gains.start + sensor_index - 1]
        };
        let mirror_ratio = match self.model {
            CandidateModel::NoEdge => None,
            CandidateModel::MirrorOnly | CandidateModel::Electrostatic => {
                Some(parameters[self.physical.start].exp() / observation.b_sc_n_t)
            }
        };
        let delta_u = match self.model {
            CandidateModel::Electrostatic => parameters[self.physical.start + 1],
            CandidateModel::NoEdge | CandidateModel::MirrorOnly => 0.0,
        };

        for sample_index in 0..observation.energy_sample_count {
            let energy_weight = observation.energy_response_weights[sample_index];
            for energy_index in 0..observation.energy_count {
                let sample_offset = energy_index * observation.energy_sample_count + sample_index;
                let energy = observation.energy_response_e_v[sample_offset];
                let incident_log = interpolate_parameters(
                    parameters,
                    self.spectrum,
                    &observation.spectrum_interpolation[sample_offset],
                );
                let incident_rate = incident_log.clamp(-100.0, 100.0).exp();
                let baseline_log = interpolate_parameters(
                    parameters,
                    self.baseline,
                    &observation.baseline_interpolation[sample_offset],
                );
                let amplitude = self.contrast(parameters, energy);
                let boundary_pitch = mirror_ratio.and_then(|ratio| {
                    boundary_pitch_deg(energy, ratio, delta_u, self.spacecraft_potential_e_v)
                });
                for pitch_index in 0..observation.pitch_count {
                    let mut normalized_rate = if observation.affected[pitch_index] {
                        match mirror_ratio {
                            None => baseline_log.exp(),
                            Some(_) => {
                                let Some(boundary_pitch) = boundary_pitch else {
                                    rates[energy_index * observation.pitch_count + pitch_index] =
                                        f64::NAN;
                                    continue;
                                };
                                let transmitted = pitch_bin_transmission(
                                    observation.pitch_edges_deg[pitch_index],
                                    observation.pitch_edges_deg[pitch_index + 1],
                                    boundary_pitch,
                                );
                                baseline_log.exp()
                                    * (transmitted + (1.0 - transmitted) * (-amplitude).exp())
                            }
                        }
                    } else {
                        1.0
                    };
                    if observation.affected[pitch_index] {
                        normalized_rate +=
                            self.secondary_beam_ratio(parameters, observation, energy, pitch_index);
                    }
                    rates[energy_index * observation.pitch_count + pitch_index] +=
                        energy_weight * incident_rate * normalized_rate;
                }
            }
        }
        rates = observation.apply_detector_response(rates);

        let background_rate = if self.backgrounds.is_empty() {
            0.0
        } else {
            parameters[self.backgrounds.start + sensor_index].exp()
        };
        let dispersion = parameters[self.dispersions.start + sensor_index].exp();
        let mut likelihood = 0.0;
        let mut valid_cells = 0_usize;
        for (cell_index, rate) in rates.into_iter().enumerate() {
            if !observation.valid[cell_index] {
                continue;
            }
            let source_mean = observation.exposure[cell_index] * gain.exp() * rate;
            let pre_dead_time_mean = source_mean
                + observation.known_background_counts[cell_index]
                + background_rate * observation.live_time_capacity_seconds[cell_index];
            let mean = if observation.dead_time_seconds == 0.0 {
                pre_dead_time_mean
            } else {
                pre_dead_time_mean
                    / (1.0
                        + observation.dead_time_seconds * pre_dead_time_mean
                            / observation.live_time_capacity_seconds[cell_index])
            };
            let log_mean = mean.ln();
            if !log_mean.is_finite() {
                continue;
            }
            valid_cells += 1;
            let counts = observation.counts[cell_index];
            let log_mu = log_mean.clamp(-30.0, 30.0);
            let mu = log_mu.exp();
            let value = lgamma(counts + dispersion) - lgamma(dispersion) - lgamma(counts + 1.0)
                + dispersion * (dispersion.ln() - (dispersion + mu).ln())
                + counts * (log_mu - (dispersion + mu).ln());
            if !value.is_finite() {
                return f64::NEG_INFINITY;
            }
            likelihood += value;
        }
        if valid_cells == 0 {
            f64::NEG_INFINITY
        } else {
            likelihood
        }
    }

    fn contrast(&self, parameters: &[f64], energy_e_v: f64) -> f64 {
        match (self.contrast_model, self.contrast) {
            (ContrastModel::None, _) => 0.0,
            (ContrastModel::Constant, Some(range)) => parameters[range.start],
            (ContrastModel::Band, Some(range)) => {
                let floor = parameters[range.start];
                let excess = parameters[range.start + 1];
                let center = parameters[range.start + 2];
                let width = parameters[range.start + 3].exp();
                let distance = energy_e_v.ln() - center;
                floor + excess * (-0.5 * (distance / width).powi(2)).exp()
            }
            _ => f64::NAN,
        }
    }

    fn secondary_beam_ratio(
        &self,
        parameters: &[f64],
        observation: &Observation,
        energy_e_v: f64,
        pitch_index: usize,
    ) -> f64 {
        let Some(range) = self.beam else {
            return 0.0;
        };
        let amplitude = parameters[range.start].exp();
        let center = parameters[range.start + 1].exp();
        let sigma_energy = parameters[range.start + 2].exp();
        let sigma_pitch = parameters[range.start + 3].exp();
        let energy_distance = (energy_e_v / center).ln() / sigma_energy;
        let energy_profile = (-0.5 * energy_distance * energy_distance).exp();
        let pitch_offset = pitch_index * observation.pitch_sample_count;
        let pitch_profile = observation.folded_pitch_response_deg
            [pitch_offset..pitch_offset + observation.pitch_sample_count]
            .iter()
            .zip(&observation.pitch_response_weights)
            .map(|(pitch, weight)| {
                let distance = pitch / sigma_pitch;
                weight * (-0.5 * distance * distance).exp()
            })
            .sum::<f64>();
        amplitude * energy_profile * pitch_profile
    }
}

impl Observation {
    fn from_python(
        payload: &Bound<'_, PyDict>,
        spectrum_knots: &[f64],
        baseline_knots: &[f64],
    ) -> PyResult<Self> {
        let energy_response = extract_array2_f64(payload, "energy_response_eV")?;
        let energy_count = energy_response.0;
        let energy_sample_count = energy_response.1;
        let energy_response_e_v = energy_response.2;
        let energy_response_weights = extract_vec_f64(payload, "energy_response_weights")?;
        if energy_response_weights.len() != energy_sample_count {
            return Err(value_error(
                "energy_response_weights must match energy_response_eV columns",
            ));
        }
        let (count_rows, pitch_count, counts) = extract_array2_f64(payload, "counts")?;
        if count_rows != energy_count {
            return Err(value_error(
                "counts rows must match energy_response_eV rows",
            ));
        }
        let exposure = extract_matching_array2_f64(payload, "exposure", energy_count, pitch_count)?;
        let known_background_counts = extract_matching_array2_f64(
            payload,
            "known_background_counts",
            energy_count,
            pitch_count,
        )?;
        let live_time_capacity_seconds = extract_matching_array2_f64(
            payload,
            "live_time_capacity_seconds",
            energy_count,
            pitch_count,
        )?;
        let valid = extract_matching_array2_bool(payload, "valid", energy_count, pitch_count)?;
        let physical_energy_row = extract_vec_bool(payload, "physical_energy_row")?;
        if physical_energy_row.len() != energy_count {
            return Err(value_error("physical_energy_row must match counts rows"));
        }
        let affected = extract_vec_bool(payload, "affected")?;
        if affected.len() != pitch_count {
            return Err(value_error("affected must match counts columns"));
        }
        let pitch_edges_deg = extract_vec_f64(payload, "pitch_edges_deg")?;
        if pitch_edges_deg.len() != pitch_count + 1
            || pitch_edges_deg
                .windows(2)
                .any(|values| values[0] >= values[1])
        {
            return Err(value_error(
                "pitch_edges_deg must be strictly increasing with one more value than pitch bins",
            ));
        }
        let pitch_response = extract_array2_f64(payload, "folded_pitch_response_deg")?;
        if pitch_response.0 != pitch_count {
            return Err(value_error(
                "folded_pitch_response_deg rows must match counts columns",
            ));
        }
        let pitch_sample_count = pitch_response.1;
        let pitch_response_weights = extract_vec_f64(payload, "pitch_response_weights")?;
        if pitch_sample_count == 0 || pitch_response_weights.len() != pitch_sample_count {
            return Err(value_error(
                "pitch_response_weights must match folded pitch response columns",
            ));
        }
        if energy_response_e_v
            .iter()
            .any(|value| !value.is_finite() || *value <= 0.0)
            || energy_response_weights
                .iter()
                .any(|value| !value.is_finite())
        {
            return Err(value_error(
                "energy response values and weights must be finite and energies positive",
            ));
        }
        let spectrum_interpolation = build_interpolation(&energy_response_e_v, spectrum_knots)?;
        let baseline_interpolation = build_interpolation(&energy_response_e_v, baseline_knots)?;
        let detector_response = extract_detector_response(payload, energy_count * pitch_count)?;
        let b_sc_n_t = required(payload, "b_sc_nT")?.extract::<f64>()?;
        if !b_sc_n_t.is_finite() || b_sc_n_t <= 0.0 {
            return Err(value_error("b_sc_nT must be finite and positive"));
        }
        Ok(Self {
            sensor_index: required(payload, "sensor_index")?.extract::<usize>()?,
            b_sc_n_t,
            energy_count,
            pitch_count,
            pitch_sample_count,
            energy_sample_count,
            energy_response_e_v,
            energy_response_weights,
            spectrum_interpolation,
            baseline_interpolation,
            pitch_edges_deg,
            folded_pitch_response_deg: pitch_response.2,
            pitch_response_weights,
            physical_energy_row,
            affected,
            counts,
            exposure,
            known_background_counts,
            live_time_capacity_seconds,
            dead_time_seconds: required(payload, "dead_time_seconds")?.extract::<f64>()?,
            valid,
            detector_response,
        })
    }

    fn apply_detector_response(&self, rates: Vec<f64>) -> Vec<f64> {
        match &self.detector_response {
            DetectorResponse::Identity => rates,
            DetectorResponse::Diagonal(diagonal) => rates
                .into_iter()
                .enumerate()
                .map(|(index, rate)| {
                    let energy_index = index / self.pitch_count;
                    if self.physical_energy_row[energy_index] && rate.is_finite() {
                        diagonal[index] * rate
                    } else {
                        0.0
                    }
                })
                .collect(),
            DetectorResponse::Dense(matrix) => {
                let cell_count = rates.len();
                let latent = rates
                    .into_iter()
                    .enumerate()
                    .map(|(index, rate)| {
                        let energy_index = index / self.pitch_count;
                        if self.physical_energy_row[energy_index] && rate.is_finite() {
                            rate
                        } else {
                            0.0
                        }
                    })
                    .collect::<Vec<_>>();
                matrix
                    .chunks_exact(cell_count)
                    .map(|row| {
                        row.iter()
                            .zip(&latent)
                            .map(|(response, rate)| response * rate)
                            .sum()
                    })
                    .collect()
            }
        }
    }
}

impl ParameterRange {
    fn is_empty(self) -> bool {
        self.start == self.stop
    }
}

fn build_interpolation(values: &[f64], knots: &[f64]) -> PyResult<Vec<Interpolation>> {
    if knots.is_empty()
        || knots.iter().any(|value| !value.is_finite())
        || knots.windows(2).any(|values| values[0] >= values[1])
    {
        return Err(value_error(
            "interpolation knots must be finite and increasing",
        ));
    }
    Ok(values
        .iter()
        .map(|value| interpolation(value.ln(), knots))
        .collect())
}

fn interpolation(value: f64, knots: &[f64]) -> Interpolation {
    if knots.len() == 1 || value <= knots[0] {
        return Interpolation {
            left: 0,
            fraction: 0.0,
        };
    }
    if value >= knots[knots.len() - 1] {
        return Interpolation {
            left: knots.len() - 2,
            fraction: 1.0,
        };
    }
    let right = knots.partition_point(|knot| *knot < value);
    let left = right - 1;
    Interpolation {
        left,
        fraction: (value - knots[left]) / (knots[right] - knots[left]),
    }
}

fn interpolate_parameters(
    parameters: &[f64],
    range: ParameterRange,
    interpolation: &Interpolation,
) -> f64 {
    let left = parameters[range.start + interpolation.left];
    if range.stop - range.start == 1 {
        return left;
    }
    let right = parameters[range.start + interpolation.left + 1];
    left + interpolation.fraction * (right - left)
}

fn boundary_pitch_deg(
    energy_e_v: f64,
    mirror_ratio: f64,
    delta_u_eff_e_v: f64,
    spacecraft_potential_e_v: f64,
) -> Option<f64> {
    let corrected = energy_e_v - spacecraft_potential_e_v;
    let boundary = (1.0 + delta_u_eff_e_v / corrected) / mirror_ratio;
    if !corrected.is_finite()
        || corrected <= 0.0
        || !mirror_ratio.is_finite()
        || mirror_ratio <= 0.0
        || !boundary.is_finite()
    {
        return None;
    }
    if boundary <= 0.0 {
        Some(0.0)
    } else if boundary >= 1.0 {
        Some(90.0)
    } else {
        Some(boundary.sqrt().asin().to_degrees())
    }
}

fn pitch_bin_transmission(lower: f64, upper: f64, boundary_pitch: f64) -> f64 {
    let transmitted_lower = lower.max(boundary_pitch);
    let transmitted_upper = upper.min(180.0 - boundary_pitch);
    (transmitted_upper - transmitted_lower).max(0.0) / (upper - lower)
}

fn finite_difference_step(value: f64, lower: f64, upper: f64) -> f64 {
    let sign = if value >= 0.0 { 1.0 } else { -1.0 };
    let mut step = f64::EPSILON.sqrt() * sign * value.abs().max(1.0);
    let lower_distance = value - lower;
    let upper_distance = upper - value;
    let shifted = value + step;
    let violated = shifted < lower || shifted > upper;
    let fitting = step.abs() <= lower_distance.max(upper_distance);
    if violated && fitting {
        step = -step;
    } else if !fitting && upper_distance >= lower_distance {
        step = upper_distance;
    } else if !fitting {
        step = -lower_distance;
    }
    step
}

#[allow(clippy::too_many_arguments)]
fn validate_layout(
    parameter_count: usize,
    model: CandidateModel,
    contrast_model: ContrastModel,
    physical: ParameterRange,
    spectrum: ParameterRange,
    baseline: ParameterRange,
    contrast: Option<ParameterRange>,
    beam: Option<ParameterRange>,
    gains: ParameterRange,
    backgrounds: ParameterRange,
    dispersions: ParameterRange,
    spectrum_knot_count: usize,
    baseline_knot_count: usize,
) -> PyResult<()> {
    let ranges = [
        physical,
        spectrum,
        baseline,
        gains,
        backgrounds,
        dispersions,
    ];
    if ranges
        .iter()
        .any(|range| range.start > range.stop || range.stop > parameter_count)
        || contrast.is_some_and(|range| range.start > range.stop || range.stop > parameter_count)
        || beam.is_some_and(|range| range.start > range.stop || range.stop > parameter_count)
    {
        return Err(value_error("parameter range is outside parameter_count"));
    }
    let expected_physical = match model {
        CandidateModel::NoEdge => 0,
        CandidateModel::MirrorOnly => 1,
        CandidateModel::Electrostatic => 2,
    };
    let expected_contrast = match contrast_model {
        ContrastModel::None => 0,
        ContrastModel::Constant => 1,
        ContrastModel::Band => 4,
    };
    if physical.stop - physical.start != expected_physical
        || spectrum.stop - spectrum.start != spectrum_knot_count
        || baseline.stop - baseline.start != baseline_knot_count
        || spectrum_knot_count < 2
        || baseline_knot_count < 1
        || contrast.map_or(0, |range| range.stop - range.start) != expected_contrast
        || beam.map_or(0, |range| range.stop - range.start) != if beam.is_some() { 4 } else { 0 }
    {
        return Err(value_error(
            "parameter layout is inconsistent with the model",
        ));
    }
    Ok(())
}

fn extract_range(payload: &Bound<'_, PyDict>, key: &str) -> PyResult<ParameterRange> {
    let value = required(payload, key)?;
    let (start, stop) = value.extract::<(usize, usize)>()?;
    Ok(ParameterRange { start, stop })
}

fn extract_vec_f64(payload: &Bound<'_, PyDict>, key: &str) -> PyResult<Vec<f64>> {
    let value = required(payload, key)?;
    let array = value.extract::<PyReadonlyArray1<'_, f64>>()?;
    Ok(array.as_array().iter().copied().collect())
}

fn extract_vec_bool(payload: &Bound<'_, PyDict>, key: &str) -> PyResult<Vec<bool>> {
    let value = required(payload, key)?;
    let array = value.extract::<PyReadonlyArray1<'_, bool>>()?;
    Ok(array.as_array().iter().copied().collect())
}

fn extract_array2_f64(
    payload: &Bound<'_, PyDict>,
    key: &str,
) -> PyResult<(usize, usize, Vec<f64>)> {
    let value = required(payload, key)?;
    let array = value.extract::<PyReadonlyArray2<'_, f64>>()?;
    let view = array.as_array();
    Ok((
        view.shape()[0],
        view.shape()[1],
        view.iter().copied().collect(),
    ))
}

fn extract_matching_array2_f64(
    payload: &Bound<'_, PyDict>,
    key: &str,
    rows: usize,
    columns: usize,
) -> PyResult<Vec<f64>> {
    let (actual_rows, actual_columns, values) = extract_array2_f64(payload, key)?;
    if (actual_rows, actual_columns) != (rows, columns) {
        return Err(value_error(format!(
            "{key} must have shape ({rows}, {columns})"
        )));
    }
    Ok(values)
}

fn extract_matching_array2_bool(
    payload: &Bound<'_, PyDict>,
    key: &str,
    rows: usize,
    columns: usize,
) -> PyResult<Vec<bool>> {
    let value = required(payload, key)?;
    let array = value.extract::<PyReadonlyArray2<'_, bool>>()?;
    let view = array.as_array();
    if view.shape() != [rows, columns] {
        return Err(value_error(format!(
            "{key} must have shape ({rows}, {columns})"
        )));
    }
    Ok(view.iter().copied().collect())
}

fn extract_detector_response(
    payload: &Bound<'_, PyDict>,
    cell_count: usize,
) -> PyResult<DetectorResponse> {
    let value = required(payload, "detector_response_matrix")?;
    if value.is_none() {
        return Ok(DetectorResponse::Identity);
    }
    let (rows, columns, matrix) = extract_array2_f64(payload, "detector_response_matrix")?;
    if (rows, columns) != (cell_count, cell_count) {
        return Err(value_error(format!(
            "detector_response_matrix must have shape ({cell_count}, {cell_count})"
        )));
    }
    let is_diagonal = matrix.iter().enumerate().all(|(index, value)| {
        let row = index / cell_count;
        let column = index % cell_count;
        row == column || *value == 0.0
    });
    if is_diagonal {
        Ok(DetectorResponse::Diagonal(
            (0..cell_count)
                .map(|index| matrix[index * cell_count + index])
                .collect(),
        ))
    } else {
        Ok(DetectorResponse::Dense(matrix))
    }
}

fn extract_bounds(
    payload: &Bound<'_, PyDict>,
    parameter_count: usize,
) -> PyResult<Vec<(f64, f64)>> {
    let (rows, columns, values) = extract_array2_f64(payload, "bounds")?;
    if (rows, columns) != (parameter_count, 2) {
        return Err(value_error(format!(
            "bounds must have shape ({parameter_count}, 2)"
        )));
    }
    let bounds = values
        .chunks_exact(2)
        .map(|values| (values[0], values[1]))
        .collect::<Vec<_>>();
    if bounds.iter().any(|(lower, upper)| lower > upper) {
        return Err(value_error("each lower bound must be <= its upper bound"));
    }
    Ok(bounds)
}

fn required<'py>(payload: &Bound<'py, PyDict>, key: &str) -> PyResult<Bound<'py, PyAny>> {
    payload
        .get_item(key)?
        .ok_or_else(|| value_error(format!("missing required field: {key}")))
}

fn value_error(message: impl Into<String>) -> PyErr {
    PyValueError::new_err(message.into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn interpolation_matches_clamped_linear_behavior() {
        let knots = [0.0, 1.0, 3.0];
        let below = interpolation(-1.0, &knots);
        let interior = interpolation(2.0, &knots);
        let above = interpolation(4.0, &knots);

        assert_eq!(below.left, 0);
        assert_eq!(below.fraction, 0.0);
        assert_eq!(interior.left, 1);
        assert_eq!(interior.fraction, 0.5);
        assert_eq!(above.left, 1);
        assert_eq!(above.fraction, 1.0);
    }

    #[test]
    fn hard_pitch_bin_uses_fractional_overlap() {
        assert!((pitch_bin_transmission(20.0, 40.0, 30.0) - 0.5).abs() < 1.0e-12);
        assert_eq!(pitch_bin_transmission(140.0, 160.0, 30.0), 0.5);
    }

    #[test]
    fn finite_difference_step_turns_away_from_bounds() {
        assert!(finite_difference_step(1.0, 0.0, 1.0) < 0.0);
        assert!(finite_difference_step(0.0, 0.0, 1.0) > 0.0);
    }
}
