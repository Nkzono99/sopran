//! Per-spectrum edge features for spacecraft-potential proxies.
//!
//! ``infer_low_energy_cutoff`` finds the strongest log-signal step inside an
//! energy window of an electron spectrum (``rising`` steps are cold-electron
//! cutoffs on the night side, ``falling`` steps are the photoelectron boundary
//! on the day side). ``infer_ion_energy_peak`` finds the low-energy ion peak
//! used as a diagnostic acceleration proxy. Both work on one energy spectrum
//! per row (looks already summed); Python owns the adoption rules.

use numpy::{IntoPyArray, PyReadonlyArray2, PyUntypedArrayMethods};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[derive(Clone, Copy, Debug)]
pub(crate) struct CutoffConfig {
    pub(crate) edge_min_ev: f64,
    pub(crate) edge_max_ev: f64,
    pub(crate) low_reference_max_ev: f64,
    pub(crate) high_reference_min_ev: f64,
    pub(crate) min_positive_bins: usize,
    pub(crate) min_pair_counts: f64,
    pub(crate) min_edge_contrast_log10: f64,
    pub(crate) min_profile_contrast_log10: f64,
    pub(crate) threshold_fraction: f64,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct CutoffResult {
    pub(crate) fit_success: bool,
    pub(crate) quality: bool,
    pub(crate) fail_code: i16,
    pub(crate) direction_code: i8,
    pub(crate) signal_units_code: u8,
    pub(crate) cutoff_energy_ev: f64,
    pub(crate) edge_low_energy_ev: f64,
    pub(crate) edge_high_energy_ev: f64,
    pub(crate) edge_delta_log10: f64,
    pub(crate) threshold_crossing_energy_ev: f64,
    pub(crate) profile_contrast_log10: f64,
    pub(crate) low_reference_log10_signal: f64,
    pub(crate) high_reference_log10_signal: f64,
    pub(crate) peak_low_energy_ev: f64,
    pub(crate) peak_low_log10_signal: f64,
    pub(crate) n_positive_low_energy_bins: usize,
    pub(crate) low_energy_total_counts: f64,
    pub(crate) total_counts: f64,
    pub(crate) low_energy_counts_fraction: f64,
    pub(crate) quality_score: f64,
    pub(crate) energy_min_ev: f64,
    pub(crate) energy_max_ev: f64,
}

pub(crate) fn infer_low_energy_cutoff_one(
    energy: &[f64],
    counts: &[f64],
    eflux: &[f64],
    config: CutoffConfig,
) -> CutoffResult {
    let use_eflux = eflux.iter().any(|value| value.is_finite() && *value > 0.0);
    let mut edge_pairs: Vec<(f64, f64, f64)> = Vec::new();
    let mut low_reference_values = Vec::new();
    let mut high_reference_values = Vec::new();
    let mut total_counts = 0.0;
    let mut low_counts = 0.0;
    for ((&e, &count), &flux) in energy.iter().zip(counts.iter()).zip(eflux.iter()) {
        let positive_count = if count.is_finite() && count > 0.0 {
            count
        } else {
            0.0
        };
        total_counts += positive_count;
        if e.is_finite() && e <= config.edge_max_ev {
            low_counts += positive_count;
        }
        let signal = if use_eflux { flux } else { count };
        if e.is_finite()
            && e >= config.edge_min_ev
            && e <= config.edge_max_ev
            && signal.is_finite()
            && signal > 0.0
        {
            let y = signal.log10();
            edge_pairs.push((e, positive_count, y));
            if e <= config.low_reference_max_ev {
                low_reference_values.push(y);
            }
            if e >= config.high_reference_min_ev {
                high_reference_values.push(y);
            }
        }
    }
    edge_pairs.sort_by(|left, right| left.0.total_cmp(&right.0));
    let low_fraction = if total_counts > 0.0 {
        low_counts / total_counts
    } else {
        f64::NAN
    };
    let mut output = CutoffResult {
        fit_success: false,
        quality: false,
        fail_code: 0,
        direction_code: 0,
        signal_units_code: u8::from(use_eflux),
        cutoff_energy_ev: f64::NAN,
        edge_low_energy_ev: f64::NAN,
        edge_high_energy_ev: f64::NAN,
        edge_delta_log10: f64::NAN,
        threshold_crossing_energy_ev: f64::NAN,
        profile_contrast_log10: f64::NAN,
        low_reference_log10_signal: f64::NAN,
        high_reference_log10_signal: f64::NAN,
        peak_low_energy_ev: f64::NAN,
        peak_low_log10_signal: f64::NAN,
        n_positive_low_energy_bins: edge_pairs.len(),
        low_energy_total_counts: low_counts,
        total_counts,
        low_energy_counts_fraction: low_fraction,
        quality_score: 0.0,
        energy_min_ev: finite_min(energy),
        energy_max_ev: finite_max(energy),
    };
    if edge_pairs.len() < config.min_positive_bins.max(2) {
        output.fail_code = 1;
        return output;
    }
    let e: Vec<f64> = edge_pairs.iter().map(|(energy, _, _)| *energy).collect();
    let c: Vec<f64> = edge_pairs.iter().map(|(_, count, _)| *count).collect();
    let raw_y: Vec<f64> = edge_pairs.iter().map(|(_, _, y)| *y).collect();
    let y = median_smooth(&raw_y);
    let low_ref = median_finite(&low_reference_values);
    let high_ref = median_finite(&high_reference_values);
    let y_floor = percentile_finite(&y, 20.0);
    let y_ceiling = percentile_finite(&y, 80.0);
    let profile_contrast = if y_floor.is_finite() && y_ceiling.is_finite() {
        y_ceiling - y_floor
    } else {
        f64::NAN
    };
    output.profile_contrast_log10 = profile_contrast;
    output.low_reference_log10_signal = low_ref;
    output.high_reference_log10_signal = high_ref;

    let mut best_pair: Option<(usize, f64)> = None;
    for index in 0..(y.len() - 1) {
        let pair_counts = c[index] + c[index + 1];
        let dy = y[index + 1] - y[index];
        if dy.is_finite() && pair_counts >= config.min_pair_counts {
            match best_pair {
                Some((_, best_dy)) if best_dy.abs() >= dy.abs() => {}
                _ => best_pair = Some((index, dy)),
            }
        }
    }
    let Some((best_index, edge_delta)) = best_pair else {
        output.fail_code = 3;
        return output;
    };
    let direction_code: i8 = if edge_delta > 0.0 { 1 } else { -1 };
    let edge_energy = (e[best_index] * e[best_index + 1]).sqrt();
    let threshold_energy = threshold_crossing_energy(
        &e,
        &y,
        direction_code,
        y_floor,
        y_ceiling,
        config.threshold_fraction,
    );
    if let Some(index) = y
        .iter()
        .enumerate()
        .filter(|(_, value)| value.is_finite())
        .max_by(|(_, a), (_, b)| a.total_cmp(b))
        .map(|(index, _)| index)
    {
        output.peak_low_energy_ev = e[index];
        output.peak_low_log10_signal = y[index];
    }
    let edge_contrast = edge_delta.abs();
    let fit_success = edge_contrast >= config.min_edge_contrast_log10
        && profile_contrast.is_finite()
        && profile_contrast >= config.min_profile_contrast_log10;
    let quality_score = cutoff_quality_score(
        edge_contrast,
        profile_contrast,
        edge_pairs.len(),
        low_fraction,
    );
    let cutoff = if threshold_energy.is_finite() {
        threshold_energy
    } else {
        edge_energy
    };
    output.fit_success = fit_success;
    output.quality = fit_success && quality_score >= 1.0;
    output.fail_code = if fit_success { 0 } else { 4 };
    output.direction_code = direction_code;
    output.cutoff_energy_ev = if fit_success { cutoff } else { f64::NAN };
    output.edge_low_energy_ev = e[best_index];
    output.edge_high_energy_ev = e[best_index + 1];
    output.edge_delta_log10 = edge_delta;
    output.threshold_crossing_energy_ev = threshold_energy;
    output.quality_score = quality_score;
    output
}

fn threshold_crossing_energy(
    energy: &[f64],
    y: &[f64],
    direction_code: i8,
    floor: f64,
    ceiling: f64,
    fraction: f64,
) -> f64 {
    if !(floor.is_finite() && ceiling.is_finite() && ceiling > floor) {
        return f64::NAN;
    }
    let threshold = floor + fraction.clamp(0.05, 0.95) * (ceiling - floor);
    for index in 0..(y.len().saturating_sub(1)) {
        let crosses = if direction_code == 1 {
            y[index] < threshold && y[index + 1] >= threshold
        } else {
            y[index] >= threshold && y[index + 1] < threshold
        };
        if crosses {
            let (y0, y1) = (y[index], y[index + 1]);
            let (e0, e1) = (energy[index], energy[index + 1]);
            if y1 == y0 {
                return (e0 * e1).sqrt();
            }
            let ratio = ((threshold - y0) / (y1 - y0)).clamp(0.0, 1.0);
            return (e0.ln() + ratio * (e1.ln() - e0.ln())).exp();
        }
    }
    f64::NAN
}

fn cutoff_quality_score(
    edge_contrast: f64,
    profile_contrast: f64,
    bins: usize,
    low_fraction: f64,
) -> f64 {
    let contrast_score = edge_contrast.max(0.0) / 0.4;
    let profile_score = if profile_contrast.is_finite() {
        profile_contrast.max(0.0) / 0.6
    } else {
        0.0
    };
    let coverage_score = ((bins as f64) / 8.0).max(0.0).sqrt().min(1.5);
    let count_score = if low_fraction.is_finite() && low_fraction > 0.01 {
        1.0
    } else {
        0.5
    };
    0.45 * contrast_score + 0.35 * profile_score + 0.15 * coverage_score + 0.05 * count_score
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct IonPeakConfig {
    pub(crate) min_energy_ev: f64,
    pub(crate) max_energy_ev: f64,
    pub(crate) low_reference_max_ev: f64,
    pub(crate) high_reference_min_ev: f64,
    pub(crate) min_positive_bins: usize,
    pub(crate) min_total_counts: f64,
    pub(crate) min_low_fraction: f64,
    pub(crate) min_profile_contrast_log10: f64,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct IonPeakResult {
    pub(crate) fit_success: bool,
    pub(crate) peak_energy_ev: f64,
    pub(crate) profile_contrast_log10: f64,
    pub(crate) low_energy_counts_fraction: f64,
    pub(crate) total_counts: f64,
    pub(crate) quality_score: f64,
}

pub(crate) fn infer_ion_energy_peak_one(
    energy: &[f64],
    counts: &[f64],
    eflux: &[f64],
    config: IonPeakConfig,
) -> IonPeakResult {
    let mut total_counts = 0.0;
    let mut low_counts = 0.0;
    for (&e, &count) in energy.iter().zip(counts.iter()) {
        let positive = if count.is_finite() && count > 0.0 {
            count
        } else {
            0.0
        };
        total_counts += positive;
        if e.is_finite() && e <= config.max_energy_ev {
            low_counts += positive;
        }
    }
    let low_fraction = if total_counts > 0.0 {
        low_counts / total_counts
    } else {
        f64::NAN
    };
    let mut output = IonPeakResult {
        fit_success: false,
        peak_energy_ev: f64::NAN,
        profile_contrast_log10: f64::NAN,
        low_energy_counts_fraction: low_fraction,
        total_counts,
        quality_score: 0.0,
    };
    if total_counts < config.min_total_counts {
        return output;
    }
    let use_eflux = eflux.iter().any(|value| value.is_finite() && *value > 0.0);
    let mut pairs: Vec<(f64, f64)> = Vec::new();
    for ((&e, &count), &flux) in energy.iter().zip(counts.iter()).zip(eflux.iter()) {
        let signal = if use_eflux { flux } else { count };
        if e.is_finite()
            && e >= config.min_energy_ev
            && e <= config.max_energy_ev
            && signal.is_finite()
            && signal > 0.0
        {
            pairs.push((e, signal.log10()));
        }
    }
    if pairs.len() < config.min_positive_bins.max(1) {
        return output;
    }
    pairs.sort_by(|left, right| left.0.total_cmp(&right.0));
    let energies: Vec<f64> = pairs.iter().map(|(e, _)| *e).collect();
    let raw_y: Vec<f64> = pairs.iter().map(|(_, y)| *y).collect();
    let y = median_smooth(&raw_y);
    let Some((peak_index, _)) = y
        .iter()
        .enumerate()
        .filter(|(_, value)| value.is_finite())
        .max_by(|(_, a), (_, b)| a.total_cmp(b))
    else {
        return output;
    };
    let peak_energy = energies[peak_index];
    let low_ref = median_filtered(&energies, &y, |e| e <= config.low_reference_max_ev);
    let high_ref = median_filtered(&energies, &y, |e| e >= config.high_reference_min_ev);
    let contrast = if low_ref.is_finite() && high_ref.is_finite() {
        low_ref - high_ref
    } else {
        percentile_finite(&y, 80.0) - percentile_finite(&y, 20.0)
    };
    let quality = contrast.max(0.0) + low_fraction.max(0.0) + 0.05 * total_counts.max(1.0).log10();
    let fit_success = peak_energy.is_finite()
        && low_fraction >= config.min_low_fraction
        && contrast >= config.min_profile_contrast_log10;
    output.fit_success = fit_success;
    output.peak_energy_ev = if fit_success { peak_energy } else { f64::NAN };
    output.profile_contrast_log10 = contrast;
    output.quality_score = quality;
    output
}

fn median_smooth(values: &[f64]) -> Vec<f64> {
    if values.len() < 3 {
        return values.to_vec();
    }
    (0..values.len())
        .map(|index| {
            let lo = index.saturating_sub(1);
            let hi = (index + 2).min(values.len());
            median_finite(&values[lo..hi])
        })
        .collect()
}

fn median_filtered(energy: &[f64], values: &[f64], predicate: impl Fn(f64) -> bool) -> f64 {
    let filtered: Vec<f64> = energy
        .iter()
        .zip(values.iter())
        .filter(|(e, _)| predicate(**e))
        .map(|(_, v)| *v)
        .collect();
    median_finite(&filtered)
}

fn median_finite(values: &[f64]) -> f64 {
    let mut finite: Vec<f64> = values.iter().copied().filter(|v| v.is_finite()).collect();
    if finite.is_empty() {
        return f64::NAN;
    }
    finite.sort_by(f64::total_cmp);
    let mid = finite.len() / 2;
    if finite.len() % 2 == 0 {
        0.5 * (finite[mid - 1] + finite[mid])
    } else {
        finite[mid]
    }
}

fn percentile_finite(values: &[f64], percentile: f64) -> f64 {
    let mut finite: Vec<f64> = values.iter().copied().filter(|v| v.is_finite()).collect();
    if finite.is_empty() {
        return f64::NAN;
    }
    finite.sort_by(f64::total_cmp);
    let position = (percentile / 100.0).clamp(0.0, 1.0) * (finite.len() - 1) as f64;
    let lower = position.floor() as usize;
    let upper = position.ceil() as usize;
    let fraction = position - lower as f64;
    finite[lower] + fraction * (finite[upper] - finite[lower])
}

fn finite_min(values: &[f64]) -> f64 {
    values
        .iter()
        .copied()
        .filter(|v| v.is_finite())
        .min_by(f64::total_cmp)
        .unwrap_or(f64::NAN)
}

fn finite_max(values: &[f64]) -> f64 {
    values
        .iter()
        .copied()
        .filter(|v| v.is_finite())
        .max_by(f64::total_cmp)
        .unwrap_or(f64::NAN)
}

fn matrix(values: &PyReadonlyArray2<'_, f64>, name: &str) -> PyResult<(usize, usize, Vec<f64>)> {
    let view = values.as_array();
    if view.ndim() != 2 {
        return Err(PyValueError::new_err(format!(
            "{name} must be two-dimensional"
        )));
    }
    Ok((
        view.shape()[0],
        view.shape()[1],
        view.iter().copied().collect(),
    ))
}

#[allow(clippy::too_many_arguments)]
#[pyfunction]
pub(crate) fn infer_low_energy_cutoff<'py>(
    py: Python<'py>,
    energy_ev: PyReadonlyArray2<'py, f64>,
    counts: PyReadonlyArray2<'py, f64>,
    eflux: PyReadonlyArray2<'py, f64>,
    edge_min_ev: f64,
    edge_max_ev: f64,
    low_reference_max_ev: f64,
    high_reference_min_ev: f64,
    min_positive_bins: usize,
    min_pair_counts: f64,
    min_edge_contrast_log10: f64,
    min_profile_contrast_log10: f64,
    threshold_fraction: f64,
) -> PyResult<Bound<'py, PyDict>> {
    let (rows, cols, energy) = matrix(&energy_ev, "energy_eV")?;
    let (count_rows, count_cols, count_values) = matrix(&counts, "counts")?;
    let (flux_rows, flux_cols, flux_values) = matrix(&eflux, "eflux")?;
    if count_rows != rows || flux_rows != rows || count_cols != cols || flux_cols != cols {
        return Err(PyValueError::new_err(
            "energy_eV, counts and eflux must share one (records, energy) shape",
        ));
    }
    let config = CutoffConfig {
        edge_min_ev,
        edge_max_ev,
        low_reference_max_ev,
        high_reference_min_ev,
        min_positive_bins,
        min_pair_counts,
        min_edge_contrast_log10,
        min_profile_contrast_log10,
        threshold_fraction,
    };
    let results: Vec<CutoffResult> = (0..rows)
        .map(|row| {
            let span = row * cols..(row + 1) * cols;
            infer_low_energy_cutoff_one(
                &energy[span.clone()],
                &count_values[span.clone()],
                &flux_values[span],
                config,
            )
        })
        .collect();
    let output = PyDict::new(py);
    let flags = |f: fn(&CutoffResult) -> bool| -> Vec<u8> {
        results.iter().map(|r| u8::from(f(r))).collect()
    };
    let floats = |f: fn(&CutoffResult) -> f64| -> Vec<f64> { results.iter().map(f).collect() };
    output.set_item("fit_success", flags(|r| r.fit_success).into_pyarray(py))?;
    output.set_item("quality", flags(|r| r.quality).into_pyarray(py))?;
    output.set_item(
        "fail_code",
        results
            .iter()
            .map(|r| r.fail_code)
            .collect::<Vec<i16>>()
            .into_pyarray(py),
    )?;
    output.set_item(
        "direction_code",
        results
            .iter()
            .map(|r| r.direction_code)
            .collect::<Vec<i8>>()
            .into_pyarray(py),
    )?;
    output.set_item(
        "signal_units_code",
        results
            .iter()
            .map(|r| r.signal_units_code)
            .collect::<Vec<u8>>()
            .into_pyarray(py),
    )?;
    output.set_item(
        "cutoff_energy_eV",
        floats(|r| r.cutoff_energy_ev).into_pyarray(py),
    )?;
    output.set_item(
        "edge_low_energy_eV",
        floats(|r| r.edge_low_energy_ev).into_pyarray(py),
    )?;
    output.set_item(
        "edge_high_energy_eV",
        floats(|r| r.edge_high_energy_ev).into_pyarray(py),
    )?;
    output.set_item(
        "edge_delta_log10",
        floats(|r| r.edge_delta_log10).into_pyarray(py),
    )?;
    output.set_item(
        "threshold_crossing_energy_eV",
        floats(|r| r.threshold_crossing_energy_ev).into_pyarray(py),
    )?;
    output.set_item(
        "profile_contrast_log10",
        floats(|r| r.profile_contrast_log10).into_pyarray(py),
    )?;
    output.set_item(
        "low_reference_log10_signal",
        floats(|r| r.low_reference_log10_signal).into_pyarray(py),
    )?;
    output.set_item(
        "high_reference_log10_signal",
        floats(|r| r.high_reference_log10_signal).into_pyarray(py),
    )?;
    output.set_item(
        "peak_low_energy_eV",
        floats(|r| r.peak_low_energy_ev).into_pyarray(py),
    )?;
    output.set_item(
        "peak_low_log10_signal",
        floats(|r| r.peak_low_log10_signal).into_pyarray(py),
    )?;
    output.set_item(
        "n_positive_low_energy_bins",
        results
            .iter()
            .map(|r| r.n_positive_low_energy_bins as i64)
            .collect::<Vec<i64>>()
            .into_pyarray(py),
    )?;
    output.set_item(
        "low_energy_total_counts",
        floats(|r| r.low_energy_total_counts).into_pyarray(py),
    )?;
    output.set_item("total_counts", floats(|r| r.total_counts).into_pyarray(py))?;
    output.set_item(
        "low_energy_counts_fraction",
        floats(|r| r.low_energy_counts_fraction).into_pyarray(py),
    )?;
    output.set_item(
        "quality_score",
        floats(|r| r.quality_score).into_pyarray(py),
    )?;
    output.set_item(
        "energy_min_eV",
        floats(|r| r.energy_min_ev).into_pyarray(py),
    )?;
    output.set_item(
        "energy_max_eV",
        floats(|r| r.energy_max_ev).into_pyarray(py),
    )?;
    Ok(output)
}

#[allow(clippy::too_many_arguments)]
#[pyfunction]
pub(crate) fn infer_ion_energy_peak<'py>(
    py: Python<'py>,
    energy_ev: PyReadonlyArray2<'py, f64>,
    counts: PyReadonlyArray2<'py, f64>,
    eflux: PyReadonlyArray2<'py, f64>,
    min_energy_ev: f64,
    max_energy_ev: f64,
    low_reference_max_ev: f64,
    high_reference_min_ev: f64,
    min_positive_bins: usize,
    min_total_counts: f64,
    min_low_fraction: f64,
    min_profile_contrast_log10: f64,
) -> PyResult<Bound<'py, PyDict>> {
    let (rows, cols, energy) = matrix(&energy_ev, "energy_eV")?;
    let (count_rows, count_cols, count_values) = matrix(&counts, "counts")?;
    let (flux_rows, flux_cols, flux_values) = matrix(&eflux, "eflux")?;
    if count_rows != rows || flux_rows != rows || count_cols != cols || flux_cols != cols {
        return Err(PyValueError::new_err(
            "energy_eV, counts and eflux must share one (records, energy) shape",
        ));
    }
    let config = IonPeakConfig {
        min_energy_ev,
        max_energy_ev,
        low_reference_max_ev,
        high_reference_min_ev,
        min_positive_bins,
        min_total_counts,
        min_low_fraction,
        min_profile_contrast_log10,
    };
    let results: Vec<IonPeakResult> = (0..rows)
        .map(|row| {
            let span = row * cols..(row + 1) * cols;
            infer_ion_energy_peak_one(
                &energy[span.clone()],
                &count_values[span.clone()],
                &flux_values[span],
                config,
            )
        })
        .collect();
    let output = PyDict::new(py);
    let floats = |f: fn(&IonPeakResult) -> f64| -> Vec<f64> { results.iter().map(f).collect() };
    output.set_item(
        "fit_success",
        results
            .iter()
            .map(|r| u8::from(r.fit_success))
            .collect::<Vec<u8>>()
            .into_pyarray(py),
    )?;
    output.set_item(
        "peak_energy_eV",
        floats(|r| r.peak_energy_ev).into_pyarray(py),
    )?;
    output.set_item(
        "profile_contrast_log10",
        floats(|r| r.profile_contrast_log10).into_pyarray(py),
    )?;
    output.set_item(
        "low_energy_counts_fraction",
        floats(|r| r.low_energy_counts_fraction).into_pyarray(py),
    )?;
    output.set_item("total_counts", floats(|r| r.total_counts).into_pyarray(py))?;
    output.set_item(
        "quality_score",
        floats(|r| r.quality_score).into_pyarray(py),
    )?;
    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cutoff_config() -> CutoffConfig {
        CutoffConfig {
            edge_min_ev: 5.0,
            edge_max_ev: 350.0,
            low_reference_max_ev: 30.0,
            high_reference_min_ev: 80.0,
            min_positive_bins: 5,
            min_pair_counts: 2.0,
            min_edge_contrast_log10: 0.25,
            min_profile_contrast_log10: 0.35,
            threshold_fraction: 0.5,
        }
    }

    #[test]
    fn rising_step_is_a_cutoff_candidate() {
        let energy: Vec<f64> = (0..12).map(|i| 8.0 * 1.4_f64.powi(i)).collect();
        let counts: Vec<f64> = energy
            .iter()
            .map(|e| if *e < 40.0 { 2.0 } else { 400.0 })
            .collect();
        let eflux = vec![f64::NAN; energy.len()];
        let result = infer_low_energy_cutoff_one(&energy, &counts, &eflux, cutoff_config());
        assert!(result.fit_success);
        assert_eq!(result.direction_code, 1);
        assert!(result.cutoff_energy_ev > 20.0 && result.cutoff_energy_ev < 80.0);
        assert_eq!(result.signal_units_code, 0);
    }

    #[test]
    fn flat_spectrum_has_no_edge() {
        let energy: Vec<f64> = (0..12).map(|i| 8.0 * 1.4_f64.powi(i)).collect();
        let counts = vec![100.0; energy.len()];
        let eflux = vec![f64::NAN; energy.len()];
        let result = infer_low_energy_cutoff_one(&energy, &counts, &eflux, cutoff_config());
        assert!(!result.fit_success);
        assert_eq!(result.fail_code, 4);
    }

    #[test]
    fn low_energy_ion_peak_is_found() {
        let energy: Vec<f64> = (0..16).map(|i| 5.0 * 1.4_f64.powi(i)).collect();
        let counts: Vec<f64> = energy
            .iter()
            .map(|e| 50.0 * (-((e.ln() - 40.0_f64.ln()) / 0.8).powi(2)).exp() + 0.5)
            .collect();
        let eflux = vec![f64::NAN; energy.len()];
        let config = IonPeakConfig {
            min_energy_ev: 5.0,
            max_energy_ev: 1000.0,
            low_reference_max_ev: 120.0,
            high_reference_min_ev: 400.0,
            min_positive_bins: 3,
            min_total_counts: 20.0,
            min_low_fraction: 0.35,
            min_profile_contrast_log10: 0.25,
        };
        let result = infer_ion_energy_peak_one(&energy, &counts, &eflux, config);
        assert!(result.fit_success);
        assert!((result.peak_energy_ev - 40.0).abs() < 15.0);
        assert!(result.profile_contrast_log10 > 1.0);
    }
}
