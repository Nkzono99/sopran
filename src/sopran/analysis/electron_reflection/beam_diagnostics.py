"""Count-space decomposition of a fitted global ER beam (no refitting)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from . import global_joint as gj

if TYPE_CHECKING:
    from matplotlib.figure import Figure

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class GlobalJointBeamDecomposition:
    """Conditional model subtraction, not a new count sample or likelihood."""

    fit: gj.GlobalJointModelFit
    full_fov: gj.GlobalFullFOV
    reflected_counts: FloatArray
    beam_counts: FloatArray
    observed_minus_beam_counts: FloatArray
    folded_observed_ratio: FloatArray
    folded_observed_minus_beam_ratio: FloatArray
    folded_beam_over_observed_reference: FloatArray
    folded_reflected_model_ratio: FloatArray
    display_prior_count: float
    representative_b_sc_nT: float
    spacecraft_potential_eV: float


def _divide(values: FloatArray, exposure: FloatArray) -> FloatArray:
    return np.divide(values, exposure, out=np.full_like(values, np.nan), where=exposure > 0)


def decompose_global_joint_beam(
    observations: Mapping[str, gj.GlobalPitchCountObservation],
    fit: gj.GlobalJointModelFit,
    *,
    settings: gj.GlobalJointFitSettings,
) -> GlobalJointBeamDecomposition:
    """Remove fitted beam in count space, retaining negative residual counts.

    Use the observations and settings used to fit this candidate. Folded data
    ratios use the configured additive display pseudocount on both sides;
    subtracting the beam does not generate a new Poisson/NB observation or
    propagate parameter uncertainty. Nonlinear dead-time responses are not
    supported by this additive decomposition.
    """
    if not fit.success:
        raise ValueError("A successful candidate fit is required")
    prepared = tuple(
        gj._prepare_observation(name, obs, settings) for name, obs in observations.items()
    )
    prepared = tuple(obs for obs in prepared if np.any(obs.valid))
    if any(obs.dead_time_seconds != 0 for obs in prepared):
        raise ValueError("Additive beam decomposition requires zero dead time")
    problem = gj._build_problem(
        prepared,
        fit.model,
        fit.contrast_model,
        settings,
        beam_enabled=fit.secondary_beam_enabled,
        transition_model=fit.transition_model,
    )
    if problem.names != fit._parameter_names:
        raise ValueError("Fit parameters do not match the supplied settings/observations")
    vector = np.asarray(fit._parameter_values, dtype=float)
    full = gj._global_full_fov(vector, problem)
    without_beam = vector.copy()
    if problem.layout.beam is not None:
        without_beam[problem.layout.beam.start] = -np.inf
    reflected = gj._global_full_fov(without_beam, problem)
    beam_counts = np.maximum(full.fitted_counts - reflected.fitted_counts, 0.0)
    remainder = full.corrected_counts - beam_counts
    split = np.flatnonzero(np.isclose(full.pitch_edges_deg, 90.0)).item()

    def halves(values: FloatArray) -> tuple[FloatArray, FloatArray]:
        return values[:, :split], values[:, split:][:, ::-1]

    a, r = halves(full.corrected_counts)
    na, nr = halves(full.normalized_exposure)
    ba, br = halves(beam_counts)
    fa, fr = halves(reflected.fitted_counts)
    prior = settings.normalized_rate_prior_count
    reference = _divide(r + prior, nr)
    observed = _divide(_divide(a + prior, na), reference)
    beam_ratio = _divide(_divide(ba, na), reference)
    # A detector response can spread the outgoing beam into reference cells.
    remaining_reference = _divide(r + prior - br, nr)
    remaining = _divide(_divide(a + prior - ba, na), remaining_reference)
    reflected_ratio = _divide(_divide(fa, na), _divide(fr, nr))
    return GlobalJointBeamDecomposition(
        fit,
        full,
        reflected.fitted_counts,
        beam_counts,
        remainder,
        observed,
        remaining,
        beam_ratio,
        reflected_ratio,
        prior,
        float(np.median([obs.b_sc_nT for obs in prepared])),
        settings.effective_field.spacecraft_potential_eV,
    )


def plot_global_joint_beam_decomposition(
    decomposition: GlobalJointBeamDecomposition,
    *,
    comparison_fit: gj.GlobalJointModelFit | None = None,
    title: str = "",
) -> Figure:
    """Plot total/beam/reflected surfaces and conditional beam-subtracted data.

    This is a companion diagnostic to ``plot_global_joint_effective_field_fit``.
    Gray denotes missing support / an unusable denominator. Magenta denotes
    negative residual counts before the display pseudocount, on either side
    of the fold. Neither negative values nor missing cells are clipped
    into apparently successful positive observations.
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    d = decomposition
    full = d.full_fov
    split = d.folded_observed_ratio.shape[1]
    values = (
        _divide(full.corrected_counts, full.normalized_exposure),
        _divide(full.fitted_counts, full.normalized_exposure),
        _divide(d.beam_counts, full.normalized_exposure),
        _divide(d.observed_minus_beam_counts, full.normalized_exposure),
        _divide(d.reflected_counts, full.normalized_exposure),
        _divide(d.beam_counts, full.fitted_counts),
        d.folded_observed_ratio,
        d.folded_observed_minus_beam_ratio,
        d.folded_reflected_model_ratio,
    )
    titles = (
        "Global FOV: observed",
        "Global FOV: total model",
        "Global FOV: predicted beam",
        "Observed minus predicted beam",
        "Reflected model (beam set to zero)",
        "Beam / total model",
        "Folded observed (stabilized display)",
        "Folded observed minus beam",
        "Folded reflected model",
    )
    fig, axes = plt.subplots(3, 3, figsize=(17, 12), layout="constrained")
    cmap = plt.get_cmap("RdBu_r").with_extremes(bad="#555555")
    for index, (ax, value, label) in enumerate(zip(axes.flat, values, titles, strict=True)):
        edges = full.pitch_edges_deg[: split + 1] if index >= 6 else full.pitch_edges_deg
        if index == 5:
            mesh = ax.pcolormesh(
                edges,
                full.energy_edges_eV,
                value,
                cmap=plt.get_cmap("viridis").with_extremes(bad="#555555"),
                vmin=0,
                vmax=1,
            )
            bar_label = "Fraction of predicted counts"
        else:
            logged = np.full_like(value, np.nan)
            finite = np.isfinite(value)
            logged[finite] = np.log10(np.maximum(value[finite], 1.0e-4))
            mesh = ax.pcolormesh(edges, full.energy_edges_eV, logged, cmap=cmap, vmin=-2, vmax=2)
            bar_label = "log10(affected/reference)" if index >= 6 else "log10(normalized rate)"
            if index in (3, 7):
                residual = d.observed_minus_beam_counts
                negative_counts = residual < 0
                usable = full.normalized_exposure > 0
                if index == 7:
                    negative_counts = (
                        negative_counts[:, :split] | negative_counts[:, split:][:, ::-1]
                    )
                    usable = usable[:, :split] & usable[:, split:][:, ::-1]
                negative = np.ma.masked_where(~(usable & negative_counts), np.ones_like(value))
                ax.pcolormesh(
                    edges,
                    full.energy_edges_eV,
                    negative,
                    cmap=ListedColormap(["#be4b91"]),
                    vmin=0,
                    vmax=1,
                )
        fig.colorbar(mesh, ax=ax, label=bar_label)
        ax.set(
            title=label,
            yscale="log",
            ylim=(full.energy_edges_eV[0], full.energy_edges_eV[-1]),
            xlabel="Folded pitch [deg]"
            if index >= 6
            else "Moon-oriented pitch [deg] (0: outgoing)",
            ylabel="Energy [eV]",
        )
        if index >= 6:
            energy = np.geomspace(full.energy_edges_eV[0], full.energy_edges_eV[-1], 256)
            for fit, color, style, line_label in (
                (d.fit, "black", "-", "Decomposed fit: " + d.fit.model),
                (comparison_fit, "#ba5b00", "--", "Comparison candidate"),
            ):
                if fit is None or fit.mirror_ratio is None:
                    continue
                boundary = gj.mirror_boundary_sin2(
                    energy,
                    fit.mirror_ratio,
                    fit.delta_u_eff_eV or 0.0,
                    spacecraft_potential_eV=d.spacecraft_potential_eV,
                )
                angle = np.where(
                    (boundary > 0) & (boundary < 1),
                    np.degrees(np.arcsin(np.sqrt(np.clip(boundary, 0, 1)))),
                    np.nan,
                )
                ax.plot(angle, energy, color=color, ls=style, label=line_label)
            if ax.get_legend_handles_labels()[0]:
                ax.legend(fontsize=8)
    fit = d.fit
    beam_label = (
        f"beam E={fit.beam_center_eV:.1f} eV, sigma_pitch={fit.beam_sigma_pitch_deg:.1f} deg"
        if fit.secondary_beam_enabled
        else "beam disabled"
    )
    fig.suptitle(
        f"{title} | {fit.model} | {beam_label}\n"
        "Conditional count-space subtraction, NOT a refit; signed residual counts retained. "
        f"Folded display pseudocount={d.display_prior_count:g}; "
        "no beam-parameter uncertainty propagated.",
        fontsize=11,
    )
    axes[0, 0].legend(
        handles=[
            Patch(color="#555555", label="Missing / unusable denominator"),
            Patch(color="#be4b91", label="Negative after subtraction"),
            Patch(color=cmap(0.0), label="Zero / below color range"),
        ],
        fontsize=7,
    )
    return fig
