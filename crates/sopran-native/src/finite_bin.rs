//! Folded finite-bin reflection followed by conservative D_out and bin response.
//! Port of the validated angle-transport pilot; all search iterations stay in Rust.
//!
//! The parameter vector is `[log10 Rm, log10 rho, Delta U / 500 eV, log10 scale,
//! sigma_deg, log10 concentration]`. Concentration is used only by the
//! beta-binomial count likelihood; other losses keep it fixed.
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

const NP: usize = 6;
type Vector = [f64; NP];
const BEAM_SHAPES: usize = 4;
const AMPLITUDE_STEPS: usize = 12;
/// Beam shapes whose largest relative addition stays below this are skipped.
const BEAM_NEGLIGIBLE: f64 = 1e-4;
const LEVEL_STEPS: usize = 48;
const LEVEL_BOUNDS_DEX: [f64; 2] = [-6., 6.];
const CONCENTRATION_STEPS: usize = 32;

#[derive(Clone, Copy, PartialEq, Debug)]
enum Loss {
    Squared,
    Huber(f64),
    Binomial,
    BetaBinomial,
}

impl Loss {
    fn counts(self) -> bool {
        matches!(self, Loss::Binomial | Loss::BetaBinomial)
    }
}

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
    beam_log_amplitude: [f64; 2],
    loss: Loss,
    scale_prior_inv_var: f64,
}
struct Event {
    low: Vec<f64>,
    high: Vec<f64>,
    reference: Vec<Vec<f64>>,
    mask: Vec<Vec<bool>>,
    observed: Vec<Vec<f64>>,
    affected: Vec<Vec<f64>>,
    total: Vec<Vec<f64>>,
    offset: Vec<Vec<f64>>,
    /// Affected/reference exposure ratio times 10^offset: model ratio to count odds.
    gain: Vec<Vec<f64>>,
    saturated: Vec<Vec<f64>>,
}
struct Evaluation {
    cost: f64,
    template: usize,
    amplitude: f64,
    prediction: Vec<f64>,
}
struct FitResult {
    x: Vector,
    evaluation: Evaluation,
    evaluations: usize,
    converged: bool,
}
/// Model ratio components for one detector cell, relative to its incident flux.
struct Cell {
    row: usize,
    col: usize,
    masked: bool,
    base: f64,
    beams: [f64; BEAM_SHAPES],
}

/// ln Gamma(x) for x > 0: Stirling series after shifting x to at least 7.
/// Absolute error is below 1e-10, ample for deviances of order one or more.
fn ln_gamma(mut x: f64) -> f64 {
    let mut shift = 1.;
    while x < 7. {
        shift *= x;
        x += 1.;
    }
    let inverse = 1. / x;
    let square = inverse * inverse;
    let series =
        inverse * (1. / 12. - square * (1. / 360. - square * (1. / 1260. - square / 1680.)));
    (x - 0.5) * x.ln() - x + 0.918_938_533_204_672_8 + series - shift.ln()
}

fn xlogy_ratio(a: f64, n: f64) -> f64 {
    if a <= 0. {
        0.
    } else {
        a * (a / n).ln()
    }
}

/// Golden-section minimum of a unimodal 1-D function on `[lo, hi]`.
fn golden(lo: f64, hi: f64, steps: usize, mut f: impl FnMut(f64) -> f64) -> (f64, f64) {
    let ratio = (5_f64.sqrt() - 1.) / 2.;
    let (mut a, mut b) = (lo, hi);
    let mut c = b - ratio * (b - a);
    let mut d = a + ratio * (b - a);
    let (mut fc, mut fd) = (f(c), f(d));
    for _ in 0..steps {
        if fc <= fd {
            b = d;
            d = c;
            fd = fc;
            c = b - ratio * (b - a);
            fc = f(c);
        } else {
            a = c;
            c = d;
            fc = fd;
            d = a + ratio * (b - a);
            fd = f(d);
        }
    }
    if fc <= fd {
        (fc, c)
    } else {
        (fd, d)
    }
}

impl Config {
    fn barrier_unobserved(&self, event: &Event, x: Vector) -> bool {
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

    /// Rows whose fitted cells lie on both sides of the bin-mean reflection boundary.
    fn boundary_rows(&self, event: &Event, x: Vector) -> usize {
        let mut rows = 0;
        for row in 0..event.low.len() {
            if !event.mask[row].iter().any(|m| *m) {
                continue;
            }
            let probability = self.probability(
                event.low[row],
                event.high[row],
                10_f64.powf(x[0]),
                x[2] * 500.,
            );
            let (mut lost, mut reflected) = (false, false);
            for (target, chunk) in probability.chunks(self.subdivisions).enumerate() {
                if event.mask[row][target] {
                    let mean = chunk.iter().sum::<f64>() / self.subdivisions as f64;
                    lost |= mean < 0.5;
                    reflected |= mean >= 0.5;
                }
            }
            rows += usize::from(lost && reflected);
        }
        rows
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

    /// Beta-binomial normaliser ln Gamma(n + phi) - ln Gamma(phi); zero otherwise.
    fn norm(&self, event: &Event, row: usize, col: usize, phi: f64) -> f64 {
        if self.loss == Loss::BetaBinomial && event.mask[row][col] {
            ln_gamma(event.total[row][col] + phi) - ln_gamma(phi)
        } else {
            0.
        }
    }

    /// Objective contribution of one cell for a linear model ratio without
    /// the calibration offset. Count losses return a deviance relative to the
    /// saturated binomial log likelihood. `norm` comes from [`Config::norm`]
    /// with the same concentration `phi`.
    #[allow(clippy::too_many_arguments)]
    fn cell_cost(
        &self,
        event: &Event,
        row: usize,
        col: usize,
        ratio: f64,
        phi: f64,
        norm: f64,
    ) -> f64 {
        match self.loss {
            Loss::Squared => {
                let r = ratio.log10() + event.offset[row][col] - event.observed[row][col];
                r * r
            }
            Loss::Huber(delta) => {
                let r = ratio.log10() + event.offset[row][col] - event.observed[row][col];
                if r.abs() <= delta {
                    r * r
                } else {
                    2. * delta * r.abs() - delta.powi(2)
                }
            }
            Loss::Binomial | Loss::BetaBinomial => {
                let a = event.affected[row][col];
                let n = event.total[row][col];
                // Odds of an affected count; q = odds / (1 + odds).
                let odds = ratio * event.gain[row][col];
                let likelihood = if self.loss == Loss::Binomial {
                    let hit = if a > 0. { a * odds.ln() } else { 0. };
                    hit - n * odds.ln_1p()
                } else {
                    let alpha = (phi * odds / (1. + odds)).max(f64::MIN_POSITIVE);
                    let beta = (phi / (1. + odds)).max(f64::MIN_POSITIVE);
                    ln_gamma(a + alpha) - ln_gamma(alpha) + ln_gamma(n - a + beta)
                        - ln_gamma(beta)
                        - norm
                };
                2. * (event.saturated[row][col] - likelihood)
            }
        }
    }

    fn cell_ratio(cell: &Cell, template: usize, amplitude: f64) -> f64 {
        if template == 0 {
            cell.base
        } else {
            cell.base + amplitude * cell.beams[template - 1]
        }
    }

    fn cell_log_ratio(&self, event: &Event, cell: &Cell, template: usize, amplitude: f64) -> f64 {
        Self::cell_ratio(cell, template, amplitude).log10() + event.offset[cell.row][cell.col]
    }

    /// Reflection and beam components for active rows; all cells when `save`.
    fn cells(&self, event: &Event, x: Vector, save: bool) -> (Vec<Cell>, bool) {
        let n = self.weights.len();
        let p = self.pitch.len() - 1;
        let rm = 10_f64.powf(x[0]);
        let rho = 10_f64.powf(x[1]);
        let du = x[2] * 500.;
        let scale = 10_f64.powf(x[3]);
        let q = self.projection(x[4]);
        let beam_active = self.beam_enabled && du < 0.;
        let mut probability = vec![0.; n];
        let mut reflected = vec![0.; p];
        let mut beam = vec![vec![0.; p]; 2];
        let mut cells = Vec::new();
        for row in 0..event.low.len() {
            if !event.mask[row].iter().any(|m| *m) {
                continue;
            }
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
                    if beam_active {
                        for (b, values) in beam.iter_mut().enumerate() {
                            values[target] += ni * self.angular_beams[b][j] * q[j * p + target];
                        }
                    }
                }
            }
            let mut spectral = [0.; 2];
            if beam_active {
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
                let masked = event.mask[row][target];
                if !save && !masked {
                    continue;
                }
                let reference = event.reference[row][target];
                cells.push(Cell {
                    row,
                    col: target,
                    masked,
                    base: reflected[target] / reference,
                    // Shape = 2 * spectral width index + pitch width index.
                    beams: std::array::from_fn(|s| {
                        spectral[s / 2] * beam[s % 2][target] / reference
                    }),
                });
            }
        }
        (cells, beam_active)
    }

    /// Best beam shape and continuous amplitude for one parameter vector.
    /// Shapes whose cost without the beam-touched cells already exceeds
    /// `threshold` are skipped: every cell cost is non-negative, so they
    /// cannot reach it. Callers needing the exact minimum pass infinity.
    fn select_beam(
        &self,
        event: &Event,
        cells: &[Cell],
        phi: f64,
        beam_active: bool,
        threshold: f64,
    ) -> (f64, usize, f64) {
        let norms: Vec<f64> = cells
            .iter()
            .map(|c| self.norm(event, c.row, c.col, phi))
            .collect();
        let base: Vec<f64> = cells
            .iter()
            .zip(&norms)
            .map(|(c, &norm)| {
                if c.masked {
                    self.cell_cost(event, c.row, c.col, c.base, phi, norm)
                } else {
                    0.
                }
            })
            .collect();
        let none: f64 = base.iter().sum();
        let mut best = (none, 0, 0.);
        if !beam_active {
            return best;
        }
        let [lo, hi] = self.beam_log_amplitude;
        for shape in 0..BEAM_SHAPES {
            let maximum = 10_f64.powf(hi);
            let touched: Vec<usize> = (0..cells.len())
                .filter(|&k| cells[k].masked && cells[k].beams[shape] > 0.)
                .collect();
            if touched
                .iter()
                .all(|&k| maximum * cells[k].beams[shape] < BEAM_NEGLIGIBLE * cells[k].base)
            {
                continue;
            }
            let mut rest = 0.;
            let mut next = touched.iter().peekable();
            for (k, value) in base.iter().enumerate() {
                if next.peek() == Some(&&k) {
                    next.next();
                } else {
                    rest += value;
                }
            }
            if rest > threshold.min(best.0) {
                continue;
            }
            let template = shape + 1;
            let (cost, log_amplitude) = golden(lo, hi, AMPLITUDE_STEPS, |u| {
                let amplitude = 10_f64.powf(u);
                rest + touched
                    .iter()
                    .map(|&k| {
                        let c = &cells[k];
                        let ratio = Self::cell_ratio(c, template, amplitude);
                        self.cell_cost(event, c.row, c.col, ratio, phi, norms[k])
                    })
                    .sum::<f64>()
            });
            if cost < best.0 {
                best = (cost, template, 10_f64.powf(log_amplitude));
            }
        }
        best
    }

    fn prior(&self, x: Vector) -> f64 {
        self.scale_prior_inv_var * x[3] * x[3]
    }

    /// Objective at `x`; values above `threshold` may be lower bounds only.
    fn evaluate(&self, event: &Event, x: Vector, save: bool, threshold: f64) -> Evaluation {
        let (cells, beam_active) = self.cells(event, x, save);
        let phi = 10_f64.powf(x[5]);
        let prior = self.prior(x);
        let (cost, template, amplitude) =
            self.select_beam(event, &cells, phi, beam_active, threshold - prior);
        let prediction = if save {
            cells
                .iter()
                .map(|c| self.cell_log_ratio(event, c, template, amplitude))
                .collect()
        } else {
            Vec::new()
        };
        Evaluation {
            cost: cost + prior,
            template,
            amplitude,
            prediction,
        }
    }

    /// Minimum objective with one free log10 level per energy row (and one
    /// shared concentration for the beta-binomial loss). Cells carry linear
    /// model ratios without the calibration offset.
    fn row_profiled(
        &self,
        event: &Event,
        cells: &[(usize, usize, f64)],
        phi_bounds: [f64; 2],
    ) -> f64 {
        let rows: Vec<Vec<(usize, usize, f64)>> = (0..event.low.len())
            .map(|row| cells.iter().filter(|c| c.0 == row).copied().collect())
            .filter(|r: &Vec<_>| !r.is_empty())
            .collect();
        let total = |log_phi: f64| {
            let phi = 10_f64.powf(log_phi);
            rows.iter()
                .map(|members| {
                    let norms: Vec<f64> = members
                        .iter()
                        .map(|&(row, col, _)| self.norm(event, row, col, phi))
                        .collect();
                    let [lo, hi] = LEVEL_BOUNDS_DEX;
                    golden(lo, hi, LEVEL_STEPS, |level| {
                        let factor = 10_f64.powf(level);
                        members
                            .iter()
                            .zip(&norms)
                            .map(|(&(row, col, ratio), &norm)| {
                                self.cell_cost(event, row, col, ratio * factor, phi, norm)
                            })
                            .sum()
                    })
                    .0
                })
                .sum::<f64>()
        };
        if self.loss == Loss::BetaBinomial && phi_bounds[0] < phi_bounds[1] {
            golden(phi_bounds[0], phi_bounds[1], CONCENTRATION_STEPS, total).0
        } else {
            total(phi_bounds[0])
        }
    }

    /// Row-level profiled objectives without and with the loss-cone boundary.
    fn loss_cone_test(
        &self,
        event: &Event,
        x: Vector,
        template: usize,
        amplitude: f64,
        phi_bounds: [f64; 2],
    ) -> (f64, f64) {
        let fixed = |x: Vector| -> Vec<(usize, usize, f64)> {
            let (cells, _) = self.cells(event, x, false);
            cells
                .iter()
                .map(|c| (c.row, c.col, Self::cell_ratio(c, template, amplitude)))
                .collect()
        };
        let mut without = x;
        without[1] = 0.;
        (
            self.row_profiled(event, &fixed(without), phi_bounds),
            self.row_profiled(event, &fixed(x), phi_bounds),
        )
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
fn clip(mut x: Vector, bounds: &[[f64; 2]; NP]) -> Vector {
    for j in 0..NP {
        x[j] = x[j].clamp(bounds[j][0], bounds[j][1]);
    }
    x
}
fn local(
    start: Vector,
    bounds: &[[f64; 2]; NP],
    score: &mut impl FnMut(Vector) -> f64,
) -> (f64, Vector, bool) {
    let free: Vec<_> = (0..NP).filter(|&j| bounds[j][0] < bounds[j][1]).collect();
    let n = free.len();
    let mut simplex = vec![(score(start), start)];
    if n == 0 {
        return (simplex[0].0, start, true);
    }
    for j in free {
        // Small relative steps keep Nelder–Mead a local refiner of each start;
        // range-proportional steps were tested and left good basins.
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
            .all(|r| (0..NP).all(|j| (r.1[j] - simplex[0].1[j]).abs() < 1e-6))
            && simplex[n].0 - simplex[0].0 < 1e-9
        {
            return (simplex[0].0, simplex[0].1, true);
        }
        let center: Vector = clip(
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
    bounds: &[[f64; 2]; NP],
    starts: &[Vector],
    generations: usize,
    seeds: usize,
    seed: u64,
) -> FitResult {
    let mut calls = 0;
    let mut bounded = |x, threshold| {
        calls += 1;
        config.evaluate(event, x, false, threshold).cost
    };
    let free: Vec<_> = (0..NP).filter(|&j| bounds[j][0] < bounds[j][1]).collect();
    let starts: Vec<_> = starts.iter().map(|x| clip(*x, bounds)).collect();
    let mut best = (
        bounded(starts[0], f64::INFINITY),
        starts[0],
        free.is_empty(),
    );
    let mut local_starts = starts.clone();
    // generations = 0 skips DE: Nelder–Mead refines only the given starts.
    for run in 0..if free.is_empty() || generations == 0 {
        0
    } else {
        seeds
    } {
        let mut rng = Random(seed.wrapping_add(run as u64));
        let count = 35;
        let mut population: Vec<Vector> = (0..count)
            .map(|_| {
                std::array::from_fn(|j| bounds[j][0] + rng.unit() * (bounds[j][1] - bounds[j][0]))
            })
            .collect();
        for (i, x) in starts.iter().take(count).enumerate() {
            population[i] = *x;
        }
        let mut costs: Vec<_> = population
            .iter()
            .map(|x| bounded(*x, f64::INFINITY))
            .collect();
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
                for j in 0..NP {
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
                // A trial is kept only at or below costs[i]; values above it
                // may be bounds, which leaves every acceptance unchanged.
                let value = bounded(trial, costs[i]);
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
        let result = local(start, bounds, &mut |x| bounded(x, f64::INFINITY));
        if result.0 < best.0 || (result.0 <= best.0 + 1e-12 && result.2 && !best.2) {
            best = (result.0, result.1, result.2);
        }
    }
    FitResult {
        x: best.1,
        evaluation: config.evaluate(event, best.1, true, f64::INFINITY),
        evaluations: calls,
        converged: best.2,
    }
}

#[pyclass]
pub struct FiniteBinProblem {
    config: Config,
    event: Event,
}
type EvaluationOutput = (f64, usize, f64, Vec<f64>, bool, usize);
type FitOutput = (Vector, f64, usize, f64, Vec<f64>, bool, usize, bool, usize);

fn validate_x(x: &Vector) -> PyResult<()> {
    if x.iter().any(|v| !v.is_finite())
        || [x[0], x[1], x[3], x[5]].iter().any(|v| {
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

fn rows_valid(rows: &[Vec<f64>], e: usize, p: usize) -> bool {
    rows.len() == e && rows.iter().all(|r| r.len() == p)
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
        affected: Vec<Vec<f64>>,
        total: Vec<Vec<f64>>,
        log_exposure: Vec<Vec<f64>>,
        offset: Vec<Vec<f64>>,
        beam_enabled: bool,
        beam_amplitude_bounds: [f64; 2],
        loss: &str,
        huber_delta: f64,
        scale_prior_inv_var: f64,
    ) -> PyResult<Self> {
        let n = weights.len();
        let p = pitch.len().saturating_sub(1);
        let e = low.len();
        let loss = match loss {
            "squared" => Loss::Squared,
            "huber" if huber_delta.is_finite() && huber_delta > 0. => Loss::Huber(huber_delta),
            "binomial" => Loss::Binomial,
            "beta_binomial" => Loss::BetaBinomial,
            _ => return Err(PyValueError::new_err("unknown finite-bin loss")),
        };
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
            || !rows_valid(&reference, e, p)
            || mask.len() != e
            || mask.iter().any(|r| r.len() != p)
            || !rows_valid(&observed, e, p)
            || !rows_valid(&affected, e, p)
            || !rows_valid(&total, e, p)
            || !rows_valid(&log_exposure, e, p)
            || !rows_valid(&offset, e, p)
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
            || offset.iter().flatten().any(|v| !v.is_finite())
            || !beam_amplitude_bounds
                .iter()
                .all(|v| v.is_finite() && *v > 0.)
            || beam_amplitude_bounds[0] > beam_amplitude_bounds[1]
            || !scale_prior_inv_var.is_finite()
            || scale_prior_inv_var < 0.
        {
            return Err(PyValueError::new_err(
                "invalid finite-bin angular response or observations",
            ));
        }
        let mut saturated = vec![vec![0.; p]; e];
        let mut gain = vec![vec![1.; p]; e];
        if loss.counts() {
            for row in 0..e {
                for col in 0..p {
                    if !mask[row][col] {
                        continue;
                    }
                    let (a, t, x) = (affected[row][col], total[row][col], log_exposure[row][col]);
                    if !(a.is_finite() && t.is_finite() && x.is_finite())
                        || a < 0.
                        || t <= 0.
                        || a > t
                    {
                        return Err(PyValueError::new_err(
                            "count losses need 0 <= affected <= total, total > 0 and finite exposure",
                        ));
                    }
                    saturated[row][col] = xlogy_ratio(a, t) + xlogy_ratio(t - a, t);
                    gain[row][col] = (x + offset[row][col] * std::f64::consts::LN_10).exp();
                }
            }
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
                beam_log_amplitude: beam_amplitude_bounds.map(f64::log10),
                loss,
                scale_prior_inv_var,
            },
            event: Event {
                low,
                high,
                reference,
                mask,
                observed,
                affected,
                total,
                offset,
                gain,
                saturated,
            },
        })
    }

    fn evaluate(&self, py: Python<'_>, x: Vector) -> PyResult<EvaluationOutput> {
        validate_x(&x)?;
        let result = py.detach(|| self.config.evaluate(&self.event, x, true, f64::INFINITY));
        if !result.cost.is_finite() || result.prediction.iter().any(|v| !v.is_finite()) {
            return Err(PyValueError::new_err(
                "finite-bin prediction or objective overflow",
            ));
        }
        Ok((
            result.cost,
            result.template,
            result.amplitude,
            result.prediction,
            self.config.barrier_unobserved(&self.event, x),
            self.config.boundary_rows(&self.event, x),
        ))
    }

    fn fit(
        &self,
        py: Python<'_>,
        bounds: [[f64; 2]; NP],
        starts: Vec<Vector>,
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
        let evaluation = &result.evaluation;
        if !evaluation.cost.is_finite() || evaluation.prediction.iter().any(|v| !v.is_finite()) {
            return Err(PyValueError::new_err(
                "finite-bin prediction or objective overflow",
            ));
        }
        Ok((
            result.x,
            evaluation.cost,
            evaluation.template,
            evaluation.amplitude,
            evaluation.prediction.clone(),
            result.converged,
            result.evaluations,
            self.config.barrier_unobserved(&self.event, result.x),
            self.config.boundary_rows(&self.event, result.x),
        ))
    }

    /// Row-level profiled objectives (rho = 1, fitted rho) at fixed beam.
    fn loss_cone_test(
        &self,
        py: Python<'_>,
        x: Vector,
        template: usize,
        amplitude: f64,
        log_concentration_bounds: [f64; 2],
    ) -> PyResult<(f64, f64)> {
        validate_x(&x)?;
        if template > BEAM_SHAPES
            || !amplitude.is_finite()
            || amplitude < 0.
            || log_concentration_bounds.iter().any(|v| !v.is_finite())
            || log_concentration_bounds[0] > log_concentration_bounds[1]
        {
            return Err(PyValueError::new_err("invalid loss-cone test arguments"));
        }
        let result = py.detach(|| {
            self.config.loss_cone_test(
                &self.event,
                x,
                template,
                amplitude,
                log_concentration_bounds,
            )
        });
        if !result.0.is_finite() || !result.1.is_finite() {
            return Err(PyValueError::new_err("loss-cone test objective overflow"));
        }
        Ok(result)
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
            beam_log_amplitude: [0.25_f64.log10(), 8_f64.log10()],
            loss: Loss::Huber(0.1),
            scale_prior_inv_var: 0.,
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

    fn event(affected: f64, total: f64) -> Event {
        let rows = |v: f64| vec![vec![v; 2]; 1];
        let mut saturated = rows(0.);
        saturated[0].fill(xlogy_ratio(affected, total) + xlogy_ratio(total - affected, total));
        Event {
            low: vec![100.],
            high: vec![200.],
            reference: rows(1.),
            mask: vec![vec![true; 2]],
            observed: rows(0.),
            affected: rows(affected),
            total: rows(total),
            offset: rows(0.),
            gain: rows(1.),
            saturated,
        }
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
        for target in [[0.3, -1.2, 0.4, 0., 12., 2.], [-3., 0., 2., 0., 0., 2.]] {
            let bounds = [
                [-3., 3.],
                [-4., 0.],
                [-1., 2.],
                [0., 0.],
                [0., 90.],
                [2., 2.],
            ];
            let mut score = |x: Vector| (0..NP).map(|j| (x[j] - target[j]).powi(2)).sum();
            let (cost, _, converged) = local([1., -0.3, 0.1, 0., 20., 2.], &bounds, &mut score);
            assert!(converged && cost < 1e-9, "{cost}");
        }
    }

    #[test]
    fn count_deviance_is_zero_at_saturation_and_beta_binomial_tends_to_binomial() {
        let mut c = response();
        let ev = event(30., 100.);
        let saturated = 30_f64 / 70.;
        let misfit = saturated * 10_f64.powf(0.2);
        c.loss = Loss::Binomial;
        assert!(c.cell_cost(&ev, 0, 0, saturated, 1., 0.).abs() < 1e-12);
        let off = c.cell_cost(&ev, 0, 0, misfit, 1., 0.);
        assert!(off > 0.);
        c.loss = Loss::BetaBinomial;
        let cost = |phi: f64| c.cell_cost(&ev, 0, 0, misfit, phi, c.norm(&ev, 0, 0, phi));
        let near = cost(1e6);
        assert!((near - off).abs() < 1e-3 * off, "{near} {off}");
        // Overdispersion lowers the penalty of the same misfit.
        assert!(cost(10.) < near);
    }

    #[test]
    fn stirling_ln_gamma_matches_libm() {
        for x in [1e-12, 1e-3, 0.5, 1., 3.7, 6.999, 7., 42.5, 1e3, 1e6] {
            let expected = libm::lgamma(x);
            assert!(
                (ln_gamma(x) - expected).abs() < 1e-10 * expected.abs().max(1.),
                "{x}"
            );
        }
    }

    #[test]
    fn golden_section_finds_interior_and_edge_minima() {
        let (value, at) = golden(-1., 2., 60, |u| (u - 0.7).powi(2));
        assert!(value < 1e-12 && (at - 0.7).abs() < 1e-6);
        let (_, at) = golden(-1., 2., 60, |u| u);
        assert!((at + 1.).abs() < 1e-6);
    }
}
