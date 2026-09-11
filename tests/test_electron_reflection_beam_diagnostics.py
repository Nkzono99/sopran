from dataclasses import replace

import numpy as np
import pytest

from sopran.experimental.electron_reflection import global_joint as gj
from sopran.experimental.electron_reflection.beam_diagnostics import (
    decompose_global_joint_beam,
    plot_global_joint_beam_decomposition,
)


def case(beam=True):
    settings = gj.GlobalJointFitSettings(
        loss_cone_model="shared", edge_transition="hard", spectrum_knots=4
    )
    edges = np.linspace(0, 180, 17)
    counts = np.full((12, 16), 100.0)
    counts[2:6, :8] = 0
    observations = {
        name: gj.GlobalPitchCountObservation(
            energy_eV=np.geomspace(40, 1200, 12),
            pitch_deg=(edges[:-1] + edges[1:]) / 2,
            pitch_edges_deg=edges,
            counts=counts,
            exposure=np.ones_like(counts),
            b_sc_nT=5.0,
            affected_side="low",
        )
        for name in ("S1", "S2")
    }
    prepared = tuple(gj._prepare_observation(n, o, settings) for n, o in observations.items())
    fit = gj._fit_candidate(
        prepared,
        "mirror_only",
        "constant",
        settings,
        beam_enabled=beam,
        transition_model="hard",
        free_parameters=(),
    )
    return observations, fit, settings


def test_decomposition_preserves_counts_and_signed_subtraction():
    observations, fit, settings = case()
    d = decompose_global_joint_beam(observations, fit, settings=settings)
    np.testing.assert_allclose(d.reflected_counts + d.beam_counts, d.full_fov.fitted_counts)
    np.testing.assert_allclose(
        d.observed_minus_beam_counts + d.beam_counts, d.full_fov.corrected_counts
    )
    assert np.any(d.observed_minus_beam_counts < 0)
    assert np.all(d.beam_counts >= 0)
    split = len(d.full_fov.pitch_deg) // 2
    np.testing.assert_allclose(d.beam_counts[:, split:], 0, atol=1.0e-12)
    np.testing.assert_allclose(
        d.folded_observed_ratio - d.folded_beam_over_observed_reference,
        d.folded_observed_minus_beam_ratio,
        equal_nan=True,
    )


def test_disabled_beam_is_identity():
    observations, fit, settings = case(False)
    d = decompose_global_joint_beam(observations, fit, settings=settings)
    np.testing.assert_array_equal(d.beam_counts, 0.0)
    np.testing.assert_allclose(d.observed_minus_beam_counts, d.full_fov.corrected_counts)


def test_detector_response_subtracts_beam_from_both_hemispheres():
    observations, _, settings = case()
    response = np.eye(12 * 16)
    for energy in range(12):
        response[energy * 16 + 15, energy * 16] = 0.5
    observations = {
        n: replace(o, detector_response_matrix=response) for n, o in observations.items()
    }
    prepared = tuple(gj._prepare_observation(n, o, settings) for n, o in observations.items())
    fit = gj._fit_candidate(
        prepared,
        "mirror_only",
        "constant",
        settings,
        beam_enabled=True,
        transition_model="hard",
        free_parameters=(),
    )
    d = decompose_global_joint_beam(observations, fit, settings=settings)
    split = len(d.full_fov.pitch_deg) // 2
    assert np.any(d.beam_counts[:, split:] > 0)
    signed = d.observed_minus_beam_counts + settings.normalized_rate_prior_count
    rate = np.divide(
        signed,
        d.full_fov.normalized_exposure,
        out=np.full_like(signed, np.nan),
        where=d.full_fov.normalized_exposure > 0,
    )
    reference = rate[:, split:][:, ::-1]
    expected = np.divide(
        rate[:, :split],
        reference,
        out=np.full_like(reference, np.nan),
        where=reference > 0,
    )
    np.testing.assert_allclose(d.folded_observed_minus_beam_ratio, expected)


def test_subtraction_keeps_missing_cells_and_plots(tmp_path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    observations, _, settings = case()
    observations = {
        n: replace(o, exposure=np.where(np.arange(16)[None, :] == 15, 0.0, np.ones((12, 16))))
        for n, o in observations.items()
    }
    prepared = tuple(gj._prepare_observation(n, o, settings) for n, o in observations.items())
    fit = gj._fit_candidate(
        prepared,
        "mirror_only",
        "constant",
        settings,
        beam_enabled=True,
        transition_model="hard",
        free_parameters=(),
    )
    d = decompose_global_joint_beam(observations, fit, settings=settings)
    assert np.any(~np.isfinite(d.folded_observed_minus_beam_ratio))
    fig = plot_global_joint_beam_decomposition(d, title="Synthetic")
    path = tmp_path / "beam.png"
    fig.savefig(path, dpi=60)
    plt.close(fig)
    assert path.stat().st_size > 10000


def test_fold_plot_marks_negative_counts_hidden_by_display_prior():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    observations, fit, settings = case()
    d = decompose_global_joint_beam(observations, fit, settings=settings)
    split = len(d.full_fov.pitch_deg) // 2
    residual = d.observed_minus_beam_counts
    negative = (residual[:, :split] < 0) | (residual[:, split:][:, ::-1] < 0)
    exposure = d.full_fov.normalized_exposure
    supported = (exposure[:, :split] > 0) & (exposure[:, split:][:, ::-1] > 0)
    assert np.any(negative & (d.folded_observed_minus_beam_ratio > 0))
    fig = plot_global_joint_beam_decomposition(d)
    overlay = fig.axes[7].collections[1].get_array()
    np.testing.assert_array_equal(~np.ma.getmaskarray(overlay), negative & supported)
    plt.close(fig)


def test_nonadditive_deadtime_and_wrong_layout_rejected():
    observations, fit, settings = case()
    with pytest.raises(ValueError, match="do not match"):
        decompose_global_joint_beam(observations, fit, settings=replace(settings, spectrum_knots=5))
    observations = {
        n: replace(o, dead_time_seconds=1.0e-6, live_time_capacity_seconds=np.ones_like(o.counts))
        for n, o in observations.items()
    }
    with pytest.raises(ValueError, match="zero dead time"):
        decompose_global_joint_beam(observations, fit, settings=settings)
