//! Connected-component extraction of closed-field islands on a lon/lat grid.
//!
//! Thresholded "closed-like" cells are grouped with four-neighbour
//! connectivity and longitude wraparound. Python owns the thresholds, the
//! product I/O and the plotting.

use numpy::{IntoPyArray, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::VecDeque;

#[derive(Debug, Clone)]
pub(crate) struct ClosedIslandResult {
    pub(crate) strong_closed_island: Vec<u8>,
    pub(crate) island_id: Vec<i64>,
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn classify_closed_islands(
    lon_deg: &[f64],
    lat_deg: &[f64],
    closed_like: &[u8],
    path_max_nt: &[f64],
    footpoint_separation_deg: &[f64],
    min_path_max_nt: f64,
    min_footpoint_separation_deg: f64,
    min_cells: usize,
) -> Result<ClosedIslandResult, String> {
    let rows = lon_deg.len();
    if lat_deg.len() != rows
        || closed_like.len() != rows
        || path_max_nt.len() != rows
        || footpoint_separation_deg.len() != rows
    {
        return Err("all input vectors must have the same length".to_string());
    }
    if rows == 0 {
        return Ok(ClosedIslandResult {
            strong_closed_island: Vec::new(),
            island_id: Vec::new(),
        });
    }
    if !min_path_max_nt.is_finite() || !min_footpoint_separation_deg.is_finite() {
        return Err("thresholds must be finite".to_string());
    }
    if min_cells == 0 {
        return Err("min_cells must be positive".to_string());
    }
    let lon_values = sorted_unique_finite(lon_deg)?;
    let lat_values = sorted_unique_finite(lat_deg)?;
    if lon_values.len() * lat_values.len() != rows {
        return Err("lon/lat inputs must form a complete rectangular grid".to_string());
    }
    let lon_count = lon_values.len();
    let lat_count = lat_values.len();
    let mut mask = vec![false; rows];
    let mut row_lookup = vec![usize::MAX; rows];
    for row in 0..rows {
        let lon_idx = binary_find(&lon_values, lon_deg[row])
            .ok_or_else(|| "failed to index longitude in regular grid".to_string())?;
        let lat_idx = binary_find(&lat_values, lat_deg[row])
            .ok_or_else(|| "failed to index latitude in regular grid".to_string())?;
        let grid_idx = lat_idx * lon_count + lon_idx;
        row_lookup[grid_idx] = row;
        mask[grid_idx] = closed_like[row] != 0
            && path_max_nt[row].is_finite()
            && footpoint_separation_deg[row].is_finite()
            && path_max_nt[row] >= min_path_max_nt
            && footpoint_separation_deg[row] >= min_footpoint_separation_deg;
    }
    if row_lookup.iter().any(|value| *value == usize::MAX) {
        return Err("lon/lat grid has duplicate or missing cells".to_string());
    }
    let mut strong = vec![0u8; rows];
    let mut island_id = vec![-1i64; rows];
    let mut visited = vec![false; rows];
    let mut next_id: i64 = 0;
    for start in 0..rows {
        if !mask[start] || visited[start] {
            continue;
        }
        let component = flood_component(start, lon_count, lat_count, &mask, &mut visited);
        if component.len() < min_cells {
            continue;
        }
        for grid_idx in component {
            let row = row_lookup[grid_idx];
            strong[row] = 1;
            island_id[row] = next_id;
        }
        next_id += 1;
    }
    Ok(ClosedIslandResult {
        strong_closed_island: strong,
        island_id,
    })
}

fn flood_component(
    start: usize,
    lon_count: usize,
    lat_count: usize,
    mask: &[bool],
    visited: &mut [bool],
) -> Vec<usize> {
    let mut queue = VecDeque::from([start]);
    visited[start] = true;
    let mut out = Vec::new();
    while let Some(idx) = queue.pop_front() {
        out.push(idx);
        let j = idx / lon_count;
        let i = idx % lon_count;
        let neighbours = [
            (j.checked_sub(1), Some(i)),
            ((j + 1 < lat_count).then_some(j + 1), Some(i)),
            (Some(j), Some((i + lon_count - 1) % lon_count)),
            (Some(j), Some((i + 1) % lon_count)),
        ];
        for (nj, ni) in neighbours {
            let (Some(nj), Some(ni)) = (nj, ni) else {
                continue;
            };
            let nidx = nj * lon_count + ni;
            if !mask[nidx] || visited[nidx] {
                continue;
            }
            visited[nidx] = true;
            queue.push_back(nidx);
        }
    }
    out
}

fn sorted_unique_finite(values: &[f64]) -> Result<Vec<f64>, String> {
    let mut out = values.to_vec();
    if out.iter().any(|value| !value.is_finite()) {
        return Err("lon/lat arrays must be finite".to_string());
    }
    out.sort_by(|a, b| a.total_cmp(b));
    out.dedup_by(|a, b| (*a - *b).abs() < 1.0e-9);
    Ok(out)
}

fn binary_find(values: &[f64], target: f64) -> Option<usize> {
    values
        .binary_search_by(|probe| probe.total_cmp(&target))
        .ok()
}

#[allow(clippy::too_many_arguments)]
#[pyfunction]
pub(crate) fn classify_closed_islands_batch<'py>(
    py: Python<'py>,
    lon_deg: PyReadonlyArray1<'py, f64>,
    lat_deg: PyReadonlyArray1<'py, f64>,
    closed_like: PyReadonlyArray1<'py, u8>,
    path_max_nt: PyReadonlyArray1<'py, f64>,
    footpoint_separation_deg: PyReadonlyArray1<'py, f64>,
    min_path_max_nt: f64,
    min_footpoint_separation_deg: f64,
    min_cells: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let result = classify_closed_islands(
        lon_deg.as_slice()?,
        lat_deg.as_slice()?,
        closed_like.as_slice()?,
        path_max_nt.as_slice()?,
        footpoint_separation_deg.as_slice()?,
        min_path_max_nt,
        min_footpoint_separation_deg,
        min_cells,
    )
    .map_err(PyValueError::new_err)?;
    let output = PyDict::new(py);
    output.set_item(
        "strong_closed_island",
        result.strong_closed_island.into_pyarray(py),
    )?;
    output.set_item("island_id", result.island_id.into_pyarray(py))?;
    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::classify_closed_islands;

    #[test]
    fn thresholds_apply_and_longitude_wraps() {
        let lon = vec![-1.0, 1.0, -1.0, 1.0];
        let lat = vec![0.0, 0.0, 2.0, 2.0];
        let closed = vec![1u8, 1, 0, 1];
        let path_max = vec![12.0, 14.0, 30.0, 13.0];
        let sep = vec![6.0, 7.0, 8.0, 2.0];
        let result =
            classify_closed_islands(&lon, &lat, &closed, &path_max, &sep, 10.0, 5.0, 1).unwrap();
        assert_eq!(result.strong_closed_island, vec![1, 1, 0, 0]);
        assert_eq!(result.island_id, vec![0, 0, -1, -1]);
    }

    #[test]
    fn small_components_are_dropped() {
        let lon = vec![-2.0, 0.0, 2.0, -2.0, 0.0, 2.0, -2.0, 0.0, 2.0];
        let lat = vec![-2.0, -2.0, -2.0, 0.0, 0.0, 0.0, 2.0, 2.0, 2.0];
        let closed = vec![1u8, 0, 0, 0, 0, 0, 0, 0, 1];
        let path_max = vec![12.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 13.0];
        let sep = vec![6.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 7.0];
        let result =
            classify_closed_islands(&lon, &lat, &closed, &path_max, &sep, 10.0, 5.0, 2).unwrap();
        assert!(result.strong_closed_island.iter().all(|v| *v == 0));
        assert!(result.island_id.iter().all(|v| *v == -1));
    }
}
