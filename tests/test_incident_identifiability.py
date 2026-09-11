from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from sopran.analysis.electron_reflection.identifiability import scan_incident_likelihood
from sopran.analysis.electron_reflection.incident import IncidentProblem


class QuadraticProblem:
    """Analytic profile truth with a nuisance coupled to both physical axes."""

    fit = IncidentProblem.fit

    def __init__(self):
        self.layout = SimpleNamespace(model="electrostatic", physical=slice(0, 2))
        self.names = ("ln_field", "delta_u", "nuisance")
        self.bounds = ((-3.0, 3.0), (-10.0, 10.0), (-20.0, 20.0))
        self.initial = np.array([0.4, -2.0, 4.0])
        self.counts = np.ones(10)

    def objective(self, vector):
        b, u, z = vector
        residual = z - 2 * b + u
        return (
            float(b**2 + u**2 + residual**2),
            np.array([2 * b - 4 * residual, 2 * u + 2 * residual, 2 * residual]),
        )


def test_scan_profiles_nuisance_and_preserves_inputs():
    p = QuadraticProblem()
    bounds = p.bounds
    seed = p.initial.copy()
    calls = []
    fields, delta = np.exp([-1.0, 0.0, 1.0]), np.array([-2.0, 0.0, 2.0])
    result = scan_incident_likelihood(
        p,
        field_nT=fields,
        delta_u_eV=delta,
        seeds=[seed],
        on_point=lambda *args: calls.append(args[:3]),
    )
    np.testing.assert_allclose(
        result.nll, delta[:, None] ** 2 + np.log(fields)[None, :] ** 2, atol=1e-8
    )
    np.testing.assert_allclose(
        result.vectors[:, :, 2], 2 * np.log(fields)[None, :] - delta[:, None], atol=1e-5
    )
    assert result.baseline.nll < 1e-8
    assert np.all(result.consistent)
    assert not np.any(result.nuisance_at_bounds)
    assert len(calls) == 18
    assert p.bounds == bounds
    np.testing.assert_array_equal(p.initial, seed)
    np.testing.assert_array_equal(seed, [0.4, -2.0, 4.0])


def test_failed_points_are_not_likelihood_evidence():
    p = QuadraticProblem()
    real_fit = p.fit

    # Bind the wrapper to each copied instance, not to the original bounds.
    class Failure(QuadraticProblem):
        def fit(self, seeds, **kwargs):
            result = IncidentProblem.fit(self, seeds, **kwargs)
            if self.bounds[0] == (0.0, 0.0):
                return replace(result, success=False)
            return result

    result = scan_incident_likelihood(
        Failure(), field_nT=np.exp([-1, 0, 1]), delta_u_eV=[-1, 1], seeds=[p.initial]
    )
    assert np.all(np.isfinite(result.nll))
    assert np.all(np.isnan(result.twice_delta_nll[:, 1]))
    assert np.all(np.isfinite(result.twice_delta_nll[:, [0, 2]]))
    inconsistent = replace(result, baseline=replace(real_fit([p.initial]), nll=100.0))
    assert not np.any(inconsistent.consistent)
    assert np.all(np.isnan(inconsistent.twice_delta_nll))


@pytest.mark.parametrize(
    "field,delta",
    [([0, 1], [-1, 1]), ([1, 1], [-1, 1]), ([1, 2], [0, np.nan]), ([1, 1000], [-1, 1])],
)
def test_invalid_grids(field, delta):
    p = QuadraticProblem()
    with pytest.raises(ValueError):
        scan_incident_likelihood(p, field_nT=field, delta_u_eV=delta, seeds=[p.initial])


def test_actual_incident_native_scan():
    pytest.importorskip("sopran._native")
    from test_incident_reflection import make_problem

    p, seed = make_problem()
    baseline = p.fit([seed])
    original = p.bounds
    b, u = np.exp(baseline.vector[0]), baseline.vector[1]
    fields = np.unique(np.clip(b * np.array([0.95, 1.05]), *np.exp(p.bounds[0])))
    delta = np.unique(np.clip(np.array([u - 2, u + 2]), *p.bounds[1]))
    result = scan_incident_likelihood(p, field_nT=fields, delta_u_eV=delta, seeds=[baseline.vector])
    assert p.bounds == original
    for j in range(len(delta)):
        for i in range(len(fields)):
            vector = result.vectors[j, i]
            assert np.exp(vector[0]) == pytest.approx(fields[i])
            assert vector[1] == pytest.approx(delta[j])
            assert p.objective(vector)[0] == pytest.approx(result.nll[j, i])


def test_log_field_endpoint_roundtrip_is_allowed_and_clamped():
    p = QuadraticProblem()
    p.bounds = ((-0.1, 0.3), *p.bounds[1:])
    fields = np.exp([-0.1, 0.0, 0.3])
    assert np.log(fields[0]) < p.bounds[0][0]
    scan = scan_incident_likelihood(p, field_nT=fields, delta_u_eV=[-1, 1], seeds=[p.initial])
    np.testing.assert_array_equal(scan.vectors[:, 0, 0], [-0.1, -0.1])
    np.testing.assert_array_equal(scan.vectors[:, -1, 0], [0.3, 0.3])
    with pytest.raises(ValueError, match="original physical bounds"):
        scan_incident_likelihood(
            p, field_nT=np.exp([-0.1001, 0.3]), delta_u_eV=[-1, 1], seeds=[p.initial]
        )
