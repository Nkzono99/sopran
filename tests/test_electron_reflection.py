from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from scipy.special import ndtr

from sopran.experimental.electron_reflection import (
    BinaryLossConeFitSettings,
    EffectiveFieldFitSettings,
    EffectiveFieldQualitySettings,
    ElectronReflectionCounts,
    GlobalJointFitSettings,
    GlobalJointModelFit,
    GlobalPitchCountObservation,
    HalekasFitSettings,
    fit_binary_loss_cone,
    fit_effective_field,
    fit_global_joint_effective_field,
    fit_halekas_distribution,
    fit_joint_effective_field,
    mirror_boundary_sin2,
    mirror_transmission_probability,
    plot_global_joint_circular_pitch_view,
    plot_global_joint_effective_field_fit,
    plot_joint_effective_field_fit,
    simulate_electron_reflection_counts,
)

pytest.importorskip("scipy")


def test_global_joint_settings_consider_secondary_beam_by_default() -> None:
    settings = GlobalJointFitSettings()

    assert settings.secondary_beam == "auto"
    assert settings.energy_bounds_eV == (20.0, 1_500.0)
    assert settings.edge_transition == "hard"
    assert settings.hemisphere_baseline_knots == 4
    assert settings.normalized_rate_prior_count == 0.5
    assert settings.normalized_max_log10_std == 0.5
    assert settings.energy_response_samples == 8
    assert settings.pitch_response_samples == 64
    assert settings.smooth_screening
    assert settings.smooth_screen_pitch_samples == 8
    assert settings.contrast_screening
    assert settings.contrast_screen_pitch_samples == 8
    assert settings.beam_screening
    assert settings.beam_screen_pitch_samples == 8
    assert settings.effective_field.min_edge_delta_bic == 6.0
    assert settings.effective_field.min_electrostatic_delta_bic == 1.0
    assert BinaryLossConeFitSettings().min_electrostatic_delta_bic == 1.0


def test_global_joint_settings_reject_nonfinite_beam_threshold() -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        GlobalJointFitSettings(min_secondary_beam_delta_bic=float("nan"))


def test_global_joint_settings_reject_nonpositive_rate_prior() -> None:
    with pytest.raises(ValueError, match="normalized_rate_prior_count"):
        GlobalJointFitSettings(normalized_rate_prior_count=0.0)
    with pytest.raises(ValueError, match="normalized_max_log10_std"):
        GlobalJointFitSettings(normalized_max_log10_std=0.0)

    with pytest.raises(ValueError, match="hemisphere_baseline_knots"):
        GlobalJointFitSettings(hemisphere_baseline_knots=1)

    with pytest.raises(ValueError, match="energy_bounds_eV"):
        GlobalJointFitSettings(energy_bounds_eV=(1_500.0, 20.0))

    with pytest.raises(ValueError, match="energy_bounds_eV"):
        GlobalJointFitSettings(energy_bounds_eV=(20.0, float("inf")))


def test_physical_pitch_orientation_places_affected_hemisphere_on_left() -> None:
    from sopran.experimental.electron_reflection.global_joint import _orient_pitch_surface

    pitch = np.asarray([10.0, 60.0, 120.0, 170.0])
    values = np.asarray([[1.0, 2.0, 3.0, 4.0]])

    physical_pitch, physical_values = _orient_pitch_surface(
        pitch,
        values,
        affected_side="high",
        orientation="physical",
    )
    native_pitch, native_values = _orient_pitch_surface(
        pitch,
        values,
        affected_side="high",
        orientation="native",
    )

    np.testing.assert_allclose(physical_pitch, pitch)
    np.testing.assert_allclose(physical_values, values[:, ::-1])
    np.testing.assert_allclose(native_pitch, pitch)
    np.testing.assert_allclose(native_values, values)


def test_prepared_global_observation_preserves_declared_affected_side() -> None:
    from sopran.experimental.electron_reflection.global_joint import _prepare_observation

    settings = GlobalJointFitSettings(
        spectrum_knots=4,
        hemisphere_baseline_knots=2,
        secondary_beam="off",
    )
    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([100.0, 200.0, 300.0]),
        pitch_deg=np.asarray([100.0, 120.0, 140.0, 160.0]),
        counts=np.ones((3, 4)),
        exposure=np.ones((3, 4)),
        b_sc_nT=5.0,
        affected_side="low",
    )

    prepared = _prepare_observation("partial", observation, settings)

    assert prepared.affected_side == "low"
    assert not np.any(prepared.affected)


def test_prepared_global_observation_uses_configured_energy_range() -> None:
    from sopran.experimental.electron_reflection.global_joint import _prepare_observation

    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([10.0, 20.0, 1_500.0, 2_000.0]),
        pitch_deg=np.asarray([45.0, 135.0]),
        counts=np.ones((4, 2)),
        exposure=np.ones((4, 2)),
        b_sc_nT=5.0,
        affected_side="low",
    )

    prepared = _prepare_observation("ESA-S1", observation, GlobalJointFitSettings())

    assert np.all(~prepared.valid[[0, 3]])
    assert np.all(prepared.valid[[1, 2]])


def test_global_joint_rejects_insufficient_energy_pitch_support() -> None:
    pitch = np.linspace(10.0, 170.0, 8)
    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([100.0, 200.0]),
        pitch_deg=pitch,
        counts=np.full((2, 8), 10.0),
        exposure=np.ones((2, 8)),
        b_sc_nT=5.0,
        affected_side="low",
    )

    with pytest.raises(ValueError, match="fewer than 3 energy rows"):
        fit_global_joint_effective_field(
            {"ESA-S1": observation, "ESA-S2": observation},
            settings=GlobalJointFitSettings(
                spectrum_knots=4,
                hemisphere_baseline_knots=2,
                secondary_beam="off",
            ),
        )


def test_global_support_is_aggregated_across_records_within_each_sensor() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _prepare_observation,
        _validate_global_support,
    )

    settings = GlobalJointFitSettings(
        spectrum_knots=4,
        hemisphere_baseline_knots=2,
        secondary_beam="off",
    )
    pitch = np.linspace(10.0, 170.0, 8)
    prepared = []
    for sensor in ("ESA-S1", "ESA-S2"):
        for record in range(2):
            counts = np.full((3, 8), 10.0)
            exposure = np.ones((3, 8))
            missing = slice(4, None) if record == 0 else slice(None, 4)
            counts[:, missing] = np.nan
            exposure[:, missing] = np.nan
            observation = GlobalPitchCountObservation(
                energy_eV=np.asarray([100.0, 200.0, 300.0]),
                pitch_deg=pitch,
                counts=counts,
                exposure=exposure,
                b_sc_nT=5.0,
                affected_side="low",
                sensor_group=sensor,
            )
            prepared.append(
                _prepare_observation(f"{sensor}:{record}", observation, settings)
            )

    _validate_global_support(tuple(prepared), settings)


def test_global_observation_refuses_to_collapse_independent_records() -> None:
    xr = pytest.importorskip("xarray")
    pitch = np.asarray([30.0, 90.0, 150.0])
    values = np.asarray(
        [
            [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
            [[10.0, 20.0, 30.0], [40.0, 50.0, 60.0]],
        ]
    )
    exposure = np.ones_like(values)
    detector_samples = np.full_like(values, 2.0)
    spectrum = xr.DataArray(
        values,
        dims=("time", "energy", "pitch_angle"),
        coords={
            "time": np.asarray(
                ["2008-01-01T00:00:00", "2008-01-01T00:00:02"],
                dtype="datetime64[ns]",
            ),
            "energy_eV": (
                ("time", "energy"),
                np.asarray([[100.0, 200.0], [100.0, 250.0]]),
            ),
            "pitch_angle": pitch,
            "exposure": (("time", "energy", "pitch_angle"), exposure),
            "detector_samples": (
                ("time", "energy", "pitch_angle"),
                detector_samples,
            ),
            "integration_time_seconds": ("time", np.asarray([0.5, 1.0])),
        },
        attrs={"value": "counts", "units": "count", "count_correction": "event_trash"},
    )
    spectrum.coords["exposure"].attrs["mode"] = "calibrated"

    with pytest.raises(ValueError, match="no longer aggregates native records"):
        GlobalPitchCountObservation.from_spectrum_window(
            spectrum,
            indices=(0, 1),
            b_sc_nT=8.0,
            affected_side="low",
        )

    observations = [
        GlobalPitchCountObservation.from_spectrum(
            spectrum,
            index=index,
            b_sc_nT=8.0,
            affected_side="low",
        )
        for index in range(2)
    ]
    np.testing.assert_allclose(observations[0].counts, values[0])
    np.testing.assert_allclose(observations[1].counts, values[1])
    assert all(item.metadata["integrated_records"] == 1 for item in observations)


def test_global_joint_rejects_disconnected_sensor_energy_support() -> None:
    pitch = np.linspace(10.0, 170.0, 8)

    def observation(energy: np.ndarray) -> GlobalPitchCountObservation:
        return GlobalPitchCountObservation(
            energy_eV=energy,
            pitch_deg=pitch,
            counts=np.full((energy.size, pitch.size), 10.0),
            exposure=np.ones((energy.size, pitch.size)),
            b_sc_nT=5.0,
            affected_side="low",
        )

    with pytest.raises(ValueError, match="not overlap-connected"):
        fit_global_joint_effective_field(
            {
                "ESA-S1": observation(np.geomspace(10.0, 40.0, 4)),
                "ESA-S2": observation(np.geomspace(1_000.0, 4_000.0, 4)),
            },
            settings=GlobalJointFitSettings(
                spectrum_knots=4,
                hemisphere_baseline_knots=2,
                energy_bounds_eV=(1.0, 5_000.0),
                secondary_beam="off",
            ),
        )


def test_global_boundary_support_combines_complementary_sensor_pitch_coverage() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _global_boundary_support,
        _prepare_observation,
    )

    settings = GlobalJointFitSettings(
        spectrum_knots=4,
        hemisphere_baseline_knots=2,
        normalized_energy_bins=4,
        secondary_beam="off",
    )
    energy = np.asarray([100.0, 200.0, 300.0])

    def prepared(name: str, pitch: np.ndarray):
        observation = GlobalPitchCountObservation(
            energy_eV=energy,
            pitch_deg=pitch,
            counts=np.ones((energy.size, pitch.size)),
            exposure=np.ones((energy.size, pitch.size)),
            b_sc_nT=5.0,
            affected_side="low",
        )
        return _prepare_observation(name, observation, settings)

    fraction, strict_fraction = _global_boundary_support(
        (
            prepared("below", np.asarray([10.0, 20.0])),
            prepared("above", np.asarray([40.0, 50.0])),
        ),
        20.0,
        None,
        spacecraft_potential_eV=0.0,
        min_transition_energy_bins=3,
        normalized_energy_bins=4,
    )

    assert fraction == pytest.approx(1.0)
    assert strict_fraction == pytest.approx(1.0)


def test_global_boundary_support_does_not_count_repeated_pitch_bins_twice() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _global_boundary_support,
        _prepare_observation,
    )

    settings = GlobalJointFitSettings(
        spectrum_knots=4,
        hemisphere_baseline_knots=2,
        normalized_energy_bins=4,
        secondary_beam="off",
    )
    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([100.0, 200.0, 300.0]),
        pitch_deg=np.asarray([20.0, 40.0, 140.0, 160.0]),
        counts=np.ones((3, 4)),
        exposure=np.ones((3, 4)),
        b_sc_nT=5.0,
        affected_side="low",
        sensor_group="ESA-S1",
    )
    prepared = _prepare_observation("record-0", observation, settings)

    fraction, strict_fraction = _global_boundary_support(
        (prepared, replace(prepared, name="record-1")),
        20.0,
        None,
        spacecraft_potential_eV=0.0,
        min_transition_energy_bins=3,
        normalized_energy_bins=4,
    )

    assert fraction == pytest.approx(1.0)
    assert strict_fraction == pytest.approx(0.0)


def _global_model_fit(
    model: str,
    bic: float,
    *,
    at_bounds: tuple[str, ...] = (),
) -> GlobalJointModelFit:
    edge = model != "no_edge"
    return GlobalJointModelFit(
        model=model,  # type: ignore[arg-type]
        contrast_model="constant" if edge else "none",
        success=True,
        reason="ok",
        mirror_ratio=4.0 if edge else None,
        delta_u_eff_eV=-45.0 if model == "electrostatic" else None,
        sigma_ln_b=0.2 if edge else None,
        secondary_beam_enabled=False,
        beam_amplitude=None,
        beam_center_eV=None,
        beam_sigma_ln_energy=None,
        beam_sigma_pitch_deg=None,
        secondary_beam_delta_bic=float("nan"),
        log_likelihood=-0.5 * bic,
        bic=bic,
        n_parameters=1,
        n_cells=100,
        at_bounds=at_bounds,
        sensors=(),
        normalized_flux=None,
        boundary_bracket_fraction=1.0 if edge else None,
        strict_boundary_bracket_fraction=1.0 if edge else None,
    )


def test_combined_global_fov_keeps_zero_count_exposure_in_denominator() -> None:
    from sopran.experimental.electron_reflection import GlobalNormalizedFlux, GlobalSensorFit
    from sopran.experimental.electron_reflection.global_joint import _combined_full_fov

    energy = np.asarray([100.0, 200.0])
    pitch = np.asarray([45.0, 135.0])
    shape = (2, 2)

    def sensor(name: str, observed: float, exposure: float) -> GlobalSensorFit:
        observed_linear = np.full(shape, observed)
        observed_log = np.log(observed) if observed > 0.0 else np.nan
        return GlobalSensorFit(
            name=name,
            energy_eV=energy,
            pitch_deg=pitch,
            affected_side="low",
            valid=np.ones(shape, dtype=bool),
            observed_log_rate=np.full(shape, observed_log),
            fitted_log_rate=np.zeros(shape),
            observed_log_normalized_flux=np.full(shape, observed_log),
            fitted_log_normalized_flux=np.zeros(shape),
            standardized_residual=np.zeros(shape),
            sensor_gain=1.0,
            dispersion=100.0,
            background_rate_hz=0.0,
            dead_time_seconds=0.0,
            response_kind="identity",
            total_counts=int(observed * exposure * np.prod(shape)),
            n_cells=int(np.prod(shape)),
            exposure=np.full(shape, exposure),
            observed_normalized_flux=observed_linear,
            energy_edges_eV=np.asarray([70.0, 140.0, 280.0]),
            pitch_edges_deg=np.asarray([0.0, 90.0, 180.0]),
        )

    normalized = GlobalNormalizedFlux(
        energy_eV=energy,
        pitch_deg=np.asarray([45.0]),
        observed_log_ratio=np.zeros((2, 1)),
        fitted_log_ratio=np.zeros((2, 1)),
        affected_exposure=np.ones((2, 1)),
        reference_exposure=np.ones((2, 1)),
    )
    fit = replace(
        _global_model_fit("mirror_only", 100.0),
        sensors=(sensor("zero", 0.0, 100.0), sensor("one", 1.0, 1.0)),
        normalized_flux=normalized,
    )

    _, _, observed_log, fitted_log, exposure = _combined_full_fov(
        fit,
        orientation="native",
    )

    np.testing.assert_allclose(np.exp(observed_log), 1.0 / 101.0)
    np.testing.assert_allclose(np.exp(fitted_log), 1.0)
    assert np.all(exposure > 0.0)


def test_global_joint_auto_selects_resolution_limited_hard_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sopran.experimental.electron_reflection import global_joint

    def fake_fit_candidate(
        observations: object,
        model: str,
        contrast_model: str,
        settings: GlobalJointFitSettings,
        *,
        beam_enabled: bool,
        transition_model: str,
        **kwargs: object,
    ) -> GlobalJointModelFit:
        del observations, contrast_model, settings, kwargs
        assert not beam_enabled
        bic = 100.0 if transition_model == "hard" else 99.0
        return replace(
            _global_model_fit(model, bic),
            sigma_ln_b=None if transition_model == "hard" else 0.2,
            transition_model=transition_model,
            at_bounds=() if transition_model == "hard" else ("sigma_ln_b",),
        )

    monkeypatch.setattr(
        global_joint,
        "_fit_candidate",
        fake_fit_candidate,
    )

    selected = global_joint._fit_candidate_with_beam(
        (),
        "mirror_only",
        "constant",
        GlobalJointFitSettings(
            edge_transition="auto",
            smooth_screening=False,
            secondary_beam="off",
        ),
    )

    assert selected.transition_model == "hard"
    assert selected.sigma_ln_b is None
    assert selected.smooth_transition_delta_bic == pytest.approx(1.0)


def test_global_contrast_family_is_selected_per_edge_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sopran.experimental.electron_reflection import global_joint

    def fake_fit_transition_without_beam(
        observations: object,
        model: str,
        contrast_model: str,
        settings: GlobalJointFitSettings,
        **kwargs: object,
    ) -> GlobalJointModelFit:
        del observations, settings, kwargs
        bic = {
            ("mirror_only", "constant"): 100.0,
            ("mirror_only", "band"): 90.0,
            ("electrostatic", "constant"): 120.0,
            ("electrostatic", "band"): 100.0,
        }[(model, contrast_model)]
        return replace(
            _global_model_fit(model, bic),
            contrast_model=contrast_model,
            at_bounds=("effective_field_nT",)
            if model == "mirror_only" and contrast_model == "band"
            else (),
        )

    monkeypatch.setattr(
        global_joint,
        "_fit_transition_without_beam",
        fake_fit_transition_without_beam,
    )
    monkeypatch.setattr(
        global_joint,
        "_fit_selected_beam",
        lambda observations, selected, settings: selected,
    )
    settings = GlobalJointFitSettings(
        effective_field=EffectiveFieldFitSettings(contrast_model="auto"),
        contrast_screening=False,
    )

    mirror, mirror_delta, mirror_screen_delta, mirror_refined = (
        global_joint._fit_edge_contrast(
            (),
            "mirror_only",
            settings,
        )
    )
    electrostatic, electrostatic_delta, electrostatic_screen_delta, electrostatic_refined = (
        global_joint._fit_edge_contrast(
            (),
            "electrostatic",
            settings,
        )
    )

    assert mirror.contrast_model == "constant"
    assert mirror_delta == pytest.approx(10.0)
    assert np.isnan(mirror_screen_delta)
    assert mirror_refined
    assert electrostatic.contrast_model == "band"
    assert electrostatic_delta == pytest.approx(20.0)
    assert np.isnan(electrostatic_screen_delta)
    assert electrostatic_refined


@pytest.mark.parametrize(
    ("screen_bic", "band_bic", "expected_contrast", "expected_refined"),
    (
        (110.0, 80.0, "constant", False),
        (90.0, 80.0, "band", True),
    ),
)
def test_global_contrast_screen_controls_band_refinement(
    monkeypatch: pytest.MonkeyPatch,
    screen_bic: float,
    band_bic: float,
    expected_contrast: str,
    expected_refined: bool,
) -> None:
    from sopran.experimental.electron_reflection import global_joint

    transition_calls: list[str] = []
    screen_pitch_samples: list[int] = []

    def fake_transition(
        observations: object,
        model: str,
        contrast_model: str,
        settings: GlobalJointFitSettings,
        **kwargs: object,
    ) -> GlobalJointModelFit:
        del observations, settings, kwargs
        transition_calls.append(contrast_model)
        bic = 100.0 if contrast_model == "constant" else band_bic
        return replace(
            _global_model_fit(model, bic),
            contrast_model=contrast_model,
            transition_model="hard",
            sigma_ln_b=None,
        )

    def fake_candidate(
        observations: object,
        model: str,
        contrast_model: str,
        settings: GlobalJointFitSettings,
        **kwargs: object,
    ) -> GlobalJointModelFit:
        del observations, model, kwargs
        screen_pitch_samples.append(settings.pitch_response_samples)
        return replace(
            _global_model_fit(
                "mirror_only",
                100.0 if contrast_model == "constant" else screen_bic,
            ),
            contrast_model=contrast_model,
            transition_model="hard",
            sigma_ln_b=None,
        )

    monkeypatch.setattr(global_joint, "_fit_transition_without_beam", fake_transition)
    monkeypatch.setattr(global_joint, "_fit_candidate", fake_candidate)
    monkeypatch.setattr(
        global_joint,
        "_fit_selected_beam",
        lambda observations, selected, settings: selected,
    )

    selected, exact_delta, screen_delta, refined = global_joint._fit_edge_contrast(
        (),
        "mirror_only",
        GlobalJointFitSettings(edge_transition="auto", secondary_beam="off"),
    )

    assert selected.contrast_model == expected_contrast
    assert screen_pitch_samples == [8, 8]
    assert screen_delta == pytest.approx(100.0 - screen_bic)
    assert refined is expected_refined
    if expected_refined:
        assert transition_calls == ["constant", "band"]
        assert exact_delta == pytest.approx(100.0 - band_bic)
    else:
        assert transition_calls == ["constant"]
        assert np.isnan(exact_delta)


def test_global_auto_contrast_accepts_zero_floor_through_screen_and_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sopran.experimental.electron_reflection import global_joint

    constant = _global_model_fit("electrostatic", 100.0)
    band = replace(
        constant,
        contrast_model="band",
        bic=80.0,
        at_bounds=("contrast_floor",),
        _parameter_names=("contrast_floor",),
        _parameter_values=(0.0,),
    )

    def fake_candidate(
        observations: object,
        model: str,
        contrast_model: str,
        settings: GlobalJointFitSettings,
        **kwargs: object,
    ) -> GlobalJointModelFit:
        return band if contrast_model == "band" else constant

    monkeypatch.setattr(global_joint, "_fit_candidate", fake_candidate)
    monkeypatch.setattr(global_joint, "_fit_transition_without_beam", fake_candidate)
    selected, delta, screen_delta, refined = global_joint._fit_edge_contrast(
        (), "electrostatic", GlobalJointFitSettings(secondary_beam="off")
    )

    assert selected is band
    assert delta == pytest.approx(20.0)
    assert screen_delta == pytest.approx(20.0)
    assert refined


@pytest.mark.parametrize("screening", [False, True])
@pytest.mark.parametrize("refine_count", [1, 6])
def test_global_contrast_refine_uses_multiple_starts_after_unqualified_constant(
    monkeypatch: pytest.MonkeyPatch,
    screening: bool,
    refine_count: int,
) -> None:
    from sopran.experimental.electron_reflection import global_joint

    refine_starts: list[int | None] = []

    def fake_transition(
        observations: object,
        model: str,
        contrast_model: str,
        settings: GlobalJointFitSettings,
        **kwargs: object,
    ) -> GlobalJointModelFit:
        del observations, settings
        if contrast_model == "constant":
            return replace(
                _global_model_fit(model, 100.0),
                contrast_model="constant",
                at_bounds=("effective_field_nT",),
            )
        refine_starts.append(kwargs.get("hard_optimizer_starts"))  # type: ignore[arg-type]
        return replace(
            _global_model_fit(model, 80.0),
            contrast_model="band",
        )

    def fake_candidate(
        observations: object,
        model: str,
        contrast_model: str,
        settings: GlobalJointFitSettings,
        **kwargs: object,
    ) -> GlobalJointModelFit:
        del observations, settings, kwargs
        return replace(
            _global_model_fit(model, 90.0 if contrast_model == "band" else 100.0),
            contrast_model=contrast_model,
        )

    monkeypatch.setattr(global_joint, "_fit_transition_without_beam", fake_transition)
    monkeypatch.setattr(global_joint, "_fit_candidate", fake_candidate)
    monkeypatch.setattr(
        global_joint,
        "_fit_selected_beam",
        lambda observations, selected, settings: selected,
    )

    selected, _, _, refined = global_joint._fit_edge_contrast(
        (),
        "electrostatic",
        GlobalJointFitSettings(
            effective_field=EffectiveFieldFitSettings(optimizer_starts=4),
            contrast_refine_optimizer_starts=refine_count,
            contrast_screening=screening,
            secondary_beam="off",
        ),
    )

    assert selected.contrast_model == "band"
    assert refined
    assert refine_starts == [max(4, refine_count)]


def test_global_smooth_screen_skips_expensive_refinement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sopran.experimental.electron_reflection import global_joint

    calls: list[tuple[str, int]] = []

    def fake_fit_candidate(
        observations: object,
        model: str,
        contrast_model: str,
        settings: GlobalJointFitSettings,
        *,
        beam_enabled: bool,
        transition_model: str,
        **kwargs: object,
    ) -> GlobalJointModelFit:
        del observations, contrast_model, beam_enabled, kwargs
        calls.append((transition_model, settings.pitch_response_samples))
        bic = 100.0 if transition_model == "hard" else 110.0
        return replace(
            _global_model_fit(model, bic),
            transition_model=transition_model,
            sigma_ln_b=None if transition_model == "hard" else 0.2,
        )

    monkeypatch.setattr(global_joint, "_fit_candidate", fake_fit_candidate)

    selected = global_joint._fit_transition_without_beam(
        (),
        "mirror_only",
        "constant",
        GlobalJointFitSettings(edge_transition="auto", secondary_beam="off"),
    )

    assert calls == [("hard", 64), ("smooth", 8)]
    assert selected.transition_model == "hard"
    assert not selected.smooth_transition_refined
    assert np.isnan(selected.smooth_transition_delta_bic)
    assert selected.smooth_transition_screen_delta_bic == pytest.approx(-10.0)


def test_global_smooth_screen_refines_promising_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sopran.experimental.electron_reflection import global_joint

    calls: list[tuple[str, int]] = []

    def fake_fit_candidate(
        observations: object,
        model: str,
        contrast_model: str,
        settings: GlobalJointFitSettings,
        *,
        beam_enabled: bool,
        transition_model: str,
        **kwargs: object,
    ) -> GlobalJointModelFit:
        del observations, contrast_model, beam_enabled, kwargs
        calls.append((transition_model, settings.pitch_response_samples))
        bic = 100.0
        if transition_model == "smooth":
            bic = 98.0 if settings.pitch_response_samples == 8 else 90.0
        return replace(
            _global_model_fit(model, bic),
            transition_model=transition_model,
            sigma_ln_b=None if transition_model == "hard" else 0.2,
        )

    monkeypatch.setattr(global_joint, "_fit_candidate", fake_fit_candidate)

    selected = global_joint._fit_transition_without_beam(
        (),
        "mirror_only",
        "constant",
        GlobalJointFitSettings(edge_transition="auto", secondary_beam="off"),
    )

    assert calls == [("hard", 64), ("smooth", 8), ("smooth", 64)]
    assert selected.transition_model == "smooth"
    assert selected.smooth_transition_refined
    assert selected.smooth_transition_delta_bic == pytest.approx(10.0)
    assert selected.smooth_transition_screen_delta_bic == pytest.approx(2.0)


def test_global_smooth_refinement_uses_hard_seed_after_failed_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sopran.experimental.electron_reflection import global_joint

    hard = replace(
        _global_model_fit(
            "mirror_only", 100.0, at_bounds=("effective_field_nT",)
        ),
        transition_model="hard",
        sigma_ln_b=None,
        _parameter_names=("effective_field_nT",),
        _parameter_values=(2.0,),
    )
    failed_screen = replace(
        _global_model_fit("mirror_only", 90.0),
        success=False,
        transition_model="smooth",
        _parameter_names=(),
        _parameter_values=(),
    )
    seeds: list[GlobalJointModelFit | None] = []

    def fake_candidate(*args: object, **kwargs: object) -> GlobalJointModelFit:
        del args
        transition = str(kwargs["transition_model"])
        seeds.append(kwargs.get("seed_fit"))  # type: ignore[arg-type]
        if transition == "hard":
            return hard
        if len(seeds) == 2:
            return failed_screen
        return replace(
            hard,
            bic=95.0,
            transition_model="smooth",
            sigma_ln_b=0.2,
            at_bounds=(),
        )

    monkeypatch.setattr(global_joint, "_fit_candidate", fake_candidate)

    selected = global_joint._fit_transition_without_beam(
        (),
        "mirror_only",
        "constant",
        GlobalJointFitSettings(edge_transition="auto", secondary_beam="off"),
    )

    assert seeds == [None, hard, hard]
    assert selected.transition_model == "smooth"


def test_mirror_boundary_uses_mirror_ratio_and_energy_correction() -> None:
    boundary = mirror_boundary_sin2(
        np.array([100.0, 400.0]),
        mirror_ratio=8.0,
        delta_u_eff_eV=100.0,
    )

    assert boundary.tolist() == pytest.approx([0.25, 0.15625])


def test_global_selection_can_accept_electrostatic_when_mirror_loses_to_no_edge() -> None:
    from sopran.experimental.electron_reflection.global_joint import _select_global_model

    no_edge = _global_model_fit("no_edge", 1_000.0)
    mirror = _global_model_fit("mirror_only", 1_020.0)
    electrostatic = _global_model_fit("electrostatic", 900.0)

    selected, reason = _select_global_model(
        no_edge,
        mirror,
        electrostatic,
        GlobalJointFitSettings(),
    )

    assert selected is electrostatic
    assert reason == "global_electrostatic_curvature_supported"


def test_global_selection_does_not_require_nested_gain_when_mirror_is_unsupported() -> None:
    from sopran.experimental.electron_reflection.global_joint import _select_global_model

    no_edge = _global_model_fit("no_edge", 1_000.0)
    mirror = _global_model_fit("mirror_only", 1_001.0)
    electrostatic = _global_model_fit("electrostatic", 990.0)
    settings = GlobalJointFitSettings(
        effective_field=EffectiveFieldFitSettings(
            min_electrostatic_delta_bic=20.0,
            profile_likelihood=False,
        )
    )

    selected, reason = _select_global_model(
        no_edge,
        mirror,
        electrostatic,
        settings,
    )

    assert selected is electrostatic
    assert reason == "global_electrostatic_curvature_supported"


def test_global_selection_falls_back_to_supported_mirror_at_electrostatic_bound() -> None:
    from sopran.experimental.electron_reflection.global_joint import _select_global_model

    no_edge = _global_model_fit("no_edge", 1_000.0)
    mirror = _global_model_fit("mirror_only", 950.0)
    electrostatic = _global_model_fit(
        "electrostatic",
        900.0,
        at_bounds=("delta_u_eff_eV",),
    )

    selected, reason = _select_global_model(
        no_edge,
        mirror,
        electrostatic,
        GlobalJointFitSettings(),
    )

    assert selected is mirror
    assert reason == "global_mirror_edge_supported"


def test_global_selection_accepts_zero_contrast_floor_for_localized_band() -> None:
    from sopran.experimental.electron_reflection.global_joint import _select_global_model

    no_edge = _global_model_fit("no_edge", 1_000.0)
    mirror = replace(
        _global_model_fit("mirror_only", 900.0),
        contrast_model="band",
        at_bounds=("contrast_floor",),
        _parameter_names=("contrast_floor",),
        _parameter_values=(0.0,),
    )
    electrostatic = _global_model_fit("electrostatic", 1_100.0)

    selected, reason = _select_global_model(
        no_edge,
        mirror,
        electrostatic,
        GlobalJointFitSettings(),
    )

    assert selected is mirror
    assert reason == "global_mirror_edge_supported"


def test_global_selection_rejects_contrast_floor_at_upper_bound() -> None:
    from sopran.experimental.electron_reflection.global_joint import _select_global_model

    no_edge = _global_model_fit("no_edge", 1_000.0)
    mirror = replace(
        _global_model_fit("mirror_only", 900.0),
        contrast_model="band",
        at_bounds=("contrast_floor",),
        _parameter_names=("contrast_floor",),
        _parameter_values=(8.0,),
    )
    electrostatic = _global_model_fit("electrostatic", 1_100.0)

    selected, reason = _select_global_model(
        no_edge,
        mirror,
        electrostatic,
        GlobalJointFitSettings(),
    )

    assert selected is no_edge
    assert reason == "contrast_parameter_at_bound"


def test_global_selection_rejects_unbracketed_edge() -> None:
    from sopran.experimental.electron_reflection.global_joint import _select_global_model

    no_edge = _global_model_fit("no_edge", 1_000.0)
    mirror = replace(
        _global_model_fit("mirror_only", 900.0),
        boundary_bracket_fraction=0.2,
        strict_boundary_bracket_fraction=0.1,
    )
    electrostatic = _global_model_fit("electrostatic", 1_100.0)

    selected, reason = _select_global_model(
        no_edge,
        mirror,
        electrostatic,
        GlobalJointFitSettings(),
    )

    assert selected is no_edge
    assert reason == "insufficient_boundary_bracketing"


def test_mirror_transmission_saturates_outside_physical_pitch_domain() -> None:
    pitch = np.array([10.0, 45.0, 80.0])

    transition = mirror_transmission_probability(
        pitch,
        np.array([100.0, 200.0]),
        mirror_ratio=1.2,
        sigma_ln_b=0.08,
        delta_u_eff_eV=150.0,
    )
    negative_boundary = mirror_transmission_probability(
        pitch,
        np.array([100.0]),
        mirror_ratio=2.0,
        sigma_ln_b=0.08,
        delta_u_eff_eV=-150.0,
    )

    assert np.all(np.isfinite(transition))
    assert np.all(transition[0] < 1.0e-3)
    assert np.all(negative_boundary == 1.0)


def test_effective_field_fit_recovers_electrostatic_boundary_crossing_pitch_domain() -> None:
    counts = simulate_electron_reflection_counts(
        energy_eV=np.array([80.0, 120.0, 180.0, 260.0, 400.0, 600.0]),
        pitch_deg=np.arange(2.5, 90.0, 5.0),
        b_sc_nT=7.0,
        mirror_ratio=2.0,
        delta_u_eff_eV=220.0,
        sigma_ln_b=0.08,
        reference_counts=2_000.0,
        concentration=300.0,
        random_seed=112,
    )

    result = fit_effective_field(
        counts,
        settings=EffectiveFieldFitSettings(profile_likelihood=False),
    )

    assert result.edge_supported
    assert result.selected_model == "electrostatic"
    assert result.mirror_ratio == pytest.approx(2.0, rel=0.25)
    assert result.delta_u_eff_eV == pytest.approx(220.0, abs=60.0)


def test_effective_field_fit_recovers_mirror_only_counts() -> None:
    energy = np.array([120.0, 180.0, 270.0, 400.0, 600.0, 900.0])
    pitch = np.arange(2.5, 90.0, 5.0)
    affected_exposure = np.broadcast_to(
        np.linspace(0.6, 1.4, pitch.size),
        (energy.size, pitch.size),
    )
    reference_exposure = affected_exposure[:, ::-1]
    counts = simulate_electron_reflection_counts(
        energy_eV=energy,
        pitch_deg=pitch,
        b_sc_nT=8.0,
        mirror_ratio=7.5,
        sigma_ln_b=0.18,
        reference_counts=900.0,
        concentration=180.0,
        affected_exposure=affected_exposure,
        reference_exposure=reference_exposure,
        random_seed=42,
    )

    result = fit_effective_field(
        counts,
        settings=EffectiveFieldFitSettings(profile_likelihood=False),
    )

    assert result.success
    assert result.edge_supported
    assert result.selected_model == "mirror_only"
    assert result.mirror_ratio == pytest.approx(7.5, rel=0.2)
    assert result.effective_field_nT == pytest.approx(60.0, rel=0.2)
    assert result.delta_u_eff_eV is None
    assert result.diagnostics.no_edge_delta_bic > 6.0
    assert result.diagnostics.fit("mirror_only").contrast_model == "constant"
    assert result.quality_grade == "good"
    assert result.quality_reasons == ()
    assert result.diagnostics.edge_fit_pitch_pattern_correlation > 0.9
    assert result.diagnostics.edge_fit_log_ratio_residual_p90_abs < 0.5


def test_joint_effective_field_recovers_shared_parameters_on_separate_grids() -> None:
    esa1 = simulate_electron_reflection_counts(
        energy_eV=np.geomspace(80.0, 1_200.0, 12),
        pitch_deg=np.linspace(4.0, 86.0, 16),
        b_sc_nT=7.0,
        mirror_ratio=5.0,
        delta_u_eff_eV=-60.0,
        sigma_ln_b=0.2,
        reference_counts=900.0,
        concentration=200.0,
        random_seed=1,
    )
    esa2 = simulate_electron_reflection_counts(
        energy_eV=np.geomspace(95.0, 1_500.0, 10),
        pitch_deg=np.linspace(6.0, 84.0, 12),
        b_sc_nT=7.0,
        mirror_ratio=5.0,
        delta_u_eff_eV=-60.0,
        sigma_ln_b=0.2,
        reference_counts=700.0,
        concentration=150.0,
        affected_exposure=np.linspace(0.7, 1.3, 12),
        reference_exposure=np.linspace(1.2, 0.8, 12),
        random_seed=2,
    )

    result = fit_joint_effective_field(
        {"ESA1": esa1, "ESA2": esa2},
        settings=EffectiveFieldFitSettings(
            contrast_model="constant",
            delta_u_bounds_eV=(-300.0, 300.0),
            optimizer_starts=3,
            profile_likelihood=False,
        ),
    )

    assert result.edge_supported
    assert result.selected_model == "electrostatic"
    assert result.mirror_ratio == pytest.approx(5.0, rel=0.15)
    assert result.delta_u_eff_eV == pytest.approx(-60.0, abs=15.0)
    assert result.sigma_ln_b == pytest.approx(0.2, rel=0.2)
    selected = result.fit("electrostatic")
    assert selected.observation("ESA1").energy_eV.size == 12
    assert selected.observation("ESA2").energy_eV.size == 10
    assert selected.observation("ESA1").log_likelihood_gain_over_no_edge > 0.0
    assert selected.observation("ESA2").log_likelihood_gain_over_no_edge > 0.0


def test_joint_effective_field_rejects_two_no_edge_observations() -> None:
    observations = {
        name: simulate_electron_reflection_counts(
            energy_eV=np.geomspace(100.0, 1_000.0, energy_bins),
            pitch_deg=np.linspace(5.0, 85.0, pitch_bins),
            b_sc_nT=6.0,
            mirror_ratio=None,
            reference_counts=1_000.0,
            concentration=250.0,
            random_seed=seed,
        )
        for name, energy_bins, pitch_bins, seed in (
            ("ESA1", 10, 14, 10),
            ("ESA2", 9, 12, 11),
        )
    }

    result = fit_joint_effective_field(
        observations,
        settings=EffectiveFieldFitSettings(
            contrast_model="constant",
            optimizer_starts=2,
            profile_likelihood=False,
        ),
    )

    assert not result.edge_supported
    assert result.selected_model == "no_edge"
    assert result.mirror_ratio is None
    assert result.reason == "no_edge_evidence"


def test_joint_effective_field_plot_writes_sensor_panels(tmp_path) -> None:
    observations = {
        name: simulate_electron_reflection_counts(
            energy_eV=np.geomspace(100.0, 1_000.0, 8),
            pitch_deg=np.linspace(5.0, 85.0, pitch_bins),
            b_sc_nT=6.0,
            mirror_ratio=4.0,
            sigma_ln_b=0.2,
            reference_counts=700.0,
            concentration=180.0,
            random_seed=seed,
        )
        for name, pitch_bins, seed in (("ESA1", 14, 20), ("ESA2", 12, 21))
    }
    result = fit_joint_effective_field(
        observations,
        settings=EffectiveFieldFitSettings(
            contrast_model="constant",
            optimizer_starts=2,
            profile_likelihood=False,
        ),
    )
    destination = tmp_path / "joint-fit.png"

    figure = plot_joint_effective_field_fit(result, path=destination)

    assert destination.exists()
    assert destination.stat().st_size > 10_000
    assert len(figure.axes) >= 6
    import matplotlib.pyplot as plt

    plt.close(figure)


def test_global_joint_fit_recovers_field_and_cross_sensor_gain(tmp_path) -> None:
    rng = np.random.default_rng(7)
    pitch = np.linspace(5.625, 174.375, 16)
    observations: dict[str, GlobalPitchCountObservation] = {}
    for sensor_index, (name, energy, gain) in enumerate(
        (
            ("ESA-S1", np.geomspace(20.0, 2_000.0, 14), 1.0),
            ("ESA-S2", np.geomspace(25.0, 2_500.0, 13), 1.6),
        )
    ):
        folded = np.minimum(pitch, 180.0 - pitch)
        affected = pitch < 90.0
        transition = mirror_transmission_probability(
            folded,
            energy,
            mirror_ratio=4.0,
            sigma_ln_b=0.18,
            delta_u_eff_eV=-45.0,
        )
        log_normalized = np.zeros_like(transition)
        hemisphere_baseline = 0.7 - 0.15 * np.log(energy / 100.0)
        log_normalized[:, affected] = (
            hemisphere_baseline[:, None]
            - 1.5 * (1.0 - transition[:, affected])
        )
        incident_rate = 300.0 * (energy / 100.0) ** -0.7
        mean = gain * incident_rate[:, None] * np.exp(log_normalized)
        counts = rng.poisson(mean).astype(float)
        exposure = np.ones_like(counts)
        if sensor_index == 0:
            counts[:, -2:] = np.nan
            exposure[:, -2:] = np.nan
            counts[0, 0] = 0.0
        else:
            counts[:, :2] = np.nan
            exposure[:, :2] = np.nan
        observations[name] = GlobalPitchCountObservation(
            energy_eV=energy,
            pitch_deg=pitch,
            counts=counts,
            exposure=exposure,
            b_sc_nT=5.0,
            affected_side="low",
        )

    result = fit_global_joint_effective_field(
        observations,
        settings=GlobalJointFitSettings(
            effective_field=EffectiveFieldFitSettings(
                contrast_model="constant",
                optimizer_starts=3,
                max_iterations=1_500,
                profile_likelihood=False,
                min_strict_boundary_bracket_fraction=0.4,
            ),
            spectrum_knots=9,
            spectrum_smoothness=0.2,
        ),
    )

    assert result.edge_supported
    assert result.selected_model == "electrostatic"
    assert result.mirror_ratio == pytest.approx(4.0, rel=0.15)
    assert result.delta_u_eff_eV == pytest.approx(-45.0, abs=20.0)
    selected = result.fit("electrostatic")
    assert selected.sensor("ESA-S2").sensor_gain == pytest.approx(1.6, rel=0.08)
    fitted_baseline_at_100_eV = np.interp(
        np.log(100.0),
        np.log(selected.hemisphere_baseline_energy_eV),
        selected.hemisphere_baseline_log_ratio,
    )
    assert fitted_baseline_at_100_eV == pytest.approx(0.7, abs=0.2)
    assert np.count_nonzero(np.isfinite(result.normalized_flux.observed_log_ratio)) > 50
    assert selected.global_fov is not None
    split = int(np.flatnonzero(np.isclose(selected.global_fov.pitch_edges_deg, 90.0))[0])
    expected_affected_exposure = np.sum(selected.global_fov.exposure[:, :split])
    assert np.sum(result.normalized_flux.affected_exposure) == pytest.approx(
        expected_affected_exposure
    )
    np.testing.assert_allclose(
        result.normalized_flux.energy_edges_eV[[0, -1]],
        [20.0, 1_500.0],
    )
    from sopran.experimental.electron_reflection.global_joint import _combined_full_fov

    combined = _combined_full_fov(selected, orientation="physical")
    np.testing.assert_allclose(combined[0], selected.global_fov.energy_eV)
    np.testing.assert_allclose(combined[1], selected.global_fov.pitch_deg)
    np.testing.assert_allclose(
        combined[2], selected.global_fov.observed_log_normalized_flux, equal_nan=True
    )
    destination = tmp_path / "global-joint-fit.png"

    figure = plot_global_joint_effective_field_fit(result, path=destination)

    assert destination.stat().st_size > 10_000
    assert len(figure.axes) >= 12
    plotted_cmap = figure.axes[0].collections[0].cmap
    assert plotted_cmap(np.ma.masked) != pytest.approx(plotted_cmap(0.5))
    colorbar_labels = {axis.get_ylabel() for axis in figure.axes}
    assert "log10(normalized rate)" in colorbar_labels
    assert "log10(affected/reference)" in colorbar_labels
    assert "log10(exposure-weighted normalized rate)" in colorbar_labels
    assert "natural log" not in colorbar_labels
    plotted = np.ma.filled(figure.axes[0].collections[0].get_array(), np.nan)
    sensor = selected.sensor("ESA-S1")
    expected_log = sensor.observed_log_normalized_flux.copy()
    expected_log[sensor.observed_normalized_flux == 0.0] = np.log(np.finfo(float).tiny)
    expected = expected_log[np.argsort(sensor.energy_eV)] / np.log(10.0)
    np.testing.assert_allclose(plotted, expected, equal_nan=True)
    combined_axis = next(
        axis
        for axis in figure.axes
        if axis.get_title() == "Combined global FOV: observed normalized flux"
    )
    combined_values = np.ma.filled(combined_axis.collections[0].get_array(), np.nan)
    assert np.count_nonzero(np.isfinite(combined_values)) > np.count_nonzero(
        np.isfinite(expected)
    )
    assert figure.axes[0].collections[0].get_clim() == pytest.approx(
        (-4.0 / np.log(10.0), 4.0 / np.log(10.0))
    )
    assert figure.axes[0].get_ylim() == pytest.approx((20.0, 1_500.0))
    import matplotlib.pyplot as plt

    plt.close(figure)

    circular_destination = tmp_path / "global-joint-circular.png"
    circular_figure = plot_global_joint_circular_pitch_view(
        result,
        path=circular_destination,
    )
    assert circular_destination.stat().st_size > 10_000
    polar_axes = [axis for axis in circular_figure.axes if axis.name == "polar"]
    assert len(polar_axes) == 3
    assert any(
        line.get_label() == "Selected boundary: electrostatic"
        for line in polar_axes[0].lines
    )
    circular_legend = polar_axes[0].get_legend()
    assert circular_legend is not None
    assert "Selected boundary: electrostatic" in {
        text.get_text() for text in circular_legend.get_texts()
    }
    assert "+B" in {text.get_text() for text in polar_axes[0].get_xticklabels()}
    assert polar_axes[0].get_ylim() == pytest.approx(
        (0.0, np.log10(1_500.0) - np.log10(20.0))
    )
    plt.close(circular_figure)

    low_confidence_fit = replace(
        selected,
        normalized_flux=replace(
            selected.normalized_flux,
            reliable=np.zeros_like(selected.normalized_flux.observed_log_ratio, dtype=bool),
        ),
    )
    low_confidence_estimate = replace(
        result,
        model_fits=tuple(
            low_confidence_fit if fit.model == result.selected_model else fit
            for fit in result.model_fits
        ),
    )
    low_confidence_circular = plot_global_joint_circular_pitch_view(
        low_confidence_estimate
    )
    low_confidence_legend = low_confidence_circular.axes[0].get_legend()
    assert low_confidence_legend is not None
    assert "Low-confidence folded pair" in {
        text.get_text() for text in low_confidence_legend.get_texts()
    }
    plt.close(low_confidence_circular)

    rejected = replace(
        result,
        selected_model="no_edge",
        edge_supported=False,
        mirror_ratio=None,
        effective_field_nT=None,
        delta_u_eff_eV=None,
        sigma_ln_b=None,
        reason="no_edge_evidence",
    )
    rejected_figure = plot_global_joint_effective_field_fit(
        rejected,
        model="best_edge",
    )
    title = rejected_figure._suptitle.get_text()
    best_edge = min(
        (fit for fit in result.model_fits if fit.model != "no_edge"),
        key=lambda fit: float(fit.bic),
    )
    direct_delta = float(result.fit("no_edge").bic) - float(best_edge.bic)
    assert "rejected diagnostic candidate" in title
    assert "B_eff(shown)=" in title
    assert f"DeltaBIC(no_edge->shown)={direct_delta:.3g}" in title
    line_labels = {
        line.get_label()
        for axis in rejected_figure.axes
        for line in axis.lines
    }
    assert f"Non-selected diagnostic: {best_edge.model}" in line_labels
    plt.close(rejected_figure)

    rejected_circular = plot_global_joint_circular_pitch_view(
        rejected,
        model="best_edge",
    )
    assert "rejected diagnostic candidate" in rejected_circular._suptitle.get_text()
    rejected_boundary = next(
        line
        for line in rejected_circular.axes[0].lines
        if line.get_label() == f"Rejected diagnostic boundary: {best_edge.model}"
    )
    assert rejected_boundary.get_linestyle() == "--"
    plt.close(rejected_circular)

    comparison_result = replace(result, spacecraft_potential_eV=25.0)
    comparison_figure = plot_global_joint_effective_field_fit(
        comparison_result,
        model="mirror_only",
    )
    folded_axis = next(
        axis
        for axis in comparison_figure.axes
        if axis.get_title() == "Global-FOV fold: observed posterior rate ratio"
    )
    boundary_lines = {line.get_label(): line for line in folded_axis.lines}
    assert set(boundary_lines) == {
        "Selected boundary: electrostatic",
        "Non-selected diagnostic: mirror_only",
    }
    legend = folded_axis.get_legend()
    assert legend is not None
    assert {text.get_text() for text in legend.get_texts()} == set(boundary_lines)
    assert boundary_lines["Selected boundary: electrostatic"].get_linestyle() == "-"
    assert boundary_lines["Non-selected diagnostic: mirror_only"].get_linestyle() == "--"
    selected_fit = result.fit("electrostatic")
    selected_boundary = mirror_boundary_sin2(
        result.normalized_flux.energy_eV,
        selected_fit.mirror_ratio,
        selected_fit.delta_u_eff_eV,
        spacecraft_potential_eV=25.0,
    )
    expected_pitch = np.full(selected_boundary.shape, np.nan)
    physical = np.isfinite(selected_boundary) & (selected_boundary >= 0.0) & (
        selected_boundary <= 1.0
    )
    expected_pitch[physical] = np.degrees(np.arcsin(np.sqrt(selected_boundary[physical])))
    np.testing.assert_allclose(
        boundary_lines["Selected boundary: electrostatic"].get_xdata(),
        expected_pitch,
        equal_nan=True,
    )
    assert "R_m(selected)=" in comparison_figure._suptitle.get_text()
    plt.close(comparison_figure)


def test_global_observation_sorts_swept_energy_with_cell_data() -> None:
    xr = pytest.importorskip("xarray")
    counts = np.asarray([[[30.0, 31.0], [10.0, 11.0], [20.0, 21.0], [40.0, 41.0]]])
    exposure = counts + 100.0
    detector_samples = counts + 200.0
    spectrum = xr.DataArray(
        counts,
        dims=("time", "energy", "pitch_angle"),
        coords={
            "time": np.asarray(["2008-01-01"], dtype="datetime64[ns]"),
            "energy_eV": (
                ("time", "energy"),
                np.asarray([[300.0, 100.0, 200.0, 100.0]]),
            ),
            "pitch_angle": np.asarray([45.0, 135.0]),
            "exposure": (("time", "energy", "pitch_angle"), exposure),
            "detector_samples": (
                ("time", "energy", "pitch_angle"),
                detector_samples,
            ),
            "integration_time_seconds": ("time", np.asarray([2.0])),
        },
        attrs={"value": "counts", "units": "count"},
    )
    spectrum.coords["exposure"].attrs["mode"] = "calibrated"

    observation = GlobalPitchCountObservation.from_spectrum(
        spectrum,
        index=0,
        b_sc_nT=5.0,
        affected_side="low",
    )

    np.testing.assert_array_equal(observation.energy_eV, [100.0, 200.0, 300.0])
    np.testing.assert_array_equal(
        observation.counts,
        np.stack((counts[0, 1] + counts[0, 3], counts[0, 2], counts[0, 0])),
    )
    np.testing.assert_array_equal(
        observation.exposure,
        np.stack((exposure[0, 1] + exposure[0, 3], exposure[0, 2], exposure[0, 0])),
    )
    np.testing.assert_array_equal(
        observation.live_time_capacity_seconds,
        2.0
        * np.stack(
            (
                detector_samples[0, 1] + detector_samples[0, 3],
                detector_samples[0, 2],
                detector_samples[0, 0],
            )
        ),
    )
    assert observation.metadata is not None
    assert observation.metadata["energy_reordered"] is True
    assert observation.metadata["duplicate_energy_rows_coalesced"] == 1


@pytest.mark.parametrize(
    ("coordinate", "invalid", "message"),
    [
        ("detector_samples", np.nan, "live-time capacity"),
        ("known_background_counts", -1.0, "known background"),
    ],
)
def test_global_observation_rejects_invalid_correction_on_measured_cell(
    coordinate: str,
    invalid: float,
    message: str,
) -> None:
    xr = pytest.importorskip("xarray")
    counts = np.ones((1, 2, 2), dtype=float)
    correction = np.ones_like(counts)
    correction[0, 0, 0] = invalid
    spectrum = xr.DataArray(
        counts,
        dims=("time", "energy", "pitch_angle"),
        coords={
            "time": np.asarray(["2008-01-01"], dtype="datetime64[ns]"),
            "energy_eV": (("time", "energy"), np.asarray([[100.0, 200.0]])),
            "pitch_angle": np.asarray([45.0, 135.0]),
            "exposure": (("time", "energy", "pitch_angle"), np.ones_like(counts)),
            coordinate: (("time", "energy", "pitch_angle"), correction),
            "integration_time_seconds": ("time", np.asarray([1.0])),
        },
        attrs={"value": "counts", "units": "count"},
    )

    with pytest.raises(ValueError, match=message):
        GlobalPitchCountObservation.from_spectrum(
            spectrum,
            index=0,
            b_sc_nT=5.0,
            affected_side="low",
        )


def test_global_observation_requires_raw_integer_counts() -> None:
    with pytest.raises(ValueError, match="raw integer event counts"):
        GlobalPitchCountObservation(
            energy_eV=np.asarray([100.0, 200.0]),
            pitch_deg=np.asarray([45.0, 135.0]),
            counts=np.full((2, 2), 1.25),
            exposure=np.ones((2, 2)),
            b_sc_nT=5.0,
            affected_side="low",
        )


def test_global_observation_preserves_count_correction_provenance() -> None:
    xr = pytest.importorskip("xarray")
    counts = np.ones((1, 2, 2), dtype=float)
    exposure = np.ones_like(counts)
    exposure[0, 0, 0] = np.nan
    spectrum = xr.DataArray(
        counts,
        dims=("time", "energy", "pitch_angle"),
        coords={
            "time": np.asarray(["2008-01-01"], dtype="datetime64[ns]"),
            "energy_eV": (("time", "energy"), np.asarray([[100.0, 200.0]])),
            "pitch_angle": np.asarray([45.0, 135.0]),
            "exposure": (("time", "energy", "pitch_angle"), exposure),
        },
        attrs={
            "value": "counts",
            "units": "count",
            "count_correction": "event_trash",
            "count_correction_order": "trash_then_event",
        },
    )

    observation = GlobalPitchCountObservation.from_spectrum(
        spectrum,
        index=0,
        b_sc_nT=5.0,
        affected_side="low",
    )

    assert observation.metadata is not None
    assert observation.metadata["count_correction"] == "event_trash"
    assert observation.metadata["count_correction_order"] == "trash_then_event"
    assert observation.metadata["invalid_exposure_count_cells"] == 1


def test_global_observation_from_spectrum_requires_count_metadata() -> None:
    xr = pytest.importorskip("xarray")
    counts = np.ones((1, 2, 2), dtype=float)
    spectrum = xr.DataArray(
        counts,
        dims=("time", "energy", "pitch_angle"),
        coords={
            "time": np.asarray(["2008-01-01"], dtype="datetime64[ns]"),
            "energy_eV": (("time", "energy"), np.asarray([[100.0, 200.0]])),
            "pitch_angle": np.asarray([45.0, 135.0]),
            "exposure": (("time", "energy", "pitch_angle"), np.ones_like(counts)),
            "integration_time_seconds": ("time", np.asarray([1.0])),
        },
        attrs={"value": "energy_flux", "units": "eV/(cm2 s sr eV)"},
    )
    spectrum.attrs = {}
    with pytest.raises(ValueError, match="raw-count spectrum"):
        GlobalPitchCountObservation.from_spectrum(
            spectrum,
            index=0,
            b_sc_nT=5.0,
            affected_side="low",
        )

    spectrum.attrs = {"value": "energy_flux", "units": "eV/(cm2 s sr eV)"}
    with pytest.raises(ValueError, match="raw-count spectrum"):
        GlobalPitchCountObservation.from_spectrum(
            spectrum,
            index=0,
            b_sc_nT=5.0,
            affected_side="low",
        )

    spectrum.attrs = {"value": "counts", "units": "count"}
    with pytest.raises(ValueError, match="requires detector_samples"):
        GlobalPitchCountObservation.from_spectrum(
            spectrum,
            index=0,
            b_sc_nT=5.0,
            affected_side="low",
            dead_time_seconds=1.0e-6,
        )


def test_global_observation_builds_finite_bin_response_samples() -> None:
    from sopran.experimental.electron_reflection.global_joint import _prepare_observation

    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([100.0, 200.0]),
        energy_edges_eV=np.asarray([70.0, 140.0, 280.0]),
        pitch_deg=np.asarray([30.0, 90.0, 150.0]),
        pitch_edges_deg=np.asarray([0.0, 60.0, 120.0, 180.0]),
        counts=np.ones((2, 3)),
        exposure=np.ones((2, 3)),
        b_sc_nT=5.0,
        affected_side="low",
    )

    prepared = _prepare_observation(
        "ESA-S1",
        observation,
        GlobalJointFitSettings(
            energy_response_samples=2,
            pitch_response_samples=3,
        ),
    )

    assert prepared.energy_response_eV.shape == (2, 2)
    np.testing.assert_allclose(
        prepared.energy_response_eV,
        np.asarray(
            [
                [84.79274058, 125.20725942],
                [169.58548116, 250.41451884],
            ]
        ),
    )
    np.testing.assert_allclose(prepared.energy_response_weights, [0.5, 0.5])
    np.testing.assert_allclose(prepared.pitch_response_weights, [5 / 18, 4 / 9, 5 / 18])
    assert prepared.folded_pitch_response_deg.shape == (3, 3)
    assert np.all(
        (prepared.energy_response_eV > observation.energy_edges_eV[:-1, None])
        & (prepared.energy_response_eV < observation.energy_edges_eV[1:, None])
    )
    assert prepared.folded_pitch_response_deg[0].tolist() == pytest.approx(
        [6.76209992, 30.0, 53.23790008]
    )


def test_global_observation_uses_common_physical_energy_support() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _predicted_surfaces,
        _prepare_observation,
    )

    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([110.0, 200.0]),
        energy_edges_eV=np.asarray([80.0, 140.0, 260.0]),
        pitch_deg=np.asarray([45.0, 135.0]),
        counts=np.ones((2, 2)),
        exposure=np.ones((2, 2)),
        detector_response_matrix=np.asarray(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.5, 0.0, 0.5, 0.0],
                [0.0, 0.5, 0.0, 0.5],
            ]
        ),
        b_sc_nT=5.0,
        affected_side="low",
    )
    prepared = _prepare_observation(
        "ESA-S1",
        observation,
        GlobalJointFitSettings(
            effective_field=EffectiveFieldFitSettings(spacecraft_potential_eV=100.0),
            energy_response_samples=2,
        ),
    )

    assert prepared.energy_response_eV[0].tolist() == pytest.approx(
        [92.67949192, 127.32050808]
    )
    assert not np.any(prepared.valid[0])
    assert np.all(prepared.valid[1])
    problem = _build_problem(
        (prepared,),
        "no_edge",
        "none",
        GlobalJointFitSettings(
            effective_field=EffectiveFieldFitSettings(spacecraft_potential_eV=100.0),
            energy_response_samples=2,
            spectrum_knots=4,
            edge_transition="hard",
        ),
        beam_enabled=False,
    )
    log_mean, _normalized, _incident = _predicted_surfaces(
        problem.initial,
        problem,
        0,
        prepared,
    )
    assert np.all(np.isfinite(log_mean[1]))
    identity_observation = replace(observation, detector_response_matrix=np.eye(4))
    identity_prepared = _prepare_observation(
        "ESA-S1",
        identity_observation,
        problem.settings,
    )
    identity_problem = _build_problem(
        (identity_prepared,),
        "no_edge",
        "none",
        problem.settings,
        beam_enabled=False,
    )
    identity_log_mean, _normalized, _incident = _predicted_surfaces(
        identity_problem.initial,
        identity_problem,
        0,
        identity_prepared,
    )
    np.testing.assert_allclose(
        np.exp(log_mean[1]),
        0.5 * np.exp(identity_log_mean[1]),
    )


def test_global_forward_model_applies_background_and_dead_time() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _predicted_surfaces,
        _prepare_observation,
    )

    settings = GlobalJointFitSettings(
        spectrum_knots=4,
        energy_response_samples=1,
        pitch_response_samples=1,
        background_model="none",
        secondary_beam="off",
    )
    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([100.0, 200.0]),
        pitch_deg=np.asarray([45.0, 135.0]),
        counts=np.ones((2, 2)),
        exposure=np.full((2, 2), 2.0),
        known_background_counts=np.full((2, 2), 3.0),
        live_time_capacity_seconds=np.full((2, 2), 4.0),
        dead_time_seconds=0.1,
        b_sc_nT=5.0,
        affected_side="low",
    )
    prepared = _prepare_observation("ESA-S1", observation, settings)
    problem = _build_problem(
        (prepared,),
        "no_edge",
        "none",
        settings,
        beam_enabled=False,
    )
    vector = problem.initial.copy()
    vector[problem.layout.spectrum] = np.log(10.0)

    log_mean, normalized, _incident = _predicted_surfaces(vector, problem, 0, prepared)

    pre_dead_time = 2.0 * 10.0 + 3.0
    expected = pre_dead_time / (1.0 + 0.1 * pre_dead_time / 4.0)
    np.testing.assert_allclose(np.exp(log_mean), expected)
    np.testing.assert_allclose(normalized, 0.0, atol=1.0e-12)


def test_global_forward_model_applies_response_matrix_and_secondary_beam() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _predicted_surfaces,
        _prepare_observation,
    )

    settings = GlobalJointFitSettings(
        spectrum_knots=4,
        energy_response_samples=1,
        pitch_response_samples=1,
        background_model="none",
        secondary_beam="on",
    )
    response = np.eye(4)
    response[[0, 2]] = response[[2, 0]]
    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([100.0, 200.0]),
        pitch_deg=np.asarray([45.0, 135.0]),
        counts=np.ones((2, 2)),
        exposure=np.ones((2, 2)),
        detector_response_matrix=response,
        b_sc_nT=5.0,
        affected_side="low",
    )
    prepared = _prepare_observation("ESA-S1", observation, settings)
    problem = _build_problem(
        (prepared,),
        "no_edge",
        "none",
        settings,
        beam_enabled=True,
    )
    vector = problem.initial.copy()
    vector[problem.layout.spectrum] = np.log(np.asarray([10.0, 15.0, 25.0, 40.0]))
    assert problem.layout.beam is not None
    vector[problem.layout.beam] = np.log(np.asarray([2.0, 100.0, 0.25, 60.0]))

    _log_mean, normalized, incident = _predicted_surfaces(vector, problem, 0, prepared)

    assert prepared.detector_response_matrix is not None
    np.testing.assert_allclose(prepared.detector_response_matrix.sum(axis=1), 1.0)
    assert incident[0, 0] > incident[1, 0]
    assert normalized[0, 0] > 0.0
    assert normalized[0, 1] == pytest.approx(0.0, abs=1.0e-12)


def test_global_hard_edge_is_integrated_over_pitch_bin() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _normalized_flux,
        _predicted_surfaces,
        _prepare_observation,
    )

    settings = GlobalJointFitSettings(
        effective_field=EffectiveFieldFitSettings(contrast_model="constant"),
        spectrum_knots=4,
        energy_response_samples=1,
        pitch_response_samples=4,
        normalized_energy_bins=4,
        normalized_min_counts=1,
        edge_transition="hard",
        secondary_beam="off",
    )
    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([100.0, 200.0]),
        pitch_deg=np.asarray([30.0, 150.0]),
        pitch_edges_deg=np.asarray([20.0, 40.0, 160.0]),
        counts=np.ones((2, 2)),
        exposure=np.ones((2, 2)),
        b_sc_nT=5.0,
        affected_side="low",
    )
    prepared = _prepare_observation("ESA-S1", observation, settings)
    problem = _build_problem(
        (prepared,),
        "mirror_only",
        "constant",
        settings,
        beam_enabled=False,
        transition_model="hard",
    )
    smooth_problem = _build_problem(
        (prepared,),
        "mirror_only",
        "constant",
        settings,
        beam_enabled=False,
        transition_model="smooth",
    )
    assert smooth_problem.layout.size == problem.layout.size + 1
    vector = problem.initial.copy()
    vector[problem.layout.physical.start] = np.log(20.0)
    assert problem.layout.contrast is not None
    vector[problem.layout.contrast] = 1.0

    _log_mean, normalized, _incident = _predicted_surfaces(vector, problem, 0, prepared)

    expected_rate = 0.5 * (1.0 + np.exp(-1.0))
    np.testing.assert_allclose(normalized[:, 0], np.log(expected_rate))
    np.testing.assert_allclose(normalized[:, 1], 0.0)
    folded = _normalized_flux(vector, problem)
    assert np.any(np.isfinite(folded.fitted_log_ratio))


def test_global_fold_uses_full_fov_and_retains_zero_count_cells() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _fold_global_fov,
        _global_full_fov,
        _prepare_observation,
    )

    settings = GlobalJointFitSettings(
        effective_field=EffectiveFieldFitSettings(contrast_model="constant"),
        spectrum_knots=4,
        energy_response_samples=1,
        pitch_response_samples=1,
        normalized_energy_bins=4,
        normalized_min_counts=5,
        normalized_rate_prior_count=0.5,
        energy_bounds_eV=(80.0, 240.0),
        edge_transition="hard",
        secondary_beam="off",
    )
    energy = np.asarray([100.0, 200.0])
    observations = []
    for name, pitch_edges in (
        ("ESA-S1", np.linspace(0.0, 180.0, 5)),
        ("ESA-S2", np.linspace(0.0, 180.0, 7)),
    ):
        pitch = 0.5 * (pitch_edges[:-1] + pitch_edges[1:])
        counts = np.ones((energy.size, pitch.size), dtype=float)
        counts[:, pitch < 90.0] = 0.0
        observation = GlobalPitchCountObservation(
            energy_eV=energy,
            pitch_deg=pitch,
            pitch_edges_deg=pitch_edges,
            counts=counts,
            exposure=np.ones_like(counts),
            b_sc_nT=5.0,
            affected_side="low",
        )
        observations.append(_prepare_observation(name, observation, settings))
    problem = _build_problem(
        tuple(observations),
        "no_edge",
        "none",
        settings,
        beam_enabled=False,
    )

    full_fov = _global_full_fov(problem.initial, problem)
    folded = _fold_global_fov(full_fov, settings)
    split = int(np.flatnonzero(np.isclose(full_fov.pitch_edges_deg, 90.0))[0])
    expected_raw_counts = sum(
        float(np.sum(item.counts[item.valid])) for item in observations
    )
    expected_exposure = sum(
        float(np.sum(item.exposure[item.valid])) for item in observations
    )
    assert np.sum(full_fov.raw_counts) == pytest.approx(expected_raw_counts)
    assert np.sum(full_fov.exposure) == pytest.approx(expected_exposure)

    np.testing.assert_allclose(
        folded.affected_counts,
        full_fov.posterior_counts[:, :split],
    )
    np.testing.assert_allclose(
        folded.reference_counts,
        full_fov.posterior_counts[:, split:][:, ::-1],
    )
    support = (
        (folded.affected_normalized_exposure > 0.0)
        & (folded.reference_normalized_exposure > 0.0)
    )
    assert np.any(support & (folded.affected_counts == 0.0))
    assert np.all(np.isfinite(folded.observed_log_ratio[support]))
    assert np.all(folded.observed_log_ratio_std[support] > 0.0)
    assert np.any(support & ~folded.reliable)

    high_affected = _fold_global_fov(replace(full_fov, affected_side="high"), settings)
    np.testing.assert_allclose(
        high_affected.affected_counts,
        full_fov.posterior_counts[:, split:][:, ::-1],
    )
    np.testing.assert_allclose(
        high_affected.observed_log_ratio,
        -folded.observed_log_ratio,
    )
    np.testing.assert_allclose(
        high_affected.fitted_log_ratio,
        -folded.fitted_log_ratio,
    )
    np.testing.assert_allclose(
        high_affected.affected_normalized_exposure,
        full_fov.normalized_exposure[:, split:][:, ::-1],
    )

    one_sided_counts = np.zeros_like(full_fov.corrected_counts)
    one_sided_counts[:, split:] = 20.0
    one_sided = _fold_global_fov(
        replace(
            full_fov,
            corrected_counts=one_sided_counts,
            posterior_counts=one_sided_counts,
            raw_counts=one_sided_counts,
        ),
        settings,
    )
    assert np.all(one_sided.total_raw_counts >= settings.normalized_min_counts)
    assert np.all(np.isfinite(one_sided.observed_log_ratio))
    assert not np.any(one_sided.reliable)


def test_global_fov_orients_mixed_affected_sides_before_aggregation() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _global_full_fov,
        _prepare_observation,
    )

    settings = GlobalJointFitSettings(
        spectrum_knots=4,
        normalized_energy_bins=4,
        energy_bounds_eV=(80.0, 240.0),
        energy_response_samples=1,
        pitch_response_samples=1,
        edge_transition="hard",
        secondary_beam="off",
    )
    prepared = []
    for sensor, side in (("ESA-S1", "low"), ("ESA-S2", "high")):
        observation = GlobalPitchCountObservation(
            energy_eV=np.asarray([100.0, 200.0]),
            pitch_deg=np.asarray([22.5, 67.5, 112.5, 157.5]),
            counts=np.ones((2, 4)),
            exposure=np.ones((2, 4)),
            b_sc_nT=5.0,
            affected_side=side,
            sensor_group=sensor,
        )
        prepared.append(_prepare_observation(sensor, observation, settings))
    problem = _build_problem(
        tuple(prepared),
        "no_edge",
        "none",
        settings,
        beam_enabled=False,
    )

    full_fov = _global_full_fov(problem.initial, problem)

    assert full_fov.affected_side == "low"
    assert np.all(np.isfinite(full_fov.observed_log_normalized_flux))


def test_global_fov_preserves_negative_background_correction() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _global_full_fov,
        _prepare_observation,
    )

    settings = GlobalJointFitSettings(
        spectrum_knots=4,
        normalized_energy_bins=4,
        energy_bounds_eV=(80.0, 240.0),
        energy_response_samples=1,
        pitch_response_samples=1,
        edge_transition="hard",
        secondary_beam="off",
    )
    counts = np.ones((2, 4), dtype=float)
    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([100.0, 200.0]),
        pitch_deg=np.asarray([22.5, 67.5, 112.5, 157.5]),
        counts=counts,
        exposure=np.ones_like(counts),
        known_background_counts=np.full_like(counts, 2.0),
        b_sc_nT=5.0,
        affected_side="low",
    )
    prepared = _prepare_observation("ESA-S1", observation, settings)
    problem = _build_problem(
        (prepared,),
        "no_edge",
        "none",
        settings,
        beam_enabled=False,
    )

    full_fov = _global_full_fov(problem.initial, problem)

    assert np.all(full_fov.corrected_counts < 0.0)
    np.testing.assert_allclose(full_fov.posterior_counts, 0.0)

    positive = replace(
        observation,
        counts=np.full_like(counts, 4.0),
        known_background_counts=np.zeros_like(counts),
    )
    mixed_problem = _build_problem(
        (prepared, _prepare_observation("ESA-S2", positive, settings)),
        "no_edge",
        "none",
        settings,
        beam_enabled=False,
    )
    mixed_fov = _global_full_fov(mixed_problem.initial, mixed_problem)
    np.testing.assert_allclose(
        mixed_fov.posterior_counts,
        np.maximum(mixed_fov.corrected_counts, 0.0),
    )


def test_global_joint_fit_accepts_zero_count_affected_hemisphere() -> None:
    energy = np.geomspace(30.0, 500.0, 6)
    pitch = np.linspace(11.25, 168.75, 8)
    observations = {}
    for name in ("ESA-S1", "ESA-S2"):
        counts = np.full((energy.size, pitch.size), 10.0)
        counts[:, pitch < 90.0] = 0.0
        observations[name] = GlobalPitchCountObservation(
            energy_eV=energy,
            pitch_deg=pitch,
            counts=counts,
            exposure=np.ones_like(counts),
            b_sc_nT=5.0,
            affected_side="low",
        )
    settings = GlobalJointFitSettings(
        effective_field=EffectiveFieldFitSettings(
            contrast_model="constant",
            optimizer_starts=1,
            max_iterations=200,
            profile_likelihood=False,
        ),
        spectrum_knots=4,
        hemisphere_baseline_knots=3,
        energy_response_samples=1,
        pitch_response_samples=1,
        edge_transition="hard",
        secondary_beam="off",
    )

    result = fit_global_joint_effective_field(observations, settings=settings)

    assert result.fit("no_edge").n_cells == 2 * energy.size * pitch.size


@pytest.mark.parametrize(
    ("model", "contrast_model", "transition_model", "beam_enabled"),
    [
        ("no_edge", "none", "none", False),
        ("mirror_only", "constant", "hard", False),
        ("electrostatic", "band", "hard", False),
        ("no_edge", "none", "none", True),
        ("mirror_only", "constant", "hard", True),
        ("electrostatic", "band", "hard", True),
    ],
)
def test_global_native_hard_objective_matches_python(
    model: str,
    contrast_model: str,
    transition_model: str,
    beam_enabled: bool,
) -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _native_hard_problem,
        _objective,
        _prepare_observation,
    )

    settings = GlobalJointFitSettings(
        spectrum_knots=5,
        hemisphere_baseline_knots=3,
        spectrum_smoothness=0.35,
        energy_response_samples=2,
        background_model="sensor_constant",
        secondary_beam="off",
    )
    observations = []
    for sensor_index, name in enumerate(("ESA-S1", "ESA-S2")):
        energy = np.asarray([45.0, 100.0, 260.0, 900.0]) * (1.0 + 0.03 * sensor_index)
        pitch = np.asarray([15.0, 55.0, 125.0, 165.0])
        counts = (
            np.arange(energy.size * pitch.size, dtype=float).reshape(energy.size, pitch.size)
            + 2.0
            + sensor_index
        )
        observation = GlobalPitchCountObservation(
            energy_eV=energy,
            pitch_deg=pitch,
            counts=counts,
            exposure=np.full_like(counts, 1.5 + sensor_index),
            known_background_counts=np.full_like(counts, 0.2 + 0.1 * sensor_index),
            live_time_capacity_seconds=np.full_like(counts, 3.0 + sensor_index),
            dead_time_seconds=0.005 * (sensor_index + 1),
            b_sc_nT=5.0 + 2.0 * sensor_index,
            affected_side="low",
        )
        observations.append(_prepare_observation(name, observation, settings))
    problem = _build_problem(
        tuple(observations),
        model,
        contrast_model,
        settings,
        beam_enabled=beam_enabled,
        transition_model=transition_model,
    )
    vector = problem.initial.copy()
    vector[problem.layout.spectrum] += np.linspace(-0.2, 0.3, settings.spectrum_knots)
    vector[problem.layout.hemisphere_baseline] = np.asarray([0.25, -0.1, 0.15])
    vector[problem.layout.gains] = np.asarray([0.2])
    vector[problem.layout.backgrounds] = np.log(np.asarray([0.08, 0.12]))
    vector[problem.layout.dispersions] = np.log(np.asarray([35.0, 75.0]))
    if model != "no_edge":
        vector[problem.layout.physical.start] = np.log(22.5)
        assert problem.layout.contrast is not None
        if contrast_model == "constant":
            vector[problem.layout.contrast] = 1.3
        else:
            vector[problem.layout.contrast] = np.asarray(
                [0.3, 1.7, np.log(180.0), np.log(0.6)]
            )
    if model == "electrostatic":
        vector[problem.layout.physical.start + 1] = -25.0
    if problem.layout.beam is not None:
        vector[problem.layout.beam] = np.log(np.asarray([0.7, 140.0, 0.28, 12.0]))

    native_problem = _native_hard_problem(problem)

    assert native_problem is not None
    assert native_problem.objective(vector) == pytest.approx(
        _objective(vector, problem),
        rel=2.0e-12,
        abs=2.0e-10,
    )
    native_value, native_gradient = native_problem.value_and_gradient(vector)
    expected_gradient = np.empty(vector.shape, dtype=float)
    for index, value in enumerate(vector):
        step = np.sqrt(np.finfo(float).eps) * (1.0 if value >= 0.0 else -1.0) * max(
            1.0,
            abs(value),
        )
        lower, upper = problem.bounds[index]
        if not lower <= value + step <= upper:
            step = -step
        shifted = vector.copy()
        shifted[index] += step
        expected_gradient[index] = (
            _objective(shifted, problem) - _objective(vector, problem)
        ) / (shifted[index] - value)
    assert native_value == pytest.approx(_objective(vector, problem), abs=2.0e-10)
    np.testing.assert_allclose(native_gradient, expected_gradient, rtol=3.0e-5, atol=3.0e-5)
    selected_indices = [0, vector.size - 1]
    indexed_value, indexed_gradient = native_problem.value_and_gradient_indices(
        vector, selected_indices
    )
    assert indexed_value == pytest.approx(native_value, abs=2.0e-10)
    np.testing.assert_allclose(
        indexed_gradient,
        native_gradient[selected_indices],
        rtol=3.0e-5,
        atol=3.0e-5,
    )


def test_global_native_hard_problem_rejects_unsupported_forward_models() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _native_hard_problem,
        _prepare_observation,
    )

    settings = GlobalJointFitSettings(
        spectrum_knots=4,
        secondary_beam="off",
    )
    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([100.0, 200.0]),
        pitch_deg=np.asarray([45.0, 135.0]),
        counts=np.ones((2, 2)),
        exposure=np.ones((2, 2)),
        detector_response_matrix=np.eye(4),
        b_sc_nT=5.0,
        affected_side="low",
    )
    prepared = _prepare_observation("ESA-S1", observation, settings)
    problem = _build_problem(
        (prepared,),
        "mirror_only",
        "constant",
        settings,
        beam_enabled=False,
        transition_model="hard",
    )

    assert _native_hard_problem(problem) is not None

    smooth_problem = _build_problem(
        (prepared,),
        "mirror_only",
        "constant",
        settings,
        beam_enabled=False,
        transition_model="smooth",
    )
    assert _native_hard_problem(smooth_problem) is None


def test_global_problem_shares_nuisance_parameters_within_sensor_group() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _group_sensor_fits_for_plot,
        _native_hard_problem,
        _objective,
        _prepare_observation,
        _sensor_fits,
    )

    settings = GlobalJointFitSettings(
        spectrum_knots=4,
        hemisphere_baseline_knots=2,
        energy_response_samples=1,
        pitch_response_samples=1,
        secondary_beam="off",
    )
    prepared = []
    for record in range(2):
        for sensor_name in ("ESA-S1", "ESA-S2"):
            counts = np.full((4, 4), 5.0 + record)
            observation = GlobalPitchCountObservation(
                energy_eV=np.asarray([40.0, 100.0, 300.0, 900.0]),
                pitch_deg=np.asarray([22.5, 67.5, 112.5, 157.5]),
                counts=counts,
                exposure=np.ones_like(counts),
                b_sc_nT=5.0,
                affected_side="low",
                sensor_group=sensor_name,
            )
            prepared.append(
                _prepare_observation(f"{sensor_name}:{record}", observation, settings)
            )

    problem = _build_problem(
        tuple(prepared),
        "mirror_only",
        "constant",
        settings,
        beam_enabled=False,
        transition_model="hard",
    )

    assert problem.sensor_names == ("ESA-S1", "ESA-S2")
    assert problem.sensor_indices == (0, 1, 0, 1)
    assert problem.layout.gains.stop - problem.layout.gains.start == 1
    assert problem.layout.dispersions.stop - problem.layout.dispersions.start == 2
    native = _native_hard_problem(problem)
    assert native is not None
    assert native.objective(problem.initial) == pytest.approx(
        _objective(problem.initial, problem), rel=2.0e-12, abs=2.0e-10
    )
    plot_sensors = _group_sensor_fits_for_plot(
        _sensor_fits(problem.initial, problem),
        energy_bounds=settings.energy_bounds_eV,
        energy_bins=settings.normalized_energy_bins,
    )
    assert [sensor.name for sensor in plot_sensors] == ["ESA-S1", "ESA-S2"]
    assert all(sensor.energy_eV.size == settings.normalized_energy_bins for sensor in plot_sensors)


def test_global_problem_shares_effective_field_across_varying_spacecraft_field() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _predicted_surfaces,
        _prepare_observation,
    )

    settings = GlobalJointFitSettings(
        spectrum_knots=4,
        hemisphere_baseline_knots=2,
        energy_response_samples=1,
        pitch_response_samples=1,
        secondary_beam="off",
    )
    prepared = []
    for index, b_sc_nT in enumerate((5.0, 10.0)):
        observation = GlobalPitchCountObservation(
            energy_eV=np.asarray([40.0, 100.0, 300.0, 900.0]),
            pitch_deg=np.asarray([22.5, 67.5, 112.5, 157.5]),
            counts=np.full((4, 4), 10.0),
            exposure=np.ones((4, 4)),
            b_sc_nT=b_sc_nT,
            affected_side="low",
            sensor_group=f"ESA-S{index + 1}",
        )
        prepared.append(_prepare_observation(f"record-{index}", observation, settings))
    problem = _build_problem(
        tuple(prepared),
        "mirror_only",
        "constant",
        settings,
        beam_enabled=False,
        transition_model="hard",
    )
    vector = problem.initial.copy()
    vector[problem.layout.physical.start] = np.log(20.0)

    _, first_normalized, _ = _predicted_surfaces(vector, problem, 0, prepared[0])
    _, second_normalized, _ = _predicted_surfaces(vector, problem, 1, prepared[1])

    assert problem.names[problem.layout.physical.start] == "effective_field_nT"
    assert not np.allclose(first_normalized, second_normalized)


def test_global_no_edge_beam_uses_multiple_beam_starts() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _prepare_observation,
        _starts,
    )

    settings = GlobalJointFitSettings(
        effective_field=EffectiveFieldFitSettings(optimizer_starts=4),
        spectrum_knots=4,
        energy_response_samples=1,
        pitch_response_samples=1,
        secondary_beam="on",
    )
    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([100.0, 200.0]),
        pitch_deg=np.asarray([45.0, 135.0]),
        counts=np.ones((2, 2)),
        exposure=np.ones((2, 2)),
        b_sc_nT=5.0,
        affected_side="low",
    )
    prepared = _prepare_observation("ESA-S1", observation, settings)
    problem = _build_problem(
        (prepared,),
        "no_edge",
        "none",
        settings,
        beam_enabled=True,
    )
    assert problem.layout.beam is not None

    starts = _starts(problem)
    beam_starts = np.stack([start[problem.layout.beam] for start in starts])

    assert len(starts) == 4
    assert np.unique(beam_starts, axis=0).shape[0] == 4


def test_global_seeded_multistart_keeps_independent_canonical_starts() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _build_problem,
        _prepare_observation,
        _starts,
    )

    settings = GlobalJointFitSettings(
        effective_field=EffectiveFieldFitSettings(optimizer_starts=4),
        spectrum_knots=4,
        hemisphere_baseline_knots=2,
        energy_response_samples=1,
        pitch_response_samples=1,
        secondary_beam="off",
    )
    observation = GlobalPitchCountObservation(
        energy_eV=np.asarray([40.0, 100.0, 300.0, 900.0]),
        pitch_deg=np.asarray([22.5, 67.5, 112.5, 157.5]),
        counts=np.full((4, 4), 10.0),
        exposure=np.ones((4, 4)),
        b_sc_nT=5.0,
        affected_side="low",
    )
    prepared = _prepare_observation("ESA-S1", observation, settings)
    problem = _build_problem(
        (prepared,),
        "electrostatic",
        "band",
        settings,
        beam_enabled=False,
        transition_model="hard",
    )
    seeded_values = problem.initial.copy()
    seeded_values[problem.layout.spectrum.start] += 10.0
    seed_fit = replace(
        _global_model_fit("electrostatic", 100.0),
        _parameter_names=problem.names,
        _parameter_values=tuple(seeded_values),
    )

    starts = _starts(problem, seed_fit=seed_fit)

    assert len(starts) == 4
    assert starts[0][problem.layout.spectrum.start] == pytest.approx(
        seeded_values[problem.layout.spectrum.start]
    )
    np.testing.assert_allclose(starts[1], problem.initial)
    assert starts[2][problem.layout.spectrum.start] == pytest.approx(
        problem.initial[problem.layout.spectrum.start]
    )
    assert np.exp(starts[2][problem.layout.physical.start]) / 5.0 == pytest.approx(0.8)
    assert starts[2][problem.layout.physical.start + 1] == pytest.approx(-100.0)


def test_global_hard_energy_quadrature_resolves_bin_crossing() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _bin_quadrature,
        _hard_pitch_bin_transmission,
    )

    energy_edges = np.asarray([40.0, 60.0])
    pitch_edges = np.asarray([0.0, 11.25])

    def integrated_transmission(samples: int) -> float:
        energy, weights = _bin_quadrature(
            energy_edges,
            samples,
            logarithmic=False,
        )
        transmission = _hard_pitch_bin_transmission(
            energy[0],
            pitch_edges,
            1.1,
            delta_u_eff_eV=-45.0,
            spacecraft_potential_eV=0.0,
        )[:, 0]
        return float(np.dot(weights, transmission))

    reference = integrated_transmission(128)

    assert abs(integrated_transmission(8) - reference) < 0.04
    assert abs(integrated_transmission(2) - reference) > 0.2


def test_global_smooth_pitch_quadrature_resolves_narrow_transition() -> None:
    from sopran.experimental.electron_reflection.global_joint import (
        _bin_quadrature,
        _transition_probability,
    )

    pitch_edges = np.asarray([0.0, 11.25])

    def integrated_transmission(samples: int) -> float:
        pitch, weights = _bin_quadrature(
            pitch_edges,
            samples,
            logarithmic=False,
        )
        transmission = _transition_probability(
            pitch[0],
            np.asarray([933.0]),
            140.8,
            sigma_ln_b=0.0303,
            transition_model="smooth",
            delta_u_eff_eV=-24.6,
            spacecraft_potential_eV=0.0,
        )[0]
        return float(np.dot(weights, transmission))

    reference = integrated_transmission(128)

    assert abs(integrated_transmission(64) - reference) < 0.002
    assert abs(integrated_transmission(8) - reference) > 0.07


def test_global_joint_auto_selects_clear_secondary_beam() -> None:
    rng = np.random.default_rng(19)
    energy = np.geomspace(20.0, 1_000.0, 10)
    pitch = np.linspace(5.625, 174.375, 16)
    folded = np.minimum(pitch, 180.0 - pitch)
    affected = pitch < 90.0
    incident = 250.0 * (energy / 100.0) ** -0.6
    beam = (
        4.0
        * np.exp(-0.5 * (np.log(energy / 120.0) / 0.22) ** 2)[:, None]
        * np.exp(-0.5 * (folded / 12.0) ** 2)[None, :]
    )
    beam[:, ~affected] = 0.0
    observations = {
        name: GlobalPitchCountObservation(
            energy_eV=energy,
            pitch_deg=pitch,
            counts=rng.poisson(gain * incident[:, None] * (1.0 + beam)).astype(float),
            exposure=np.ones((energy.size, pitch.size)),
            b_sc_nT=5.0,
            affected_side="low",
        )
        for name, gain in (("ESA-S1", 1.0), ("ESA-S2", 1.4))
    }

    result = fit_global_joint_effective_field(
        observations,
        settings=GlobalJointFitSettings(
            effective_field=EffectiveFieldFitSettings(
                contrast_model="constant",
                optimizer_starts=2,
                max_iterations=800,
                profile_likelihood=False,
            ),
            spectrum_knots=8,
            spectrum_smoothness=0.1,
            background_model="none",
            secondary_beam="auto",
            min_secondary_beam_delta_bic=6.0,
        ),
    )

    selected = result.fit(result.selected_model)
    assert selected.secondary_beam_enabled
    assert selected.secondary_beam_delta_bic > 6.0
    assert selected.secondary_beam_screen_delta_bic > 1.0
    assert selected.secondary_beam_refined
    assert selected.beam_center_eV == pytest.approx(120.0, rel=0.35)


def test_global_joint_auto_keeps_beam_off_without_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    from sopran.experimental.electron_reflection import global_joint

    def fake_fit_candidate(
        observations: object,
        model: str,
        contrast_model: str,
        settings: GlobalJointFitSettings,
        *,
        beam_enabled: bool,
        transition_model: str,
        **kwargs: object,
    ) -> GlobalJointModelFit:
        del observations, contrast_model, settings, kwargs
        return replace(
            _global_model_fit(model, 1_010.0 if beam_enabled else 1_000.0),
            secondary_beam_enabled=beam_enabled,
            transition_model=transition_model,
        )

    monkeypatch.setattr(global_joint, "_fit_candidate", fake_fit_candidate)

    selected = global_joint._fit_candidate_with_beam(
        (),
        "no_edge",
        "none",
        GlobalJointFitSettings(),
    )

    assert not selected.secondary_beam_enabled
    assert np.isnan(selected.secondary_beam_delta_bic)
    assert selected.secondary_beam_screen_delta_bic == pytest.approx(-10.0)
    assert not selected.secondary_beam_refined


def test_global_joint_unqualified_edge_receives_full_beam_refinement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sopran.experimental.electron_reflection import global_joint

    calls: list[tuple[bool, int]] = []

    def fake_fit_candidate(
        observations: object,
        model: str,
        contrast_model: str,
        settings: GlobalJointFitSettings,
        *,
        beam_enabled: bool,
        transition_model: str,
        **kwargs: object,
    ) -> GlobalJointModelFit:
        del observations, contrast_model, kwargs
        calls.append((beam_enabled, settings.pitch_response_samples))
        if not beam_enabled:
            return replace(
                _global_model_fit(
                    model, 1_000.0, at_bounds=("effective_field_nT",)
                ),
                transition_model=transition_model,
            )
        bic = 1_010.0 if settings.pitch_response_samples == 8 else 900.0
        return replace(
            _global_model_fit(model, bic),
            secondary_beam_enabled=True,
            transition_model=transition_model,
        )

    monkeypatch.setattr(global_joint, "_fit_candidate", fake_fit_candidate)

    selected = global_joint._fit_candidate_with_beam(
        (),
        "mirror_only",
        "constant",
        GlobalJointFitSettings(edge_transition="hard", secondary_beam="auto"),
    )

    assert calls == [(False, 64), (True, 8), (False, 8), (True, 64)]
    assert selected.secondary_beam_enabled
    assert selected.secondary_beam_refined


def test_global_joint_auto_keeps_qualified_edge_when_beam_fit_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sopran.experimental.electron_reflection import global_joint

    def fake_fit_candidate(
        observations: object,
        model: str,
        contrast_model: str,
        settings: GlobalJointFitSettings,
        *,
        beam_enabled: bool,
        transition_model: str,
        **kwargs: object,
    ) -> GlobalJointModelFit:
        del observations, contrast_model, settings, kwargs
        return replace(
            _global_model_fit(model, 900.0 if beam_enabled else 1_000.0),
            secondary_beam_enabled=beam_enabled,
            transition_model=transition_model,
            at_bounds=("effective_field_nT",) if beam_enabled else (),
        )

    monkeypatch.setattr(global_joint, "_fit_candidate", fake_fit_candidate)

    selected = global_joint._fit_candidate_with_beam(
        (),
        "mirror_only",
        "constant",
        GlobalJointFitSettings(edge_transition="hard", secondary_beam="auto"),
    )

    assert not selected.secondary_beam_enabled
    assert selected.bic == pytest.approx(1_000.0)
    assert selected.secondary_beam_delta_bic == pytest.approx(100.0)


def test_effective_field_profile_interval_brackets_estimate() -> None:
    counts = simulate_electron_reflection_counts(
        energy_eV=np.array([120.0, 180.0, 270.0, 400.0, 600.0, 900.0]),
        pitch_deg=np.arange(2.5, 90.0, 5.0),
        b_sc_nT=8.0,
        mirror_ratio=7.5,
        sigma_ln_b=0.18,
        reference_counts=900.0,
        concentration=180.0,
        random_seed=42,
    )

    result = fit_effective_field(
        counts,
        settings=EffectiveFieldFitSettings(
            optimizer_starts=2,
            profile_points=9,
            profile_log_ratio_half_width=1.0,
        ),
    )

    assert result.mirror_ratio is not None
    assert result.mirror_ratio_ci95 is not None
    lower, upper = result.mirror_ratio_ci95
    assert lower < result.mirror_ratio < upper
    assert lower < 7.5 < upper


def test_effective_field_fit_rejects_no_edge_counts() -> None:
    counts = simulate_electron_reflection_counts(
        energy_eV=np.array([120.0, 200.0, 350.0, 600.0, 900.0]),
        pitch_deg=np.arange(2.5, 90.0, 5.0),
        b_sc_nT=8.0,
        mirror_ratio=None,
        reference_counts=1_200.0,
        concentration=200.0,
        random_seed=7,
    )

    result = fit_effective_field(
        counts,
        settings=EffectiveFieldFitSettings(profile_likelihood=False),
    )

    assert result.success
    assert not result.edge_supported
    assert result.selected_model == "no_edge"
    assert result.mirror_ratio is None
    assert result.effective_field_nT is None
    assert result.reason == "no_edge_evidence"


def test_effective_field_fit_rejects_boundary_stuck_edge() -> None:
    counts = simulate_electron_reflection_counts(
        energy_eV=np.array([120.0, 180.0, 270.0, 400.0, 600.0, 900.0]),
        pitch_deg=np.arange(2.5, 90.0, 5.0),
        b_sc_nT=8.0,
        mirror_ratio=1.5,
        sigma_ln_b=0.35,
        reference_counts=2_000.0,
        concentration=300.0,
        random_seed=16,
    )

    result = fit_effective_field(
        counts,
        settings=EffectiveFieldFitSettings(
            mirror_ratio_bounds=(2.0, 1000.0),
            profile_likelihood=False,
        ),
    )

    assert result.success
    assert not result.edge_supported
    assert result.selected_model == "no_edge"
    assert result.mirror_ratio is None
    assert result.reason == "edge_parameter_at_bound"


def test_effective_field_fit_selects_supported_electrostatic_curvature() -> None:
    counts = simulate_electron_reflection_counts(
        energy_eV=np.array([80.0, 110.0, 150.0, 220.0, 330.0, 500.0, 750.0, 1100.0]),
        pitch_deg=np.arange(2.5, 90.0, 5.0),
        b_sc_nT=7.0,
        mirror_ratio=9.0,
        delta_u_eff_eV=140.0,
        sigma_ln_b=0.16,
        reference_counts=2_000.0,
        concentration=300.0,
        random_seed=12,
    )

    result = fit_effective_field(
        counts,
        settings=EffectiveFieldFitSettings(
            profile_likelihood=False,
            min_electrostatic_delta_bic=4.0,
        ),
    )

    assert result.success
    assert result.edge_supported
    assert result.selected_model == "electrostatic"
    assert result.mirror_ratio == pytest.approx(9.0, rel=0.25)
    assert result.delta_u_eff_eV == pytest.approx(140.0, abs=55.0)
    assert result.diagnostics.electrostatic_delta_bic > 4.0


def test_effective_field_fit_handles_zero_counts_and_missing_cells() -> None:
    counts = simulate_electron_reflection_counts(
        energy_eV=np.array([120.0, 200.0, 350.0, 600.0, 900.0]),
        pitch_deg=np.arange(2.5, 90.0, 5.0),
        b_sc_nT=6.0,
        mirror_ratio=6.0,
        reference_counts=120.0,
        concentration=80.0,
        random_seed=21,
    )
    affected = counts.affected_counts.copy()
    reference = counts.reference_counts.copy()
    affected[0, :3] = 0.0
    affected[1, 4] = np.nan
    reference[1, 4] = np.nan
    sparse = ElectronReflectionCounts(
        energy_eV=counts.energy_eV,
        pitch_deg=counts.pitch_deg,
        affected_counts=affected,
        reference_counts=reference,
        b_sc_nT=counts.b_sc_nT,
    )

    result = fit_effective_field(
        sparse,
        settings=EffectiveFieldFitSettings(profile_likelihood=False),
    )

    assert result.success
    assert result.edge_supported
    assert result.mirror_ratio == pytest.approx(6.0, rel=0.35)
    assert result.diagnostics.n_cells == affected.size - 1


def test_effective_field_fit_recovers_energy_localized_contrast() -> None:
    energy = np.geomspace(20.0, 5_000.0, 24)
    pitch = np.linspace(5.625, 84.375, 8)
    amplitude = 0.15 + 2.4 * np.exp(-0.5 * ((np.log(energy) - np.log(350.0)) / 0.65) ** 2)
    counts = _simulate_structured_contrast(
        energy=energy,
        pitch=pitch,
        amplitude=amplitude,
        mirror_ratio=5.0,
        random_seed=91,
    )

    result = fit_effective_field(
        counts,
        settings=EffectiveFieldFitSettings(
            optimizer_starts=3,
            profile_likelihood=False,
        ),
    )
    fitted = result.diagnostics.fit("mirror_only")

    assert result.edge_supported
    assert result.selected_model == "mirror_only"
    assert fitted.contrast_model == "band"
    assert fitted.contrast_band_center_eV == pytest.approx(350.0, rel=0.5)
    assert fitted.contrast_band_width_ln == pytest.approx(0.65, rel=0.55)
    assert result.diagnostics.contrast_band_delta_bic > 6.0


def test_binary_loss_cone_fit_recovers_sharp_energy_localized_edge() -> None:
    energy = np.geomspace(40.0, 1_200.0, 16)
    pitch = np.linspace(5.625, 84.375, 8)
    mirror_ratio = 1.11
    edge = (
        np.sin(np.deg2rad(pitch))[None, :] ** 2
        >= mirror_boundary_sin2(energy, mirror_ratio)[:, None]
    )
    band = np.exp(-0.5 * (np.log(energy / 240.0) / 0.35) ** 2)
    pitch_background = np.array([-2.2, -1.5, -1.0, -0.7, -0.35, -0.1, 0.0, 0.1])
    energy_baseline = -0.4 + 0.1 * np.sin(np.log(energy))
    log_ratio = energy_baseline[:, None] + pitch_background[None, :] + 2.8 * band[:, None] * edge
    mean = 1.0 / (1.0 + np.exp(-log_ratio))
    rng = np.random.default_rng(77)
    total = rng.poisson(2_000.0, size=mean.shape)
    affected = rng.binomial(total, mean).astype(float)
    counts = ElectronReflectionCounts(
        energy_eV=energy,
        pitch_deg=pitch,
        affected_counts=affected,
        reference_counts=(total - affected).astype(float),
        b_sc_nT=5.0,
    )

    settings = BinaryLossConeFitSettings(
        mirror_grid_points=72,
        delta_u_grid_points=81,
        contrast_center_grid_points=12,
        contrast_width_grid_points=8,
    )
    result = fit_binary_loss_cone(counts, settings=settings)
    fitted = result.fit("mirror_only")
    reversed_counts = ElectronReflectionCounts(
        energy_eV=counts.energy_eV[::-1],
        pitch_deg=counts.pitch_deg,
        affected_counts=counts.affected_counts[::-1],
        reference_counts=counts.reference_counts[::-1],
        b_sc_nT=counts.b_sc_nT,
    )
    reversed_result = fit_binary_loss_cone(reversed_counts, settings=settings)
    reversed_fitted = reversed_result.fit("mirror_only")

    assert result.edge_supported
    assert result.selected_model == "mirror_only"
    assert result.no_edge_delta_bic > 6.0
    assert fitted.mirror_ratio == pytest.approx(mirror_ratio, rel=0.15)
    assert fitted.contrast_band_center_eV == pytest.approx(240.0, rel=0.5)
    assert fitted.contrast_band_width_ln == pytest.approx(0.35, rel=0.75)
    assert np.all(np.diff(reversed_result.energy_eV) > 0.0)
    assert reversed_result.selected_model == result.selected_model
    assert reversed_fitted.mirror_ratio == pytest.approx(fitted.mirror_ratio)
    assert reversed_fitted.delta_u_eff_eV == fitted.delta_u_eff_eV
    assert reversed_fitted.fitted_log_ratio == pytest.approx(fitted.fitted_log_ratio)


def test_halekas_hard_fit_recovers_full_synthetic_distribution() -> None:
    counts = _simulate_halekas_distribution(sigma_ln_sin2=None)
    settings = HalekasFitSettings(
        mirror_ratio_bounds=(1.01, 5.0),
        delta_u_bounds_eV=(-200.0, 200.0),
        mirror_grid_points=72,
        delta_u_grid_points=81,
    )

    result = fit_halekas_distribution(counts, settings=settings)
    reversed_counts = ElectronReflectionCounts(
        energy_eV=counts.energy_eV[::-1],
        pitch_deg=counts.pitch_deg,
        affected_counts=counts.affected_counts[::-1],
        reference_counts=counts.reference_counts[::-1],
        b_sc_nT=counts.b_sc_nT,
    )
    reversed_result = fit_halekas_distribution(reversed_counts, settings=settings)

    assert result.success
    assert result.edge_transition == "hard"
    assert result.mirror_ratio == pytest.approx(1.35, rel=0.05)
    assert result.delta_u_eff_eV == pytest.approx(-60.0, abs=6.0)
    assert result.sigma_ln_sin2 is None
    assert result.root_mean_square_error < 0.01
    assert result.hard_to_smooth_delta_bic == pytest.approx(0.0)
    assert not result.at_bounds
    assert np.all(np.diff(reversed_result.energy_eV) > 0.0)
    assert reversed_result.mirror_ratio == result.mirror_ratio
    assert reversed_result.delta_u_eff_eV == result.delta_u_eff_eV


def test_halekas_probit_fit_recovers_gradual_edge_width() -> None:
    counts = _simulate_halekas_distribution(sigma_ln_sin2=0.22)
    hard_settings = HalekasFitSettings(
        mirror_ratio_bounds=(1.01, 5.0),
        delta_u_bounds_eV=(-200.0, 200.0),
        mirror_grid_points=72,
        delta_u_grid_points=81,
    )
    smooth_settings = HalekasFitSettings(
        edge_transition="probit",
        mirror_ratio_bounds=hard_settings.mirror_ratio_bounds,
        delta_u_bounds_eV=hard_settings.delta_u_bounds_eV,
        mirror_grid_points=hard_settings.mirror_grid_points,
        delta_u_grid_points=hard_settings.delta_u_grid_points,
    )

    hard = fit_halekas_distribution(counts, settings=hard_settings)
    smooth = fit_halekas_distribution(counts, settings=smooth_settings)

    assert smooth.success
    assert smooth.edge_transition == "probit"
    assert smooth.mirror_ratio == pytest.approx(1.35, rel=0.05)
    assert smooth.delta_u_eff_eV == pytest.approx(-60.0, abs=6.0)
    assert smooth.sigma_ln_sin2 == pytest.approx(0.22, rel=0.1)
    assert smooth.root_mean_square_error < hard.root_mean_square_error * 0.02
    assert smooth.hard_to_smooth_delta_bic > 6.0
    assert not smooth.at_bounds


def test_effective_field_fit_rejects_unbracketed_pitch_boundary() -> None:
    base = simulate_electron_reflection_counts(
        energy_eV=np.array([120.0, 180.0, 270.0, 400.0, 600.0, 900.0]),
        pitch_deg=np.arange(2.5, 90.0, 5.0),
        b_sc_nT=8.0,
        mirror_ratio=7.5,
        sigma_ln_b=0.18,
        reference_counts=2_000.0,
        concentration=300.0,
        random_seed=31,
    )
    affected = base.affected_counts.copy()
    reference = base.reference_counts.copy()
    affected[:, :3] = np.nan
    reference[:, :3] = np.nan
    sparse = ElectronReflectionCounts(
        energy_eV=base.energy_eV,
        pitch_deg=base.pitch_deg,
        affected_counts=affected,
        reference_counts=reference,
        b_sc_nT=base.b_sc_nT,
    )

    result = fit_effective_field(
        sparse,
        settings=EffectiveFieldFitSettings(
            contrast_model="constant",
            profile_likelihood=False,
        ),
    )

    assert not result.edge_supported
    assert result.selected_model == "no_edge"
    assert result.reason == "insufficient_boundary_bracketing"
    assert result.diagnostics.no_edge_delta_bic > 6.0
    assert result.diagnostics.strict_boundary_bracket_fraction == 0.0


def test_effective_field_fit_reports_separate_energy_ratio_step() -> None:
    energy = np.geomspace(20.0, 5_000.0, 24)
    pitch = np.linspace(5.625, 84.375, 8)
    baseline = np.where(energy >= 450.0, 1.1, -0.7)
    counts = _simulate_structured_contrast(
        energy=energy,
        pitch=pitch,
        amplitude=np.zeros_like(energy),
        baseline=baseline,
        mirror_ratio=5.0,
        random_seed=123,
    )

    result = fit_effective_field(
        counts,
        settings=EffectiveFieldFitSettings(
            contrast_model="constant",
            optimizer_starts=1,
            profile_likelihood=False,
        ),
    )

    assert not result.edge_supported
    assert result.diagnostics.energy_ratio_step_supported
    assert result.diagnostics.energy_ratio_step_center_eV == pytest.approx(
        450.0,
        rel=0.35,
    )
    assert result.diagnostics.energy_ratio_step_log_ratio == pytest.approx(1.8, abs=0.35)
    assert result.diagnostics.energy_ratio_step_direction == "up"
    assert result.diagnostics.energy_ratio_step_delta_bic > 6.0


def test_electron_reflection_counts_rejects_non_physical_inputs() -> None:
    with pytest.raises(ValueError, match="same shape"):
        ElectronReflectionCounts(
            energy_eV=np.array([100.0, 200.0]),
            pitch_deg=np.array([10.0, 20.0]),
            affected_counts=np.ones((2, 2)),
            reference_counts=np.ones((2, 3)),
            b_sc_nT=8.0,
        )

    with pytest.raises(ValueError, match="non-negative"):
        ElectronReflectionCounts(
            energy_eV=np.array([100.0]),
            pitch_deg=np.array([10.0]),
            affected_counts=np.array([[-1.0]]),
            reference_counts=np.array([[1.0]]),
            b_sc_nT=8.0,
        )


def test_effective_field_quality_thresholds_validate_ordering() -> None:
    with pytest.raises(ValueError, match="good <= review"):
        EffectiveFieldQualitySettings(
            good_log_ratio_residual_p90=3.0,
            review_log_ratio_residual_p90=2.0,
        )


def test_beta_binomial_analytic_gradient_matches_central_difference() -> None:
    from sopran.experimental.electron_reflection.model import (
        _initial_parameters,
        _negative_log_likelihood,
        _negative_log_likelihood_and_gradient,
        _parameter_layout,
        _prepare_counts,
    )

    counts = simulate_electron_reflection_counts(
        energy_eV=np.array([120.0, 200.0, 350.0, 600.0]),
        pitch_deg=np.arange(5.0, 90.0, 10.0),
        b_sc_nT=8.0,
        mirror_ratio=6.0,
        reference_counts=500.0,
        concentration=120.0,
        random_seed=4,
    )
    settings = EffectiveFieldFitSettings(
        contrast_model="band",
        profile_likelihood=False,
    )
    prepared = _prepare_counts(counts, settings)
    layout = _parameter_layout("mirror_only", prepared.n_energy, "band")
    vector, bounds = _initial_parameters(prepared, layout, settings)
    for index, (lower, upper) in enumerate(bounds):
        if lower < upper:
            vector[index] = np.clip(vector[index], lower + 1.0e-3, upper - 1.0e-3)

    _value, analytic = _negative_log_likelihood_and_gradient(
        vector,
        prepared,
        layout,
    )
    numeric = np.empty_like(vector)
    for index in range(vector.size):
        step = 1.0e-5 * max(1.0, abs(float(vector[index])))
        plus = vector.copy()
        minus = vector.copy()
        plus[index] += step
        minus[index] -= step
        numeric[index] = (
            _negative_log_likelihood(plus, prepared, layout)
            - _negative_log_likelihood(minus, prepared, layout)
        ) / (2.0 * step)

    assert analytic == pytest.approx(numeric, rel=2.0e-4, abs=2.0e-4)


def _simulate_structured_contrast(
    *,
    energy: np.ndarray,
    pitch: np.ndarray,
    amplitude: np.ndarray,
    baseline: np.ndarray | None = None,
    mirror_ratio: float,
    random_seed: int,
) -> ElectronReflectionCounts:
    transition = mirror_transmission_probability(
        pitch,
        energy,
        mirror_ratio,
        0.24,
    )
    baseline_values = (
        -0.1 + 0.06 * np.sin(np.log(energy))
        if baseline is None
        else np.asarray(baseline, dtype=float)
    )
    log_ratio = baseline_values[:, None] + amplitude[:, None] * transition
    mean = 1.0 / (1.0 + np.exp(-log_ratio))
    concentration = 180.0
    rng = np.random.default_rng(random_seed)
    total = rng.poisson(900.0, size=mean.shape)
    beta_probability = rng.beta(
        mean * concentration,
        (1.0 - mean) * concentration,
    )
    affected = rng.binomial(total, beta_probability).astype(float)
    reference = (total - affected).astype(float)
    return ElectronReflectionCounts(
        energy_eV=energy,
        pitch_deg=pitch,
        affected_counts=affected,
        reference_counts=reference,
        b_sc_nT=8.0,
    )


def _simulate_halekas_distribution(
    *,
    sigma_ln_sin2: float | None,
) -> ElectronReflectionCounts:
    energy = np.geomspace(40.0, 1_500.0, 20)
    pitch = np.linspace(3.0, 87.0, 20)
    boundary = mirror_boundary_sin2(
        energy,
        mirror_ratio=1.35,
        delta_u_eff_eV=-60.0,
    )
    sin2_pitch = np.sin(np.deg2rad(pitch)) ** 2
    if sigma_ln_sin2 is None:
        outside = np.asarray(sin2_pitch[None, :] >= boundary[:, None], dtype=float)
    else:
        log_boundary = np.full(boundary.shape, -np.inf, dtype=float)
        positive = boundary > 0.0
        log_boundary[positive] = np.log(boundary[positive])
        outside = ndtr((np.log(sin2_pitch)[None, :] - log_boundary[:, None]) / sigma_ln_sin2)
    ratio = 0.1 + 0.9 * outside
    reference = np.full(ratio.shape, 10_000.0)
    affected = np.rint(reference * ratio)
    return ElectronReflectionCounts(
        energy_eV=energy,
        pitch_deg=pitch,
        affected_counts=affected,
        reference_counts=reference,
        b_sc_nT=6.0,
    )
