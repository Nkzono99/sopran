//! Folded finite-bin reflection followed by conservative D_out and bin response.
//! Port of the validated angle-transport pilot; all search iterations stay in Rust.
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

struct Config {
    pitch: Vec<f64>,
    fine: Vec<f64>,
    weights: Vec<f64>,
    eigenvalues: Vec<f64>,
    eigenvectors: Vec<f64>,
    eigenvector_columns: Vec<f64>,
    weight_ratios: Vec<f64>,
    pitch_sin2: Vec<f64>,
    angular_beams: Vec<Vec<f64>>,
    nodes: Vec<f64>,
    node_weights: Vec<f64>,
    node_extrema: [f64; 2],
    subdivisions: usize,
    beam_enabled: bool,
    huber_delta: f64,
}
struct Event {
    low: Vec<f64>,
    high: Vec<f64>,
    reference: Vec<Vec<f64>>,
    mask: Vec<Vec<bool>>,
    observed: Vec<Vec<f64>>,
}
struct Evaluation {
    cost: f64,
    template: usize,
    prediction: Vec<f64>,
}
struct FitResult {
    x: [f64; 5],
    cost: f64,
    template: usize,
    prediction: Vec<f64>,
    evaluations: usize,
    converged: bool,
}

impl Config {
    fn barrier_unobserved(&self, event: &Event, x: [f64; 5]) -> bool {
        let mut all_zero = true;
        let mut all_one = true;
        for row in 0..event.low.len() {
            let probability = self.probability(
                event.low[row],
                event.high[row],
                10_f64.powf(x[0]),
                x[2] * 500.,
            );
            if x[4] == 0. {
                for (target, chunk) in probability.chunks(self.subdivisions).enumerate() {
                    if event.mask[row][target] {
                        let mean = chunk.iter().sum::<f64>() / self.subdivisions as f64;
                        all_zero &= mean < 1e-12;
                        all_one &= mean > 1. - 1e-12;
                    }
                }
            } else {
                all_zero &= probability.iter().all(|p| *p < 1e-12);
                all_one &= probability.iter().all(|p| *p > 1. - 1e-12);
            }
        }
        all_zero || all_one
    }
    /// Projection of integrated input intensity into averaged detector bins.
    /// Construct/roundoff-correct the same column-stochastic D as Python.
    fn projection(&self, sigma: f64) -> Vec<f64> {
        let n = self.weights.len();
        let p = self.pitch.len() - 1;
        let mut q = vec![0.; n * p];
        if sigma == 0. {
            for j in 0..n {
                q[j * p + j / self.subdivisions] =
                    1. / (self.weights[j] * self.subdivisions as f64);
            }
            return q;
        }
        let t = sigma.to_radians().powi(2) / 4.;
        let decay: Vec<f64> = self.eigenvalues.iter().map(|v| (v * t).exp()).collect();
        let first = decay.iter().position(|v| *v > 0.).unwrap_or(n - 1);
        // Each output accumulates k in the original order. Updating independent
        // columns together permits SIMD without reordering the floating sums.
        // The heat matrix is symmetric; compute only its upper triangle.
        let mut heat = vec![0.; n * n];
        for (i, row) in heat.chunks_exact_mut(n).enumerate() {
            for (k, &factor) in decay.iter().enumerate().skip(first) {
                let vi = self.eigenvectors[i * n + k];
                let column = &self.eigenvector_columns[k * n + i..(k + 1) * n];
                for (value, &vj) in row[i..].iter_mut().zip(column) {
                    *value += (vi * vj) * factor;
                }
            }
        }
        let mut column = vec![0.; n];
        for j in 0..n {
            for (i, value) in column.iter_mut().enumerate() {
                let h = heat[i.min(j) * n + i.max(j)];
                *value = (h * self.weight_ratios[i * n + j]).max(0.);
            }
            let norm: f64 = column.iter().sum();
            for (i, value) in column.iter().enumerate() {
                q[j * p + i / self.subdivisions] +=
                    value / (norm * self.weights[i] * self.subdivisions as f64);
            }
        }
        q
    }

    fn probability(&self, low: f64, high: f64, rm: f64, du: f64) -> Vec<f64> {
        let mut result = vec![0.; self.weights.len()];
        self.probability_into(low, high, rm, du, &mut result);
        result
    }

    fn probability_into(&self, low: f64, high: f64, rm: f64, du: f64, result: &mut [f64]) {
        result.fill(0.);
        let log_width = (high / low).ln();
        for p in 0..self.pitch.len() - 1 {
            let mut edges = [low, high, (-du).clamp(low, high), low, low];
            for k in 0..2 {
                let d = rm * self.pitch_sin2[p + k] - 1.;
                edges[k + 3] = (if d == 0. { -1. } else { du / d }).clamp(low, high);
            }
            edges.sort_by(f64::total_cmp);
            for segment in edges.windows(2) {
                if segment[0] == segment[1] {
                    continue;
                }
                let lo = segment[0].ln();
                let hi = segment[1].ln();
                let start = p * self.subdivisions;
                let end = start + self.subdivisions;
                let angle = |node: f64| {
                    let e = ((lo + hi) / 2. + (hi - lo) * node / 2.).exp();
                    ((1. + du / e) / rm)
                        .clamp(0., 1.)
                        .sqrt()
                        .asin()
                        .to_degrees()
                };
                let [min_node, max_node] = self.node_extrema;
                let (min_angle_node, max_angle_node) = if du < 0. {
                    (min_node, max_node)
                } else {
                    (max_node, min_node)
                };
                // The boundary is monotone in energy. Guard with the actual
                // quadrature extrema, including roundoff at pitch-bin edges.
                if angle(max_angle_node) <= self.fine[start] {
                    // Retain all 17 additions in order for identical rounding.
                    for &weight in &self.node_weights {
                        let mass = weight * (hi - lo) / log_width;
                        for value in &mut result[start..end] {
                            *value += mass;
                        }
                    }
                    continue;
                }
                if angle(min_angle_node) >= self.fine[end] {
                    continue;
                }
                for (&node, &weight) in self.nodes.iter().zip(&self.node_weights) {
                    let angle = angle(node);
                    for f in 0..self.subdivisions {
                        let j = p * self.subdivisions + f;
                        result[j] += weight * (hi - lo) / log_width
                            * ((self.fine[j + 1] - angle) / (self.fine[j + 1] - self.fine[j]))
                                .clamp(0., 1.);
                    }
                }
            }
        }
    }

    fn evaluate(&self, event: &Event, x: [f64; 5], save: bool) -> Evaluation {
        let n = self.weights.len();
        let p = self.pitch.len() - 1;
        let rm = 10_f64.powf(x[0]);
        let rho = 10_f64.powf(x[1]);
        let du = x[2] * 500.;
        let scale = 10_f64.powf(x[3]);
        let q = self.projection(x[4]);
        let nt = if self.beam_enabled && du < 0. { 17 } else { 1 };
        let mut costs = vec![0.; nt];
        let mut predictions = vec![Vec::new(); if save { nt } else { 0 }];
        let mut probability = vec![0.; n];
        let mut reflected = vec![0.; p];
        let mut beam = vec![vec![0.; p]; 2];
        for row in 0..event.low.len() {
            if rho != 1. {
                self.probability_into(event.low[row], event.high[row], rm, du, &mut probability);
            }
            reflected.fill(0.);
            for values in &mut beam {
                values.fill(0.);
            }
            for j in 0..n {
                let ni = event.reference[row][j / self.subdivisions] * self.weights[j];
                let reflection = scale * (rho + (1. - rho) * probability[j]) * ni;
                for target in 0..p {
                    reflected[target] += reflection * q[j * p + target];
                    if nt > 1 {
                        for (b, values) in beam.iter_mut().enumerate() {
                            values[target] += ni * self.angular_beams[b][j] * q[j * p + target];
                        }
                    }
                }
            }
            let mut spectral = [0.; 2];
            if nt > 1 {
                let center = (-du).ln();
                for (index, width) in [0.15, 0.30].iter().enumerate() {
                    let lo = event.low[row]
                        .ln()
                        .clamp(center - 3. * width, center + 3. * width);
                    let hi = event.high[row]
                        .ln()
                        .clamp(center - 3. * width, center + 3. * width);
                    spectral[index] = width
                        * (std::f64::consts::PI / 2.).sqrt()
                        * (libm::erf((hi - center) / (2_f64.sqrt() * width))
                            - libm::erf((lo - center) / (2_f64.sqrt() * width)))
                        / (event.high[row] / event.low[row]).ln();
                }
            }
            for target in 0..p {
                if !save && !event.mask[row][target] {
                    continue;
                }
                for template in 0..nt {
                    let addition = if template == 0 {
                        0.
                    } else {
                        let j = template - 1;
                        spectral[j / 8] * beam[(j / 4) % 2][target] * [0.5, 1., 2., 4.][j % 4]
                    };
                    let log =
                        ((reflected[target] + addition) / event.reference[row][target]).log10();
                    if event.mask[row][target] {
                        let r = log - event.observed[row][target];
                        costs[template] += if self.huber_delta == 0. {
                            r * r
                        } else if r.abs() <= self.huber_delta {
                            r * r
                        } else {
                            2. * self.huber_delta * r.abs() - self.huber_delta.powi(2)
                        };
                    }
                    if save {
                        predictions[template].push(log);
                    }
                }
            }
        }
        let template = (0..nt)
            .min_by(|&a, &b| costs[a].total_cmp(&costs[b]))
            .unwrap();
        Evaluation {
            cost: costs[template],
            template,
            prediction: if save {
                std::mem::take(&mut predictions[template])
            } else {
                Vec::new()
            },
        }
    }
}

struct Random(u64);
impl Random {
    fn unit(&mut self) -> f64 {
        self.0 = self.0.wrapping_add(0x9e3779b97f4a7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
        ((z ^ (z >> 31)) >> 11) as f64 / (1u64 << 53) as f64
    }
    fn index(&mut self, n: usize) -> usize {
        (self.unit() * n as f64) as usize
    }
}
fn clip(mut x: [f64; 5], bounds: &[[f64; 2]; 5]) -> [f64; 5] {
    for j in 0..5 {
        x[j] = x[j].clamp(bounds[j][0], bounds[j][1]);
    }
    x
}
fn local(
    start: [f64; 5],
    bounds: &[[f64; 2]; 5],
    score: &mut impl FnMut([f64; 5]) -> f64,
) -> (f64, [f64; 5], bool) {
    let free: Vec<_> = (0..5).filter(|&j| bounds[j][0] < bounds[j][1]).collect();
    let n = free.len();
    let mut simplex = vec![(score(start), start)];
    if n == 0 {
        return (simplex[0].0, start, true);
    }
    for j in free {
        let mut x = start;
        let step = if x[j] == 0. { 0.00025 } else { 0.05 * x[j] };
        x[j] = (x[j] + step).clamp(bounds[j][0], bounds[j][1]);
        if x[j] == start[j] {
            x[j] = (x[j] - step).clamp(bounds[j][0], bounds[j][1]);
        }
        simplex.push((score(x), x));
    }
    for _ in 0..650 {
        simplex.sort_by(|a, b| a.0.total_cmp(&b.0));
        if simplex
            .iter()
            .all(|r| (0..5).all(|j| (r.1[j] - simplex[0].1[j]).abs() < 1e-6))
            && simplex[n].0 - simplex[0].0 < 1e-9
        {
            return (simplex[0].0, simplex[0].1, true);
        }
        let center: [f64; 5] = clip(
            std::array::from_fn(|j| simplex[..n].iter().map(|r| r.1[j]).sum::<f64>() / n as f64),
            bounds,
        );
        let xr = clip(
            std::array::from_fn(|j| 2. * center[j] - simplex[n].1[j]),
            bounds,
        );
        let fr = score(xr);
        if fr < simplex[0].0 {
            let xe = clip(
                std::array::from_fn(|j| center[j] + 2. * (xr[j] - center[j])),
                bounds,
            );
            let fe = score(xe);
            simplex[n] = if fe < fr { (fe, xe) } else { (fr, xr) };
        } else if fr < simplex[n - 1].0 {
            simplex[n] = (fr, xr);
        } else {
            let outside = fr < simplex[n].0;
            let xc = clip(
                std::array::from_fn(|j| {
                    center[j] + 0.5 * ((if outside { xr[j] } else { simplex[n].1[j] }) - center[j])
                }),
                bounds,
            );
            let fc = score(xc);
            if fc < if outside { fr } else { simplex[n].0 } {
                simplex[n] = (fc, xc);
            } else {
                for i in 1..=n {
                    let x = clip(
                        std::array::from_fn(|j| {
                            simplex[0].1[j] + 0.5 * (simplex[i].1[j] - simplex[0].1[j])
                        }),
                        bounds,
                    );
                    simplex[i] = (score(x), x);
                }
            }
        }
    }
    simplex.sort_by(|a, b| a.0.total_cmp(&b.0));
    (simplex[0].0, simplex[0].1, false)
}

fn fit(
    config: &Config,
    event: &Event,
    bounds: &[[f64; 2]; 5],
    starts: &[[f64; 5]],
    generations: usize,
    seeds: usize,
    seed: u64,
) -> FitResult {
    let mut calls = 0;
    let mut score = |x| {
        calls += 1;
        config.evaluate(event, x, false).cost
    };
    let free: Vec<_> = (0..5).filter(|&j| bounds[j][0] < bounds[j][1]).collect();
    let starts: Vec<_> = starts.iter().map(|x| clip(*x, bounds)).collect();
    let mut best = (score(starts[0]), starts[0], free.is_empty());
    let mut local_starts = starts.clone();
    for run in 0..if free.is_empty() { 0 } else { seeds } {
        let mut rng = Random(seed.wrapping_add(run as u64));
        let count = 35;
        let mut population: Vec<[f64; 5]> = (0..count)
            .map(|_| {
                std::array::from_fn(|j| bounds[j][0] + rng.unit() * (bounds[j][1] - bounds[j][0]))
            })
            .collect();
        for (i, x) in starts.iter().take(count).enumerate() {
            population[i] = *x;
        }
        let mut costs: Vec<_> = population.iter().map(|x| score(*x)).collect();
        for _ in 0..generations {
            let champion = (0..count)
                .min_by(|&a, &b| costs[a].total_cmp(&costs[b]))
                .unwrap();
            let factor = 0.5 + 0.5 * rng.unit();
            for i in 0..count {
                let mut a = rng.index(count);
                while a == i {
                    a = rng.index(count);
                }
                let mut b = rng.index(count);
                while b == i || b == a {
                    b = rng.index(count);
                }
                let force = free[rng.index(free.len())];
                let mut trial = population[i];
                for j in 0..5 {
                    if j == force || rng.unit() < 0.7 {
                        let value = population[champion][j]
                            + factor * (population[a][j] - population[b][j]);
                        trial[j] = if value < bounds[j][0] || value > bounds[j][1] {
                            bounds[j][0] + rng.unit() * (bounds[j][1] - bounds[j][0])
                        } else {
                            value
                        };
                    }
                }
                let value = score(trial);
                if value <= costs[i] {
                    population[i] = trial;
                    costs[i] = value;
                }
            }
        }
        let mut order: Vec<_> = (0..count).collect();
        order.sort_by(|&a, &b| costs[a].total_cmp(&costs[b]));
        for &i in order.iter().take(2) {
            local_starts.push(population[i]);
            if costs[i] < best.0 {
                best = (costs[i], population[i], false);
            }
        }
    }
    for start in local_starts {
        let result = local(start, bounds, &mut score);
        if result.0 < best.0 || (result.0 <= best.0 + 1e-12 && result.2 && !best.2) {
            best = (result.0, result.1, result.2);
        }
    }
    let evaluation = config.evaluate(event, best.1, true);
    FitResult {
        x: best.1,
        cost: evaluation.cost,
        template: evaluation.template,
        prediction: evaluation.prediction,
        evaluations: calls,
        converged: best.2,
    }
}

#[pyclass]
pub struct FiniteBinProblem {
    config: Config,
    event: Event,
}
type EvaluationOutput = (f64, usize, Vec<f64>, bool);
type FitOutput = ([f64; 5], f64, usize, Vec<f64>, bool, usize, bool);

fn validate_x(x: &[f64; 5]) -> PyResult<()> {
    if x.iter().any(|v| !v.is_finite())
        || [x[0], x[1], x[3]].iter().any(|v| {
            let p = 10_f64.powf(*v);
            !p.is_finite() || p <= 0.
        })
        || x[1] > 0.
        || !(0. ..=90.).contains(&x[4])
        || !(x[2] * 500.).is_finite()
    {
        return Err(PyValueError::new_err("invalid finite-bin parameter vector"));
    }
    Ok(())
}

#[pymethods]
impl FiniteBinProblem {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        pitch: Vec<f64>,
        fine: Vec<f64>,
        weights: Vec<f64>,
        eigenvalues: Vec<f64>,
        eigenvectors: Vec<f64>,
        angular_beams: Vec<Vec<f64>>,
        nodes: Vec<f64>,
        node_weights: Vec<f64>,
        subdivisions: usize,
        low: Vec<f64>,
        high: Vec<f64>,
        reference: Vec<Vec<f64>>,
        mask: Vec<Vec<bool>>,
        observed: Vec<Vec<f64>>,
        beam_enabled: bool,
        huber_delta: f64,
    ) -> PyResult<Self> {
        let n = weights.len();
        let p = pitch.len().saturating_sub(1);
        let e = low.len();
        if n == 0
            || p == 0
            || e == 0
            || subdivisions == 0
            || p.checked_mul(subdivisions) != Some(n)
            || n.checked_mul(n) != Some(eigenvectors.len())
            || fine.len() != n + 1
            || eigenvalues.len() != n
            || angular_beams.len() != 2
            || angular_beams.iter().any(|v| v.len() != n)
            || nodes.len() != node_weights.len()
            || nodes.is_empty()
            || high.len() != e
            || reference.len() != e
            || mask.len() != e
            || observed.len() != e
            || reference.iter().any(|r| r.len() != p)
            || mask.iter().any(|r| r.len() != p)
            || observed.iter().any(|r| r.len() != p)
            || pitch.first() != Some(&0.)
            || pitch.last() != Some(&90.)
            || fine.first() != Some(&0.)
            || fine.last() != Some(&90.)
            || pitch.windows(2).any(|r| r[1] <= r[0])
            || fine.windows(2).any(|r| r[1] <= r[0])
            || weights.iter().any(|w| !w.is_finite() || *w <= 0.)
            || reference
                .iter()
                .flatten()
                .any(|v| !v.is_finite() || *v <= 0.)
            || low
                .iter()
                .zip(&high)
                .any(|(a, b)| !a.is_finite() || !b.is_finite() || *a <= 0. || b <= a)
            || !mask.iter().flatten().any(|v| *v)
            || [
                pitch.as_slice(),
                fine.as_slice(),
                eigenvalues.as_slice(),
                eigenvectors.as_slice(),
                nodes.as_slice(),
                node_weights.as_slice(),
            ]
            .iter()
            .any(|r| r.iter().any(|v| !v.is_finite()))
            || angular_beams.iter().flatten().any(|v| !v.is_finite())
            || observed.iter().flatten().any(|v| !v.is_finite())
            || !huber_delta.is_finite()
            || huber_delta < 0.
        {
            return Err(PyValueError::new_err(
                "invalid finite-bin angular response or observations",
            ));
        }
        let pitch_sin2 = pitch.iter().map(|p| p.to_radians().sin().powi(2)).collect();
        let mut eigenvector_columns = vec![0.; n * n];
        let mut weight_ratios = vec![0.; n * n];
        for i in 0..n {
            for j in 0..n {
                eigenvector_columns[j * n + i] = eigenvectors[i * n + j];
                weight_ratios[i * n + j] = (weights[i] / weights[j]).sqrt();
            }
        }
        let node_extrema = [
            nodes.iter().copied().fold(f64::INFINITY, f64::min),
            nodes.iter().copied().fold(f64::NEG_INFINITY, f64::max),
        ];
        Ok(Self {
            config: Config {
                pitch,
                fine,
                weights,
                eigenvalues,
                eigenvectors,
                eigenvector_columns,
                weight_ratios,
                pitch_sin2,
                angular_beams,
                nodes,
                node_weights,
                node_extrema,
                subdivisions,
                beam_enabled,
                huber_delta,
            },
            event: Event {
                low,
                high,
                reference,
                mask,
                observed,
            },
        })
    }

    fn evaluate(&self, py: Python<'_>, x: [f64; 5]) -> PyResult<EvaluationOutput> {
        validate_x(&x)?;
        let result = py.detach(|| self.config.evaluate(&self.event, x, true));
        if !result.cost.is_finite() || result.prediction.iter().any(|v| !v.is_finite()) {
            return Err(PyValueError::new_err(
                "finite-bin prediction or objective overflow",
            ));
        }
        Ok((
            result.cost,
            result.template,
            result.prediction,
            self.config.barrier_unobserved(&self.event, x),
        ))
    }

    fn fit(
        &self,
        py: Python<'_>,
        bounds: [[f64; 2]; 5],
        starts: Vec<[f64; 5]>,
        generations: usize,
        seeds: usize,
        seed: u64,
    ) -> PyResult<FitOutput> {
        if starts.is_empty() || seeds == 0 || bounds.iter().any(|b| b[0] > b[1]) {
            return Err(PyValueError::new_err(
                "fit needs starts, seeds and ordered bounds",
            ));
        }
        validate_x(&std::array::from_fn(|j| bounds[j][0]))?;
        validate_x(&std::array::from_fn(|j| bounds[j][1]))?;
        for x in &starts {
            validate_x(x)?;
        }
        let result = py.detach(|| {
            fit(
                &self.config,
                &self.event,
                &bounds,
                &starts,
                generations,
                seeds,
                seed,
            )
        });
        if !result.cost.is_finite() || result.prediction.iter().any(|v| !v.is_finite()) {
            return Err(PyValueError::new_err(
                "finite-bin prediction or objective overflow",
            ));
        }
        let barrier = self.config.barrier_unobserved(&self.event, result.x);
        Ok((
            result.x,
            result.cost,
            result.template,
            result.prediction,
            result.converged,
            result.evaluations,
            barrier,
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn response() -> Config {
        let pitch: Vec<f64> = vec![0., 27., 90.];
        let fine = vec![0., 13.5, 27., 58.5, 90.];
        let weights: Vec<f64> = vec![0.1, 0.2, 0.3, 0.4];
        let eigenvectors = vec![
            0.5, 0.5, 0.5, 0.5, -0.5, 0.5, -0.5, 0.5, 0.5, -0.5, -0.5, 0.5, -0.5, -0.5, 0.5, 0.5,
        ];
        let mut columns = vec![0.; 16];
        let mut ratios = vec![0.; 16];
        for i in 0..4 {
            for j in 0..4 {
                columns[j * 4 + i] = eigenvectors[i * 4 + j];
                ratios[i * 4 + j] = (weights[i] / weights[j]).sqrt();
            }
        }
        Config {
            pitch_sin2: pitch.iter().map(|p| p.to_radians().sin().powi(2)).collect(),
            pitch,
            fine,
            weights,
            eigenvalues: vec![-6., -4., -2., 0.],
            eigenvectors,
            eigenvector_columns: columns,
            weight_ratios: ratios,
            angular_beams: vec![vec![0.; 4]; 2],
            // Deliberately unordered: shortcuts must use extrema, not endpoints.
            nodes: vec![0.5, 0.9, -0.9, 0., -0.5],
            node_weights: vec![0.25, 0.1, 0.1, 0.3, 0.25],
            node_extrema: [-0.9, 0.9],
            subdivisions: 2,
            beam_enabled: true,
            huber_delta: 0.1,
        }
    }

    // Frozen scalar formulas from the pre-optimization implementation. These
    // verify rounding order as well as the mathematical forward response.
    fn scalar_projection(c: &Config, sigma: f64) -> Vec<f64> {
        let n = c.weights.len();
        let p = c.pitch.len() - 1;
        let mut q = vec![0.; n * p];
        let decay: Vec<_> = c
            .eigenvalues
            .iter()
            .map(|v| (v * sigma.to_radians().powi(2) / 4.).exp())
            .collect();
        let first = decay.iter().position(|v| *v > 0.).unwrap_or(n - 1);
        for j in 0..n {
            let mut column = vec![0.; n];
            for (i, value) in column.iter_mut().enumerate() {
                let mut heat = 0.;
                for (k, &d) in decay.iter().enumerate().skip(first) {
                    heat += c.eigenvectors[i * n + k] * c.eigenvectors[j * n + k] * d;
                }
                *value = (heat * (c.weights[i] / c.weights[j]).sqrt()).max(0.);
            }
            let norm: f64 = column.iter().sum();
            for (i, value) in column.iter().enumerate() {
                q[j * p + i / c.subdivisions] +=
                    value / (norm * c.weights[i] * c.subdivisions as f64);
            }
        }
        q
    }

    fn scalar_probability(c: &Config, low: f64, high: f64, rm: f64, du: f64) -> Vec<f64> {
        let mut result = vec![0.; c.weights.len()];
        let log_width = (high / low).ln();
        for p in 0..c.pitch.len() - 1 {
            let mut edges = [low, high, (-du).clamp(low, high), low, low];
            for k in 0..2 {
                let d = rm * c.pitch[p + k].to_radians().sin().powi(2) - 1.;
                edges[k + 3] = (if d == 0. { -1. } else { du / d }).clamp(low, high);
            }
            edges.sort_by(f64::total_cmp);
            for seg in edges.windows(2) {
                if seg[0] == seg[1] {
                    continue;
                }
                let lo = seg[0].ln();
                let hi = seg[1].ln();
                for (&node, &weight) in c.nodes.iter().zip(&c.node_weights) {
                    let e = ((lo + hi) / 2. + (hi - lo) * node / 2.).exp();
                    let theta = ((1. + du / e) / rm)
                        .clamp(0., 1.)
                        .sqrt()
                        .asin()
                        .to_degrees();
                    for f in 0..c.subdivisions {
                        let j = p * c.subdivisions + f;
                        result[j] += weight * (hi - lo) / log_width
                            * ((c.fine[j + 1] - theta) / (c.fine[j + 1] - c.fine[j])).clamp(0., 1.);
                    }
                }
            }
        }
        result
    }

    #[test]
    fn simd_projection_retains_scalar_summation_order() {
        let c = response();
        for sigma in [0.0001, 0.5, 12., 90.] {
            assert_eq!(c.projection(sigma), scalar_projection(&c, sigma));
        }
    }

    #[test]
    fn bin_shortcuts_retain_scalar_quadrature_at_crossings() {
        let c = response();
        let critical = 1. / 27_f64.to_radians().sin().powi(2);
        for rm in [
            0.001,
            1.,
            4.,
            1000.,
            critical,
            f64::from_bits(critical.to_bits() - 1),
            f64::from_bits(critical.to_bits() + 1),
        ] {
            for du in [-500., -200., -100., 0., 1., 1000.] {
                for (low, high) in [(90., 110.), (100., 200.), (200., 400.)] {
                    assert_eq!(
                        c.probability(low, high, rm, du),
                        scalar_probability(&c, low, high, rm, du),
                        "Rm={rm}, DU={du}, E=[{low},{high}]"
                    );
                }
            }
        }
    }

    #[test]
    fn bounded_search_recovers_interior_and_boundary() {
        for target in [[0.3, -1.2, 0.4, 0., 12.], [-3., 0., 2., 0., 0.]] {
            let bounds = [[-3., 3.], [-4., 0.], [-1., 2.], [0., 0.], [0., 90.]];
            let mut score = |x: [f64; 5]| (0..5).map(|j| (x[j] - target[j]).powi(2)).sum();
            let (cost, _, converged) = local([1., -0.3, 0.1, 0., 20.], &bounds, &mut score);
            assert!(converged && cost < 1e-9, "{cost}");
        }
    }
}
