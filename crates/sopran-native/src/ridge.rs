//! Standardized ridge regression, grouped cross-validation and the empirical
//! external-gain correction used by ER environment-response models.
//!
//! Features are standardized per column with the training rows; the intercept
//! is not penalized. Python passes dense row-major matrices once per fit.

use numpy::{IntoPyArray, PyReadonlyArray1, PyReadonlyArray2, PyUntypedArrayMethods};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[derive(Clone, Debug)]
pub(crate) struct RidgeModel {
    pub(crate) coefficients: Vec<f64>,
    pub(crate) means: Vec<f64>,
    pub(crate) scales: Vec<f64>,
}

#[derive(Clone, Debug)]
pub(crate) struct RidgePrediction {
    pub(crate) prediction: Vec<f64>,
    pub(crate) model: RidgeModel,
}

pub(crate) fn ridge_fit_predict_dense(
    x: &[f64],
    rows: usize,
    cols: usize,
    target: &[f64],
    alpha: f64,
) -> Result<RidgePrediction, String> {
    let train_rows: Vec<usize> = (0..rows).collect();
    let model = fit_ridge_model_rows(x, rows, cols, target, &train_rows, alpha)?;
    let prediction = predict_ridge_rows(x, cols, &train_rows, &model);
    Ok(RidgePrediction { prediction, model })
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn grouped_ridge_cv_predictions_dense(
    x: &[f64],
    rows: usize,
    cols: usize,
    target: &[f64],
    groups: Option<&[i64]>,
    alpha: f64,
    folds: usize,
    seed: u64,
) -> Result<Vec<f64>, String> {
    if rows == 0 || cols == 0 || target.len() != rows || x.len() != rows * cols {
        return Err("features must be (rows, cols) with one target per row".to_string());
    }
    if let Some(groups) = groups {
        if groups.len() != rows {
            return Err("groups must have one value per row".to_string());
        }
    }
    let fold_count = folds.max(2);
    let test_splits = match groups {
        Some(groups) => build_group_test_splits(groups, fold_count, seed),
        None => build_row_test_splits(rows, fold_count, seed),
    };
    let mut prediction = vec![f64::NAN; rows];
    for test_rows in test_splits {
        if test_rows.is_empty() {
            continue;
        }
        let mut is_test = vec![false; rows];
        for &row in &test_rows {
            is_test[row] = true;
        }
        let train_rows: Vec<usize> = (0..rows).filter(|row| !is_test[*row]).collect();
        if train_rows.is_empty() {
            continue;
        }
        let model = fit_ridge_model_rows(x, rows, cols, target, &train_rows, alpha)?;
        let test_prediction = predict_ridge_rows(x, cols, &test_rows, &model);
        for (row, value) in test_rows.iter().copied().zip(test_prediction) {
            prediction[row] = value;
        }
    }
    Ok(prediction)
}

fn fit_ridge_model_rows(
    x: &[f64],
    rows: usize,
    cols: usize,
    target: &[f64],
    train_rows: &[usize],
    alpha: f64,
) -> Result<RidgeModel, String> {
    if rows == 0
        || cols == 0
        || train_rows.is_empty()
        || target.len() != rows
        || x.len() != rows * cols
    {
        return Err("features must be (rows, cols) with one target per row".to_string());
    }
    if !alpha.is_finite() || alpha < 0.0 {
        return Err("alpha must be finite and non-negative".to_string());
    }
    let mut means = vec![0.0; cols];
    let mut scales = vec![0.0; cols];
    for &row in train_rows {
        if row >= rows || !target[row].is_finite() {
            return Err("target must be finite on training rows".to_string());
        }
        for col in 0..cols {
            let value = x[row * cols + col];
            if !value.is_finite() {
                return Err("features must be finite on training rows".to_string());
            }
            means[col] += value;
        }
    }
    let inv_n = 1.0 / train_rows.len() as f64;
    for mean in &mut means {
        *mean *= inv_n;
    }
    for &row in train_rows {
        for col in 0..cols {
            let diff = x[row * cols + col] - means[col];
            scales[col] += diff * diff;
        }
    }
    for scale in &mut scales {
        *scale = (*scale * inv_n).sqrt();
        if *scale <= 0.0 || !scale.is_finite() {
            *scale = 1.0;
        }
    }
    let dim = cols + 1;
    let mut xtx = vec![0.0; dim * dim];
    let mut xty = vec![0.0; dim];
    for &row in train_rows {
        let y = target[row];
        xtx[0] += 1.0;
        xty[0] += y;
        for col in 0..cols {
            let xi = standardized_value(x, cols, row, col, &means, &scales);
            let i = col + 1;
            xtx[i] += xi;
            xtx[i * dim] += xi;
            xty[i] += xi * y;
            for col2 in col..cols {
                let xj = standardized_value(x, cols, row, col2, &means, &scales);
                let j = col2 + 1;
                xtx[i * dim + j] += xi * xj;
            }
        }
    }
    for i in 1..dim {
        for j in 1..i {
            xtx[i * dim + j] = xtx[j * dim + i];
        }
        xtx[i * dim + i] += alpha;
    }
    let coefficients = solve_linear_system(xtx, xty, dim)
        .ok_or_else(|| "ridge normal equations are singular".to_string())?;
    Ok(RidgeModel {
        coefficients,
        means,
        scales,
    })
}

fn predict_ridge_rows(
    x: &[f64],
    cols: usize,
    row_indices: &[usize],
    model: &RidgeModel,
) -> Vec<f64> {
    row_indices
        .iter()
        .map(|&row| {
            let mut value = model.coefficients[0];
            for col in 0..cols {
                value += model.coefficients[col + 1]
                    * standardized_value(x, cols, row, col, &model.means, &model.scales);
            }
            value
        })
        .collect()
}

fn standardized_value(
    x: &[f64],
    cols: usize,
    row: usize,
    col: usize,
    means: &[f64],
    scales: &[f64],
) -> f64 {
    (x[row * cols + col] - means[col]) / scales[col]
}

fn build_row_test_splits(rows: usize, folds: usize, seed: u64) -> Vec<Vec<usize>> {
    let mut indices: Vec<usize> = (0..rows).collect();
    shuffle_slice(&mut indices, seed);
    (0..folds)
        .map(|fold| indices.iter().skip(fold).step_by(folds).copied().collect())
        .collect()
}

fn build_group_test_splits(groups: &[i64], folds: usize, seed: u64) -> Vec<Vec<usize>> {
    let mut unique_groups = groups.to_vec();
    unique_groups.sort_unstable();
    unique_groups.dedup();
    shuffle_slice(&mut unique_groups, seed);
    (0..folds)
        .map(|fold| {
            let mut selected: Vec<i64> = unique_groups
                .iter()
                .skip(fold)
                .step_by(folds)
                .copied()
                .collect();
            selected.sort_unstable();
            groups
                .iter()
                .enumerate()
                .filter_map(|(row, group)| selected.binary_search(group).ok().map(|_| row))
                .collect()
        })
        .collect()
}

fn shuffle_slice<T>(values: &mut [T], seed: u64) {
    if values.len() < 2 {
        return;
    }
    let mut rng = SplitMix64::new(seed);
    for index in (1..values.len()).rev() {
        let swap_index = (rng.next_u64() as usize) % (index + 1);
        values.swap(index, swap_index);
    }
}

struct SplitMix64 {
    state: u64,
}

impl SplitMix64 {
    fn new(seed: u64) -> Self {
        Self {
            state: seed.wrapping_add(0x9E37_79B9_7F4A_7C15),
        }
    }

    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
}

fn solve_linear_system(mut a: Vec<f64>, mut b: Vec<f64>, n: usize) -> Option<Vec<f64>> {
    for pivot in 0..n {
        let mut best = pivot;
        let mut best_abs = a[pivot * n + pivot].abs();
        for row in pivot + 1..n {
            let value = a[row * n + pivot].abs();
            if value > best_abs {
                best = row;
                best_abs = value;
            }
        }
        if best_abs <= 1.0e-12 || !best_abs.is_finite() {
            return None;
        }
        if best != pivot {
            for col in pivot..n {
                a.swap(pivot * n + col, best * n + col);
            }
            b.swap(pivot, best);
        }
        let pivot_value = a[pivot * n + pivot];
        for row in pivot + 1..n {
            let factor = a[row * n + pivot] / pivot_value;
            a[row * n + pivot] = 0.0;
            for col in pivot + 1..n {
                a[row * n + col] -= factor * a[pivot * n + col];
            }
            b[row] -= factor * b[pivot];
        }
    }
    let mut x = vec![0.0; n];
    for row in (0..n).rev() {
        let mut sum = b[row];
        for col in row + 1..n {
            sum -= a[row * n + col] * x[col];
        }
        let diag = a[row * n + row];
        if diag.abs() <= 1.0e-12 || !diag.is_finite() {
            return None;
        }
        x[row] = sum / diag;
    }
    Some(x)
}

pub(crate) fn r2_score(target: &[f64], prediction: &[f64]) -> f64 {
    let mean_y = mean(target);
    let mut ss_tot = 0.0;
    let mut ss_res = 0.0;
    for (y, pred) in target.iter().zip(prediction.iter()) {
        ss_tot += (y - mean_y) * (y - mean_y);
        ss_res += (y - pred) * (y - pred);
    }
    if ss_tot <= 0.0 {
        f64::NAN
    } else {
        1.0 - ss_res / ss_tot
    }
}

fn mean(values: &[f64]) -> f64 {
    if values.is_empty() {
        return f64::NAN;
    }
    values.iter().sum::<f64>() / values.len() as f64
}

fn dense_matrix(
    values: &PyReadonlyArray2<'_, f64>,
    name: &str,
) -> PyResult<(usize, usize, Vec<f64>)> {
    let view = values.as_array();
    if view.ndim() != 2 {
        return Err(PyValueError::new_err(format!(
            "{name} must be two-dimensional"
        )));
    }
    let rows = view.shape()[0];
    let cols = view.shape()[1];
    Ok((rows, cols, view.iter().copied().collect()))
}

#[pyfunction]
pub(crate) fn ridge_fit_predict<'py>(
    py: Python<'py>,
    features: PyReadonlyArray2<'py, f64>,
    target: PyReadonlyArray1<'py, f64>,
    alpha: f64,
) -> PyResult<Bound<'py, PyDict>> {
    let (rows, cols, x) = dense_matrix(&features, "features")?;
    let y = target.as_slice()?.to_vec();
    if y.len() != rows {
        return Err(PyValueError::new_err(
            "target must have one value per feature row",
        ));
    }
    let fit = ridge_fit_predict_dense(&x, rows, cols, &y, alpha).map_err(PyValueError::new_err)?;
    let output = PyDict::new(py);
    output.set_item("prediction", fit.prediction.into_pyarray(py))?;
    output.set_item("coefficients", fit.model.coefficients.into_pyarray(py))?;
    output.set_item("means", fit.model.means.into_pyarray(py))?;
    output.set_item("scales", fit.model.scales.into_pyarray(py))?;
    Ok(output)
}

#[pyfunction]
pub(crate) fn grouped_ridge_cv_predictions<'py>(
    py: Python<'py>,
    features: PyReadonlyArray2<'py, f64>,
    target: PyReadonlyArray1<'py, f64>,
    groups: Option<PyReadonlyArray1<'py, i64>>,
    alpha: f64,
    folds: usize,
    seed: u64,
) -> PyResult<Bound<'py, numpy::PyArray1<f64>>> {
    let (rows, cols, x) = dense_matrix(&features, "features")?;
    let y = target.as_slice()?.to_vec();
    if y.len() != rows {
        return Err(PyValueError::new_err(
            "target must have one value per feature row",
        ));
    }
    let group_values = match &groups {
        Some(values) => Some(values.as_slice()?.to_vec()),
        None => None,
    };
    let prediction = py
        .detach(move || {
            grouped_ridge_cv_predictions_dense(
                &x,
                rows,
                cols,
                &y,
                group_values.as_deref(),
                alpha,
                folds,
                seed,
            )
        })
        .map_err(PyValueError::new_err)?;
    Ok(prediction.into_pyarray(py))
}

/// Fit base and physical ridge models to ``log(target)`` and return the
/// empirical external gain ``exp(pred_physical - pred_base)`` together with the
/// environment-corrected field ``max(exp(y - log_gain) - eps, 0)``.
#[pyfunction]
pub(crate) fn ridge_external_gain<'py>(
    py: Python<'py>,
    base_features: PyReadonlyArray2<'py, f64>,
    physical_features: PyReadonlyArray2<'py, f64>,
    target: PyReadonlyArray1<'py, f64>,
    alpha: f64,
    eps_nt: f64,
) -> PyResult<Bound<'py, PyDict>> {
    let (rows, base_cols, base_x) = dense_matrix(&base_features, "base_features")?;
    let (physical_rows, physical_cols, physical_x) =
        dense_matrix(&physical_features, "physical_features")?;
    let y = target.as_slice()?.to_vec();
    if physical_rows != rows || y.len() != rows {
        return Err(PyValueError::new_err(
            "base_features, physical_features and target must share one row count",
        ));
    }
    if !y.iter().all(|value| value.is_finite()) {
        return Err(PyValueError::new_err("target must be finite"));
    }
    let base_fit = ridge_fit_predict_dense(&base_x, rows, base_cols, &y, alpha)
        .map_err(PyValueError::new_err)?;
    let physical_fit = ridge_fit_predict_dense(&physical_x, rows, physical_cols, &y, alpha)
        .map_err(PyValueError::new_err)?;
    let mut gain = Vec::with_capacity(rows);
    let mut corrected = Vec::with_capacity(rows);
    for row in 0..rows {
        let log_gain = physical_fit.prediction[row] - base_fit.prediction[row];
        gain.push(log_gain.exp());
        corrected.push(((y[row] - log_gain).exp() - eps_nt).max(0.0));
    }
    let output = PyDict::new(py);
    output.set_item("base_r2", r2_score(&y, &base_fit.prediction))?;
    output.set_item("physical_r2", r2_score(&y, &physical_fit.prediction))?;
    output.set_item("mean_external_gain", mean(&gain))?;
    output.set_item("base_prediction", base_fit.prediction.into_pyarray(py))?;
    output.set_item(
        "physical_prediction",
        physical_fit.prediction.into_pyarray(py),
    )?;
    output.set_item("external_gain", gain.into_pyarray(py))?;
    output.set_item("corrected", corrected.into_pyarray(py))?;
    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ridge_fit_predict_dense_recovers_linear_signal() {
        let rows = 32usize;
        let cols = 2usize;
        let mut x = Vec::with_capacity(rows * cols);
        let mut target = Vec::with_capacity(rows);
        for row in 0..rows {
            let x0 = row as f64 / 10.0;
            let x1 = (row % 5) as f64 - 2.0;
            x.push(x0);
            x.push(x1);
            target.push(1.5 + 2.0 * x0 - 0.25 * x1);
        }
        let fit = ridge_fit_predict_dense(&x, rows, cols, &target, 1.0e-6).unwrap();
        assert_eq!(fit.prediction.len(), rows);
        assert_eq!(fit.model.coefficients.len(), cols + 1);
        assert!(r2_score(&target, &fit.prediction) > 0.999);
    }

    #[test]
    fn grouped_cv_keeps_groups_together_and_predicts_linear_signal() {
        let rows = 40usize;
        let mut x = Vec::with_capacity(rows);
        let mut target = Vec::with_capacity(rows);
        let mut groups = Vec::with_capacity(rows);
        for row in 0..rows {
            let value = row as f64 / 39.0;
            x.push(value);
            target.push(0.5 + 1.75 * value);
            groups.push((row / 2) as i64);
        }
        let prediction =
            grouped_ridge_cv_predictions_dense(&x, rows, 1, &target, Some(&groups), 1.0e-6, 5, 7)
                .unwrap();
        assert!(prediction.iter().all(|value| value.is_finite()));
        assert!(r2_score(&target, &prediction) > 0.98);
        let splits = build_group_test_splits(&groups, 5, 7);
        for split in splits {
            for pair in split.chunks(2) {
                assert_eq!(pair.len(), 2);
                assert_eq!(groups[pair[0]], groups[pair[1]]);
            }
        }
    }

    #[test]
    fn singular_design_is_reported() {
        let x = vec![1.0, 1.0, 1.0, 1.0];
        let target = vec![1.0, 2.0];
        assert!(ridge_fit_predict_dense(&x, 2, 2, &target, 0.0).is_err());
    }
}
