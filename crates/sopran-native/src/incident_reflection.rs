//! Packed diagonal-response incident PAD model and analytic NB gradient.
use libm::lgamma;
use numpy::{IntoPyArray, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::HashMap;

struct ResponseValues {
    incident: f64,
    k: f64,
    full: f64,
    full_k: f64,
    beam_distance: f64,
    beam_energy: f64,
}

#[pyclass(module = "sopran._native")]
pub struct IncidentHardProblem {
    energy: Vec<f64>,
    weights: Vec<f64>,
    lower: Vec<f64>,
    upper: Vec<f64>,
    b: Vec<f64>,
    counts: Vec<f64>,
    exposure: Vec<f64>,
    sensor: Vec<usize>,
    affected: Vec<bool>,
    sb: Vec<f64>,
    ab: Vec<f64>,
    nodes: Vec<f64>,
    pw: Vec<f64>,
    log_factorial: Vec<f64>,
    full_z: Vec<f64>,
    pitch_squared: Vec<f64>,
    pitch_representatives: Vec<usize>,
    pitch_groups: Vec<usize>,
    response_representatives: Vec<(usize, usize)>,
    response_groups: Vec<usize>,
    boundary_inputs: Vec<(f64, f64)>,
    boundary_groups: Vec<usize>,
    count_inputs: Vec<(usize, f64)>,
    count_groups: Vec<usize>,
    ne: usize,
    ns: usize,
    na: usize,
    np: usize,
    spectrum: usize,
    baseline: usize,
    contrast: Option<usize>,
    beam: Option<usize>,
    gains: usize,
    dispersion: usize,
    anisotropy: usize,
    model: usize,
    phi: f64,
}

fn get<'py>(p: &Bound<'py, PyDict>, key: &str) -> PyResult<Bound<'py, PyAny>> {
    p.get_item(key)?
        .ok_or_else(|| PyValueError::new_err(format!("missing {key}")))
}

fn array(p: &Bound<'_, PyDict>, key: &str) -> PyResult<Vec<f64>> {
    Ok(get(p, key)?
        .extract::<PyReadonlyArray1<'_, f64>>()?
        .as_slice()?
        .to_vec())
}

fn digamma(mut x: f64) -> f64 {
    let mut value = 0.;
    while x < 16. {
        value -= 1. / x;
        x += 1.;
    }
    let z = 1. / (x * x);
    value + x.ln()
        - 0.5 / x
        - z * (1. / 12. - z * (1. / 120. - z * (1. / 252. - z * (1. / 240. - z / 132.))))
}

#[pymethods]
impl IncidentHardProblem {
    #[new]
    fn new(p: &Bound<'_, PyDict>) -> PyResult<Self> {
        let mut s = Self {
            energy: array(p, "energy")?,
            weights: array(p, "weights")?,
            lower: array(p, "lower")?,
            upper: array(p, "upper")?,
            b: array(p, "b")?,
            counts: array(p, "counts")?,
            exposure: array(p, "exposure")?,
            sensor: get(p, "sensor")?.extract()?,
            affected: get(p, "affected")?.extract()?,
            sb: array(p, "sb")?,
            ab: array(p, "ab")?,
            nodes: array(p, "nodes")?,
            pw: array(p, "pw")?,
            ne: get(p, "ne")?.extract()?,
            ns: get(p, "ns")?.extract()?,
            na: get(p, "na")?.extract()?,
            np: get(p, "np")?.extract()?,
            spectrum: get(p, "spectrum")?.extract()?,
            baseline: get(p, "baseline")?.extract()?,
            contrast: get(p, "contrast")?.extract()?,
            beam: get(p, "beam")?.extract()?,
            gains: get(p, "gains")?.extract()?,
            dispersion: get(p, "dispersion")?.extract()?,
            anisotropy: get(p, "anisotropy")?.extract()?,
            model: get(p, "model")?.extract()?,
            phi: get(p, "phi")?.extract()?,
            log_factorial: vec![],
            full_z: vec![],
            pitch_squared: vec![],
            pitch_representatives: vec![],
            pitch_groups: vec![],
            response_representatives: vec![],
            response_groups: vec![],
            boundary_inputs: vec![],
            boundary_groups: vec![],
            count_inputs: vec![],
            count_groups: vec![],
        };
        let n = s.counts.len();
        let size = n
            .checked_mul(s.ne)
            .ok_or_else(|| PyValueError::new_err("array size overflow"))?;
        let valid = n > 0
            && s.ne > 0
            && s.ns > 0
            && s.np > 0
            && s.model <= 2
            && s.energy.len() == size
            && s.weights.len() == size
            && s.sb.len() == size.checked_mul(s.ns).unwrap_or(usize::MAX)
            && s.ab.len() == size.checked_mul(s.na).unwrap_or(usize::MAX)
            && s.lower.len() == n
            && s.upper.len() == n
            && s.b.len() == n
            && s.exposure.len() == n
            && s.sensor.len() == n
            && s.affected.len() == n
            && !s.nodes.is_empty()
            && s.pw.len() == s.nodes.len()
            && s.spectrum.checked_add(s.ns).is_some_and(|v| v <= s.np)
            && s.anisotropy.checked_add(s.na).is_some_and(|v| v <= s.np)
            && s.baseline < s.np
            && s.contrast.is_none_or(|i| i < s.np)
            && s.beam
                .is_none_or(|i| i.checked_add(4).is_some_and(|v| v <= s.np))
            && (s.model == 0 || s.contrast.is_some())
            && (s.model != 2 || s.np >= 2)
            && s.sensor.iter().all(|i| {
                s.dispersion.checked_add(*i).is_some_and(|v| v < s.np)
                    && (*i == 0 || s.gains.checked_add(i - 1).is_some_and(|v| v < s.np))
            });
        if !valid {
            return Err(PyValueError::new_err(
                "invalid packed incident model dimensions/layout",
            ));
        }
        if !s.phi.is_finite()
            || s.energy
                .iter()
                .any(|v| !v.is_finite() || *v <= s.phi || *v <= 0.)
            || s.counts.iter().any(|v| !v.is_finite() || *v < 0.)
            || s.exposure
                .iter()
                .chain(s.b.iter())
                .any(|v| !v.is_finite() || *v <= 0.)
            || s.lower.iter().zip(&s.upper).any(|(a, b)| {
                !a.is_finite()
                    || !b.is_finite()
                    || *a < 0.
                    || *b > std::f64::consts::FRAC_PI_2 + 1e-12
                    || a >= b
            })
            || s.weights
                .iter()
                .chain(s.pw.iter())
                .any(|v| !v.is_finite() || *v < 0.)
            || s.nodes.iter().any(|v| !v.is_finite() || *v < 0. || *v > 1.)
            || s.sb.iter().chain(s.ab.iter()).any(|v| !v.is_finite())
        {
            return Err(PyValueError::new_err(
                "nonphysical/nonfinite packed incident data",
            ));
        }
        s.log_factorial = s.counts.iter().map(|y| lgamma(y + 1.)).collect();
        for cell in 0..n {
            for node in &s.nodes {
                let angle = s.lower[cell] + (s.upper[cell] - s.lower[cell]) * node;
                s.full_z.push(angle.cos().powi(2));
                s.pitch_squared.push(angle.to_degrees().powi(2));
            }
        }
        // Exact bit-pattern keys share only parameter-independent response geometry.
        // Bsc, counts, exposure and hemisphere remain individual native-cell inputs.
        let mut pitches = HashMap::new();
        let mut responses = HashMap::new();
        let mut boundaries = HashMap::new();
        let mut counts = HashMap::new();
        for cell in 0..n {
            let count_key = (s.sensor[cell], s.counts[cell].to_bits());
            let count_group = *counts.entry(count_key).or_insert_with(|| {
                let index = s.count_inputs.len();
                s.count_inputs.push((s.sensor[cell], s.counts[cell]));
                index
            });
            s.count_groups.push(count_group);
            let key = (s.lower[cell].to_bits(), s.upper[cell].to_bits());
            let pitch = *pitches.entry(key).or_insert_with(|| {
                let index = s.pitch_representatives.len();
                s.pitch_representatives.push(cell);
                index
            });
            s.pitch_groups.push(pitch);
            for e in 0..s.ne {
                let at = cell * s.ne + e;
                let mut key = vec![pitch as u64, s.energy[at].to_bits()];
                key.extend(s.sb[at * s.ns..(at + 1) * s.ns].iter().map(|v| v.to_bits()));
                key.extend(s.ab[at * s.na..(at + 1) * s.na].iter().map(|v| v.to_bits()));
                let group = *responses.entry(key).or_insert_with(|| {
                    let index = s.response_representatives.len();
                    s.response_representatives.push((cell, at));
                    index
                });
                s.response_groups.push(group);
                let boundary_group = if s.model > 0 && s.affected[cell] {
                    let key = (s.energy[at].to_bits(), s.b[cell].to_bits());
                    *boundaries.entry(key).or_insert_with(|| {
                        let index = s.boundary_inputs.len();
                        s.boundary_inputs.push((s.energy[at] - s.phi, s.b[cell]));
                        index
                    })
                } else {
                    usize::MAX
                };
                s.boundary_groups.push(boundary_group);
            }
        }
        Ok(s)
    }

    fn value_and_gradient<'py>(
        &self,
        py: Python<'py>,
        vector: PyReadonlyArray1<'_, f64>,
    ) -> PyResult<(f64, Bound<'py, numpy::PyArray1<f64>>)> {
        let v = vector.as_slice()?.to_vec();
        if v.len() != self.np || v.iter().any(|x| !x.is_finite()) {
            return Err(PyValueError::new_err("invalid parameter vector"));
        }
        let (value, gradient, _) = py.detach(|| self.evaluate(&v, false));
        Ok((value, gradient.into_pyarray(py)))
    }

    fn predict<'py>(
        &self,
        py: Python<'py>,
        vector: PyReadonlyArray1<'_, f64>,
    ) -> PyResult<Bound<'py, numpy::PyArray1<f64>>> {
        let v = vector.as_slice()?.to_vec();
        if v.len() != self.np || v.iter().any(|x| !x.is_finite()) {
            return Err(PyValueError::new_err("invalid parameter vector"));
        }
        let (_, _, mean) = py.detach(|| self.evaluate(&v, true));
        Ok(mean.into_pyarray(py))
    }
}

impl IncidentHardProblem {
    fn moments(&self, k: f64, lower: f64, upper: f64, width: f64) -> (f64, f64) {
        let span = (upper - lower).max(0.);
        let (mut sum, mut derivative) = (0., 0.);
        for (node, w) in self.nodes.iter().zip(&self.pw) {
            let z = (lower + span * node).cos().powi(2);
            let g = (k * z).exp() * w;
            sum += g;
            derivative += g * z;
        }
        (sum * span / width, derivative * span / width)
    }

    fn evaluate(&self, v: &[f64], save_mean: bool) -> (f64, Vec<f64>, Vec<f64>) {
        let mut grad = vec![0.; self.np];
        let mut jac = vec![0.; self.np];
        let mut means = if save_mean {
            Vec::with_capacity(self.counts.len())
        } else {
            vec![]
        };
        let mut nll = 0.;
        let c = v[self.baseline].exp();
        let field = if self.model > 0 { v[0].exp() } else { 1. };
        let delta = if self.model == 2 { v[1] } else { 0. };
        let floor = self.contrast.map(|i| (-v[i]).exp()).unwrap_or(1.);
        let beam = self
            .beam
            .map(|i| [v[i].exp(), v[i + 1].exp(), v[i + 2].exp(), v[i + 3].exp()]);
        let beam_pitch: Vec<_> = self
            .pitch_representatives
            .iter()
            .map(|&cell| {
                let (mut value, mut derivative) = (0., 0.);
                if let Some(b) = beam {
                    for (q, w) in self.pw.iter().enumerate() {
                        let z = self.pitch_squared[cell * self.nodes.len() + q] / b[3].powi(2);
                        let g = (-0.5 * z).exp() * w;
                        value += g;
                        derivative += g * z;
                    }
                }
                (value, derivative)
            })
            .collect();
        let responses: Vec<_> = self
            .response_representatives
            .iter()
            .map(|&(cell, at)| {
                let k: f64 = self.ab[at * self.na..(at + 1) * self.na]
                    .iter()
                    .enumerate()
                    .map(|(i, w)| w * v[self.anisotropy + i])
                    .sum();
                let incident = self.sb[at * self.ns..(at + 1) * self.ns]
                    .iter()
                    .enumerate()
                    .map(|(i, w)| w * v[self.spectrum + i])
                    .sum::<f64>()
                    .exp();
                let (mut full, mut full_k) = (0., 0.);
                for (q, weight) in self.pw.iter().enumerate() {
                    let z = self.full_z[cell * self.nodes.len() + q];
                    let value = (k * z).exp() * weight;
                    full += value;
                    full_k += value * z;
                }
                let (beam_distance, beam_energy) = if let Some(b) = beam {
                    let distance = (self.energy[at] / b[1]).ln();
                    (distance, b[0] * (-0.5 * (distance / b[2]).powi(2)).exp())
                } else {
                    (0., 0.)
                };
                ResponseValues {
                    incident,
                    k,
                    full,
                    full_k,
                    beam_distance,
                    beam_energy,
                }
            })
            .collect();
        let sensors: Vec<_> = (0..=*self.sensor.iter().max().unwrap())
            .map(|sensor| {
                let r = v[self.dispersion + sensor].exp();
                let gain = if sensor == 0 {
                    1.
                } else {
                    v[self.gains + sensor - 1].exp()
                };
                (r, r.ln(), lgamma(r), digamma(r), gain)
            })
            .collect();
        let boundaries: Vec<_> = self
            .boundary_inputs
            .iter()
            .map(|&(energy, b)| {
                let boundary = (1. + delta / energy) * b / field;
                (boundary, boundary.clamp(0., 1.).sqrt().asin())
            })
            .collect();
        let count_terms: Vec<_> = self
            .count_inputs
            .iter()
            .map(|&(sensor, y)| {
                let r = sensors[sensor].0;
                (lgamma(y + r), digamma(y + r))
            })
            .collect();
        for cell in 0..self.counts.len() {
            jac.fill(0.);
            let width = self.upper[cell] - self.lower[cell];
            let outgoing = self.affected[cell];
            let (pmean, pdmean) = beam_pitch[self.pitch_groups[cell]];
            let mut integral = 0.;
            for e in 0..self.ne {
                let at = cell * self.ne + e;
                let sb = &self.sb[at * self.ns..(at + 1) * self.ns];
                let ab = &self.ab[at * self.na..(at + 1) * self.na];
                let response = &responses[self.response_groups[at]];
                let (k, full, full_k) = (response.k, response.full, response.full_k);
                let w = self.weights[at] * response.incident;
                let (mut surface, mut surface_k) = (full, full_k);
                if outgoing {
                    surface *= c;
                    surface_k *= c;
                    if self.model > 0 {
                        let energy = self.energy[at] - self.phi;
                        let (boundary, angle) = boundaries[self.boundary_groups[at]];
                        let (trans, trans_k) = if angle <= self.lower[cell] {
                            (full, full_k)
                        } else if angle >= self.upper[cell] {
                            (0., 0.)
                        } else {
                            self.moments(k, angle, self.upper[cell], width)
                        };
                        surface = c * (floor * full + (1. - floor) * trans);
                        surface_k = c * (floor * full_k + (1. - floor) * trans_k);
                        jac[self.contrast.unwrap()] += w * c * floor * (trans - full);
                        if boundary > 0.
                            && boundary < 1.
                            && angle > self.lower[cell]
                            && angle < self.upper[cell]
                        {
                            let db = -(k * (1. - boundary)).exp() * c * (1. - floor)
                                / (2. * (boundary * (1. - boundary)).sqrt() * width);
                            jac[0] -= w * boundary * db;
                            if self.model == 2 {
                                jac[1] += w * db * self.b[cell] / (field * energy);
                            }
                        }
                    }
                    jac[self.baseline] += w * surface;
                    if let (Some(b), Some(start)) = (beam, self.beam) {
                        let distance = response.beam_distance;
                        let eg = response.beam_energy;
                        let addition = eg * pmean;
                        surface += addition;
                        jac[start] += w * addition;
                        jac[start + 1] += w * addition * distance / (b[2] * b[2]);
                        jac[start + 2] += w * addition * (distance / b[2]).powi(2);
                        jac[start + 3] += w * eg * pdmean;
                    }
                }
                integral += w * surface;
                for (i, basis) in sb.iter().enumerate() {
                    jac[self.spectrum + i] += w * surface * basis;
                }
                for (i, basis) in ab.iter().enumerate() {
                    jac[self.anisotropy + i] += w * surface_k * basis;
                }
            }
            let sensor = self.sensor[cell];
            let (r, log_r, gamma_r, digamma_r, gain) = sensors[sensor];
            let factor = self.exposure[cell] * gain;
            let mean = integral * factor;
            if save_mean {
                means.push(mean);
            }
            if !mean.is_finite() || mean <= 0. {
                return (f64::INFINITY, vec![0.; self.np], means);
            }
            let y = self.counts[cell];
            let (gamma_yr, digamma_yr) = count_terms[self.count_groups[cell]];
            nll -= gamma_yr - gamma_r - self.log_factorial[cell]
                + r * (log_r - (r + mean).ln())
                + y * (mean.ln() - (r + mean).ln());
            let dmean = y / mean - (y + r) / (mean + r);
            for (g, j) in grad.iter_mut().zip(&jac) {
                *g -= j * factor * dmean;
            }
            if sensor > 0 {
                grad[self.gains + sensor - 1] -= mean * dmean;
            }
            grad[self.dispersion + sensor] -=
                r * (digamma_yr - digamma_r + log_r + 1. - (r + mean).ln() - (r + y) / (r + mean));
        }
        (nll, grad, means)
    }
}

#[cfg(test)]
mod tests {
    use super::digamma;
    #[test]
    fn special_function_values() {
        assert!((digamma(1.) + 0.577_215_664_901_532_9).abs() < 2e-14);
        assert!((digamma(0.5) + 0.577_215_664_901_532_9 + 2. * 2_f64.ln()).abs() < 2e-14);
    }
}
