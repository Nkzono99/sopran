from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from math import exp, log
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import numpy as np
from numpy.typing import ArrayLike, NDArray

from sopran.experimental.electron_reflection.model import (
    CandidateModel,
    EffectiveFieldFitSettings,
    FloatArray,
    ResolvedContrastModel,
    mirror_boundary_sin2,
    mirror_transmission_probability,
)

SecondaryBeamMode = Literal["off", "on", "auto"]
BackgroundModel = Literal["none", "sensor_constant"]
PitchOrientation = Literal["physical", "native"]
EdgeTransition = Literal["auto", "hard", "smooth"]
ResolvedEdgeTransition = Literal["none", "hard", "smooth"]
LossConeModel = Literal["flexible", "fixed", "shared"]


@dataclass(frozen=True)
class GlobalPitchCountObservation:
    """One sensor's unpaired full-pitch count and exposure surface."""

    energy_eV: ArrayLike
    pitch_deg: ArrayLike
    counts: ArrayLike
    exposure: ArrayLike
    b_sc_nT: float
    affected_side: Literal["low", "high"]
    energy_edges_eV: ArrayLike | None = None
    pitch_edges_deg: ArrayLike | None = None
    detector_response_matrix: ArrayLike | None = None
    known_background_counts: ArrayLike | None = None
    live_time_capacity_seconds: ArrayLike | None = None
    dead_time_seconds: float = 0.0
    metadata: Mapping[str, Any] | None = None
    sensor_group: str | None = None

    @classmethod
    def from_spectrum(
        cls,
        spectrum: Any,
        *,
        index: int,
        b_sc_nT: float,
        affected_side: Literal["low", "high"],
        dead_time_seconds: float = 0.0,
        detector_response_matrix: ArrayLike | None = None,
        known_background_counts: ArrayLike | None = None,
    ) -> GlobalPitchCountObservation:
        """Extract one raw-count observation from a SOPRAN/xarray pitch spectrum."""

        return cls.from_spectrum_window(
            spectrum,
            indices=(index,),
            b_sc_nT=b_sc_nT,
            affected_side=affected_side,
            dead_time_seconds=dead_time_seconds,
            detector_response_matrix=detector_response_matrix,
            known_background_counts=known_background_counts,
        )

    @classmethod
    def from_spectrum_window(
        cls,
        spectrum: Any,
        *,
        indices: ArrayLike,
        b_sc_nT: float,
        affected_side: Literal["low", "high"],
        dead_time_seconds: float = 0.0,
        detector_response_matrix: ArrayLike | None = None,
        known_background_counts: ArrayLike | None = None,
    ) -> GlobalPitchCountObservation:
        """Extract one selected record as a raw-count observation.

        Negative-binomial likelihood terms must remain independent between
        native records. Use one observation per record and share
        ``sensor_group`` when fitting an integration window.
        """

        array = spectrum.to_xarray() if hasattr(spectrum, "to_xarray") else spectrum
        value_kind = array.attrs.get("value")
        if str(value_kind) != "counts":
            raise ValueError("global joint fitting requires a raw-count spectrum")
        units = array.attrs.get("units")
        if str(units) not in {"count", "counts"}:
            raise ValueError("global joint fitting requires count units")
        values = np.asarray(array.values, dtype=float)
        if values.ndim != 3 or tuple(str(dim) for dim in array.dims) != (
            "time",
            "energy",
            "pitch_angle",
        ):
            raise ValueError("spectrum must have (time, energy, pitch_angle) dimensions")
        energy = np.asarray(array.coords["energy_eV"].values, dtype=float)
        exposure = np.asarray(array.coords["exposure"].values, dtype=float)
        pitch = np.asarray(array.coords["pitch_angle"].values, dtype=float)
        times = np.asarray(array.coords["time"].values, dtype="datetime64[ns]")
        pitch_edges = array.attrs.get("pitch_edges")
        selected_indices = np.asarray(indices, dtype=int)
        if selected_indices.ndim != 1 or selected_indices.size == 0:
            raise ValueError("indices must be a non-empty one-dimensional sequence")
        if selected_indices.size != 1:
            raise ValueError(
                "from_spectrum_window no longer aggregates native records; "
                "build one observation per record instead"
            )
        if np.any((selected_indices < 0) | (selected_indices >= values.shape[0])):
            raise IndexError("spectrum window index is out of range")
        response = (
            detector_response_matrix
            if detector_response_matrix is not None
            else array.attrs.get("detector_response_matrix")
        )
        if response is not None and selected_indices.size > 1:
            raise ValueError(
                "multi-record integration with a detector response matrix is not supported"
            )
        background = (
            known_background_counts
            if known_background_counts is not None
            else (
                np.asarray(
                    array.coords["known_background_counts"].values[selected_indices],
                    dtype=float,
                )
                if "known_background_counts" in array.coords
                else None
            )
        )
        if "integration_time_seconds" in array.coords:
            integration_time = np.asarray(
                array.coords["integration_time_seconds"].values[selected_indices],
                dtype=float,
            )
        else:
            integration_time = np.ones(selected_indices.size, dtype=float)
        if "detector_samples" in array.coords:
            detector_samples = np.asarray(
                array.coords["detector_samples"].values[selected_indices], dtype=float
            )
            live_time_capacity = integration_time[:, None, None] * detector_samples
        else:
            if dead_time_seconds > 0.0:
                raise ValueError(
                    "dead_time_seconds requires detector_samples in the spectrum"
                )
            live_time_capacity = np.broadcast_to(
                integration_time[:, None, None],
                values[selected_indices].shape,
            ).astype(float, copy=True)
        sample_counts = values[selected_indices].reshape(-1, pitch.size)
        sample_exposure = exposure[selected_indices].reshape(-1, pitch.size)
        live_time_capacity = live_time_capacity.reshape(-1, pitch.size)
        sample_energy = np.asarray(energy[selected_indices], dtype=float).reshape(-1)
        if background is not None:
            background = np.asarray(background, dtype=float)
            expected_shape = values[selected_indices].shape
            if background.shape == expected_shape[1:] and selected_indices.size == 1:
                background = background[None, ...]
            if background.shape != expected_shape:
                raise ValueError(
                    "known background must match the selected (time, energy, pitch) cells"
                )
            background = background.reshape(-1, pitch.size)
        measured = (
            np.isfinite(sample_counts)
            & np.isfinite(sample_exposure)
            & (sample_exposure > 0.0)
        )
        invalid_exposure_count_cells = int(
            np.count_nonzero(
                np.isfinite(sample_counts)
                & (~np.isfinite(sample_exposure) | (sample_exposure <= 0.0))
            )
        )
        invalid_live_time = ~np.isfinite(live_time_capacity) | (
            live_time_capacity <= 0.0
        )
        if np.any(measured & invalid_live_time):
            raise ValueError(
                "live-time capacity must be finite and positive for measured cells"
            )
        live_time_capacity = np.where(
            invalid_live_time, 1.0, live_time_capacity
        )
        if background is not None:
            invalid_background = ~np.isfinite(background) | (background < 0.0)
            if np.any(measured & invalid_background):
                raise ValueError(
                    "known background must be finite and non-negative for measured cells"
                )
            background = np.where(invalid_background, 0.0, background)
        energy_order = np.argsort(sample_energy, kind="stable")
        energy_reordered = not np.array_equal(energy_order, np.arange(sample_energy.size))
        sample_energy = sample_energy[energy_order]
        sample_counts = sample_counts[energy_order]
        sample_exposure = sample_exposure[energy_order]
        live_time_capacity = live_time_capacity[energy_order]
        if background is not None:
            background = background[energy_order]
        response = _reorder_detector_response(
            response,
            energy_order=energy_order,
            pitch_bins=pitch.size,
        )
        unique_energy, energy_group = np.unique(sample_energy, return_inverse=True)
        duplicate_energy_rows = int(sample_energy.size - unique_energy.size)
        if duplicate_energy_rows:
            if response is not None:
                raise ValueError(
                    "duplicate energy rows cannot be coalesced with a detector response matrix"
                )
            valid_cells = (
                np.isfinite(sample_counts)
                & np.isfinite(sample_exposure)
                & (sample_exposure > 0.0)
            )
            grouped_counts = np.full(
                (unique_energy.size, pitch.size), np.nan, dtype=float
            )
            grouped_exposure = np.full_like(grouped_counts, np.nan)
            grouped_live_time = np.ones_like(grouped_counts)
            grouped_background = (
                np.zeros_like(grouped_counts) if background is not None else None
            )
            for group in range(unique_energy.size):
                rows = energy_group == group
                supported = valid_cells[rows]
                any_supported = np.any(supported, axis=0)
                grouped_counts[group, any_supported] = np.sum(
                    np.where(supported, sample_counts[rows], 0.0), axis=0
                )[any_supported]
                grouped_exposure[group, any_supported] = np.sum(
                    np.where(supported, sample_exposure[rows], 0.0), axis=0
                )[any_supported]
                grouped_live_time[group, any_supported] = np.sum(
                    np.where(supported, live_time_capacity[rows], 0.0), axis=0
                )[any_supported]
                if grouped_background is not None and background is not None:
                    grouped_background[group, any_supported] = np.sum(
                        np.where(supported, background[rows], 0.0), axis=0
                    )[any_supported]
            sample_energy = unique_energy
            sample_counts = grouped_counts
            sample_exposure = grouped_exposure
            live_time_capacity = grouped_live_time
            background = grouped_background
        exposure_mode = str(array.coords["exposure"].attrs.get("mode", "unknown"))
        diagonal_response = (
            "pace_info_geometric_factor_diagonal"
            if exposure_mode == "calibrated"
            else "relative_diagonal"
        )
        response_kind = (
            f"{diagonal_response}+redistribution_matrix"
            if response is not None
            else diagonal_response
        )
        return cls(
            energy_eV=sample_energy,
            pitch_deg=pitch,
            counts=sample_counts,
            exposure=sample_exposure,
            b_sc_nT=b_sc_nT,
            affected_side=affected_side,
            pitch_edges_deg=pitch_edges,
            detector_response_matrix=response,
            known_background_counts=background,
            live_time_capacity_seconds=live_time_capacity,
            dead_time_seconds=dead_time_seconds,
            metadata={
                "time": str(times[selected_indices[0]]),
                "time_start": str(times[selected_indices].min()),
                "time_stop": str(times[selected_indices].max()),
                "integrated_records": int(selected_indices.size),
                "exposure_mode": exposure_mode,
                "response_kind": response_kind,
                "count_correction": str(array.attrs.get("count_correction", "none")),
                "count_correction_order": str(
                    array.attrs.get("count_correction_order", "trash_then_event")
                ),
                "invalid_exposure_count_cells": invalid_exposure_count_cells,
                "energy_reordered": energy_reordered,
                "duplicate_energy_rows_coalesced": duplicate_energy_rows,
            },
        )

    def __post_init__(self) -> None:
        energy = np.asarray(self.energy_eV, dtype=float)
        pitch = np.asarray(self.pitch_deg, dtype=float)
        counts = np.asarray(self.counts, dtype=float)
        exposure = np.asarray(self.exposure, dtype=float)
        if energy.ndim != 1 or np.any(~np.isfinite(energy)) or np.any(energy <= 0.0):
            raise ValueError("energy_eV must contain finite positive values")
        if pitch.ndim != 1 or np.any(~np.isfinite(pitch)):
            raise ValueError("pitch_deg must contain finite values")
        if np.any((pitch <= 0.0) | (pitch >= 180.0)):
            raise ValueError("pitch_deg must be strictly between 0 and 180 degrees")
        if counts.shape != (energy.size, pitch.size):
            raise ValueError("counts must have shape (energy, pitch)")
        if exposure.shape != counts.shape:
            raise ValueError("exposure must have the same shape as counts")
        finite_counts = counts[np.isfinite(counts)]
        if np.any(finite_counts < 0.0):
            raise ValueError("counts must be non-negative")
        if np.any(np.abs(finite_counts - np.rint(finite_counts)) > 1.0e-8):
            raise ValueError("counts must contain raw integer event counts")
        if not np.isfinite(self.b_sc_nT) or self.b_sc_nT <= 0.0:
            raise ValueError("b_sc_nT must be finite and positive")
        if self.affected_side not in {"low", "high"}:
            raise ValueError("affected_side must be 'low' or 'high'")
        energy_edges = _resolve_energy_edges(energy, self.energy_edges_eV)
        pitch_edges = _resolve_pitch_edges(pitch, self.pitch_edges_deg)
        response = _resolve_detector_response(self.detector_response_matrix, counts.shape)
        background = _resolve_cell_array(
            self.known_background_counts,
            counts.shape,
            default=0.0,
            name="known_background_counts",
            allow_zero=True,
        )
        live_time = _resolve_cell_array(
            self.live_time_capacity_seconds,
            counts.shape,
            default=1.0,
            name="live_time_capacity_seconds",
            allow_zero=False,
        )
        if not np.isfinite(self.dead_time_seconds) or self.dead_time_seconds < 0.0:
            raise ValueError("dead_time_seconds must be finite and non-negative")
        object.__setattr__(self, "energy_eV", energy)
        object.__setattr__(self, "pitch_deg", pitch)
        object.__setattr__(self, "counts", counts)
        object.__setattr__(self, "exposure", exposure)
        object.__setattr__(self, "energy_edges_eV", energy_edges)
        object.__setattr__(self, "pitch_edges_deg", pitch_edges)
        object.__setattr__(self, "detector_response_matrix", response)
        object.__setattr__(self, "known_background_counts", background)
        object.__setattr__(self, "live_time_capacity_seconds", live_time)


@dataclass(frozen=True)
class GlobalJointFitSettings:
    """Settings for the raw-count, globally normalized joint model.

    ``energy_bounds_eV`` selects measured channels by their nominal center.
    Selected channels retain their full finite-bin quadrature and detector
    response so the forward model remains consistent with the measured counts.

    ``loss_cone_model='fixed'`` uses outside level 1 and inside fraction 0.1.
    ``'shared'`` fits one outside level and one inside fraction for all energies;
    both override ``effective_field.contrast_model`` with constant contrast and
    ignore ``hemisphere_baseline_knots``. Their no-edge null fits one common
    hemisphere level. ``'flexible'`` preserves the energy-dependent model.
    Beam selection and response integration apply to all three families.
    """

    effective_field: EffectiveFieldFitSettings = EffectiveFieldFitSettings(profile_likelihood=False)
    spectrum_knots: int = 32
    hemisphere_baseline_knots: int = 4
    loss_cone_model: LossConeModel = "flexible"
    boundary_grid_refinement: bool = True
    normalized_energy_bins: int = 24
    normalized_min_counts: int = 5
    energy_bounds_eV: tuple[float, float] = (20.0, 1_500.0)
    spectrum_smoothness: float = 0.0
    sensor_gain_log_bounds: tuple[float, float] = (-5.0, 5.0)
    energy_response_samples: int = 8
    pitch_response_samples: int = 64
    edge_transition: EdgeTransition = "hard"
    smooth_screening: bool = True
    smooth_screen_pitch_samples: int = 8
    smooth_screen_delta_bic: float = 0.0
    smooth_screen_max_iterations: int = 300
    smooth_refine_optimizer_starts: int = 1
    contrast_screening: bool = True
    contrast_screen_pitch_samples: int = 8
    contrast_screen_delta_bic_margin: float = 5.0
    contrast_screen_max_iterations: int = 300
    contrast_refine_optimizer_starts: int = 1
    background_model: BackgroundModel = "none"
    background_rate_bounds_hz: tuple[float, float] = (1.0e-8, 1.0e3)
    secondary_beam: SecondaryBeamMode = "auto"
    min_secondary_beam_delta_bic: float = 10.0
    beam_screening: bool = True
    beam_screen_pitch_samples: int = 8
    beam_screen_delta_bic_margin: float = 5.0
    beam_screen_max_iterations: int = 300
    beam_screen_optimizer_starts: int = 4
    beam_refine_optimizer_starts: int = 1
    beam_amplitude_bounds: tuple[float, float] = (1.0e-4, 100.0)
    beam_center_bounds_eV: tuple[float, float] = (5.0, 10_000.0)
    beam_sigma_ln_energy_bounds: tuple[float, float] = (0.05, 1.5)
    beam_sigma_pitch_bounds_deg: tuple[float, float] = (2.0, 60.0)
    normalized_rate_prior_count: float = 0.5
    normalized_max_log10_std: float = 0.5

    def __post_init__(self) -> None:
        if self.loss_cone_model not in {"flexible", "fixed", "shared"}:
            raise ValueError("loss_cone_model must be 'flexible', 'fixed', or 'shared'")
        if self.spectrum_knots < 4:
            raise ValueError("spectrum_knots must be at least 4")
        if self.loss_cone_model == "flexible" and self.hemisphere_baseline_knots < 2:
            raise ValueError("hemisphere_baseline_knots must be at least 2")
        if self.normalized_energy_bins < 4:
            raise ValueError("normalized_energy_bins must be at least 4")
        if self.normalized_min_counts < 1:
            raise ValueError("normalized_min_counts must be positive")
        if (
            not np.isfinite(self.normalized_rate_prior_count)
            or self.normalized_rate_prior_count <= 0.0
        ):
            raise ValueError("normalized_rate_prior_count must be finite and positive")
        if (
            not np.isfinite(self.normalized_max_log10_std)
            or self.normalized_max_log10_std <= 0.0
        ):
            raise ValueError("normalized_max_log10_std must be finite and positive")
        if not (
            np.all(np.isfinite(self.energy_bounds_eV))
            and 0.0 < self.energy_bounds_eV[0] < self.energy_bounds_eV[1]
        ):
            raise ValueError("energy_bounds_eV must be finite, positive, and increasing")
        if self.spectrum_smoothness < 0.0:
            raise ValueError("spectrum_smoothness must be non-negative")
        if self.sensor_gain_log_bounds[0] >= self.sensor_gain_log_bounds[1]:
            raise ValueError("sensor_gain_log_bounds must be increasing")
        if self.energy_response_samples < 1 or self.pitch_response_samples < 1:
            raise ValueError("response sample counts must be positive")
        if self.edge_transition not in {"auto", "hard", "smooth"}:
            raise ValueError("edge_transition must be 'auto', 'hard', or 'smooth'")
        if self.smooth_screen_pitch_samples < 1:
            raise ValueError("smooth_screen_pitch_samples must be positive")
        if not np.isfinite(self.smooth_screen_delta_bic):
            raise ValueError("smooth_screen_delta_bic must be finite")
        if self.smooth_screen_max_iterations < 1:
            raise ValueError("smooth_screen_max_iterations must be positive")
        if self.smooth_refine_optimizer_starts < 1:
            raise ValueError("smooth_refine_optimizer_starts must be positive")
        if (
            not np.isfinite(self.contrast_screen_delta_bic_margin)
            or self.contrast_screen_delta_bic_margin < 0.0
        ):
            raise ValueError("contrast_screen_delta_bic_margin must be finite and non-negative")
        if self.contrast_screen_pitch_samples < 1:
            raise ValueError("contrast_screen_pitch_samples must be positive")
        if self.contrast_screen_max_iterations < 1:
            raise ValueError("contrast_screen_max_iterations must be positive")
        if self.contrast_refine_optimizer_starts < 1:
            raise ValueError("contrast_refine_optimizer_starts must be positive")
        if self.background_model not in {"none", "sensor_constant"}:
            raise ValueError("background_model must be 'none' or 'sensor_constant'")
        if not 0.0 < self.background_rate_bounds_hz[0] < self.background_rate_bounds_hz[1]:
            raise ValueError("background_rate_bounds_hz must be finite, positive, and increasing")
        if self.secondary_beam not in {"off", "on", "auto"}:
            raise ValueError("secondary_beam must be 'off', 'on', or 'auto'")
        if (
            not np.isfinite(self.min_secondary_beam_delta_bic)
            or self.min_secondary_beam_delta_bic < 0.0
        ):
            raise ValueError("min_secondary_beam_delta_bic must be finite and non-negative")
        if self.beam_screen_pitch_samples < 1:
            raise ValueError("beam_screen_pitch_samples must be positive")
        if (
            not np.isfinite(self.beam_screen_delta_bic_margin)
            or self.beam_screen_delta_bic_margin < 0.0
        ):
            raise ValueError("beam_screen_delta_bic_margin must be finite and non-negative")
        if self.beam_screen_max_iterations < 1:
            raise ValueError("beam_screen_max_iterations must be positive")
        if self.beam_screen_optimizer_starts < 1:
            raise ValueError("beam_screen_optimizer_starts must be positive")
        if self.beam_refine_optimizer_starts < 1:
            raise ValueError("beam_refine_optimizer_starts must be positive")
        for name, bounds in (
            ("beam_amplitude_bounds", self.beam_amplitude_bounds),
            ("beam_center_bounds_eV", self.beam_center_bounds_eV),
            ("beam_sigma_ln_energy_bounds", self.beam_sigma_ln_energy_bounds),
            ("beam_sigma_pitch_bounds_deg", self.beam_sigma_pitch_bounds_deg),
        ):
            if not 0.0 < bounds[0] < bounds[1]:
                raise ValueError(f"{name} must be positive and increasing")


@dataclass(frozen=True)
class GlobalNormalizedFlux:
    """Folded affected/reference normalized-rate posterior summary."""

    energy_eV: FloatArray
    pitch_deg: FloatArray
    observed_log_ratio: FloatArray
    fitted_log_ratio: FloatArray
    affected_exposure: FloatArray
    reference_exposure: FloatArray
    energy_edges_eV: FloatArray | None = None
    affected_counts: FloatArray | None = None
    reference_counts: FloatArray | None = None
    affected_normalized_exposure: FloatArray | None = None
    reference_normalized_exposure: FloatArray | None = None
    observed_log_ratio_std: FloatArray | None = None
    total_raw_counts: FloatArray | None = None
    reliable: NDArray[np.bool_] | None = None
    affected_corrected_counts: FloatArray | None = None
    reference_corrected_counts: FloatArray | None = None


@dataclass(frozen=True)
class GlobalFullFOV:
    """S1/S2 sufficient statistics on one common 0--180 degree grid."""

    energy_eV: FloatArray
    energy_edges_eV: FloatArray
    pitch_deg: FloatArray
    pitch_edges_deg: FloatArray
    observed_log_normalized_flux: FloatArray
    fitted_log_normalized_flux: FloatArray
    corrected_counts: FloatArray
    posterior_counts: FloatArray
    fitted_counts: FloatArray
    raw_counts: FloatArray
    exposure: FloatArray
    normalized_exposure: FloatArray
    affected_side: Literal["low", "high"]


@dataclass(frozen=True)
class GlobalSensorFit:
    name: str
    energy_eV: FloatArray
    pitch_deg: FloatArray
    affected_side: Literal["low", "high"]
    valid: NDArray[np.bool_]
    observed_log_rate: FloatArray
    fitted_log_rate: FloatArray
    observed_log_normalized_flux: FloatArray
    fitted_log_normalized_flux: FloatArray
    standardized_residual: FloatArray
    sensor_gain: float
    dispersion: float
    background_rate_hz: float
    dead_time_seconds: float
    response_kind: str
    total_counts: int
    n_cells: int
    exposure: FloatArray | None = None
    observed_normalized_flux: FloatArray | None = None
    energy_edges_eV: FloatArray | None = None
    pitch_edges_deg: FloatArray | None = None
    count_correction: str = "none"
    count_correction_order: str = "trash_then_event"
    invalid_exposure_count_cells: int = 0


@dataclass(frozen=True)
class GlobalJointModelFit:
    model: CandidateModel
    contrast_model: ResolvedContrastModel
    success: bool
    reason: str
    mirror_ratio: float | None
    delta_u_eff_eV: float | None
    sigma_ln_b: float | None
    secondary_beam_enabled: bool
    beam_amplitude: float | None
    beam_center_eV: float | None
    beam_sigma_ln_energy: float | None
    beam_sigma_pitch_deg: float | None
    secondary_beam_delta_bic: float
    log_likelihood: float | None
    bic: float | None
    n_parameters: int
    n_cells: int
    at_bounds: tuple[str, ...]
    sensors: tuple[GlobalSensorFit, ...]
    normalized_flux: GlobalNormalizedFlux | None
    hemisphere_baseline_energy_eV: tuple[float, ...] = ()
    hemisphere_baseline_log_ratio: tuple[float, ...] = ()
    loss_cone_model: LossConeModel = "flexible"
    boundary_bracket_fraction: float | None = None
    strict_boundary_bracket_fraction: float | None = None
    transition_model: ResolvedEdgeTransition = "smooth"
    smooth_transition_delta_bic: float = float("nan")
    smooth_transition_screen_delta_bic: float = float("nan")
    smooth_transition_refined: bool = False
    secondary_beam_screen_delta_bic: float = float("nan")
    secondary_beam_refined: bool = False
    _parameter_names: tuple[str, ...] = field(default=(), repr=False, compare=False)
    _parameter_values: tuple[float, ...] = field(default=(), repr=False, compare=False)
    global_fov: GlobalFullFOV | None = None

    def sensor(self, name: str) -> GlobalSensorFit:
        for sensor in self.sensors:
            if sensor.name == name:
                return sensor
        raise KeyError(name)


@dataclass(frozen=True)
class GlobalJointEstimate:
    success: bool
    reason: str
    selected_model: CandidateModel
    edge_supported: bool
    mirror_ratio: float | None
    effective_field_nT: float | None
    delta_u_eff_eV: float | None
    sigma_ln_b: float | None
    representative_b_sc_nT: float
    no_edge_delta_bic: float
    electrostatic_delta_bic: float
    contrast_band_delta_bic: float
    contrast_band_screen_delta_bic: float
    contrast_band_refined: bool
    model_fits: tuple[GlobalJointModelFit, ...]
    spacecraft_potential_eV: float = 0.0

    def fit(self, model: CandidateModel) -> GlobalJointModelFit:
        for fit in self.model_fits:
            if fit.model == model:
                return fit
        raise KeyError(model)

    @property
    def normalized_flux(self) -> GlobalNormalizedFlux:
        flux = self.fit(self.selected_model).normalized_flux
        if flux is None:
            raise RuntimeError("selected fit has no normalized-flux reconstruction")
        return flux

    def to_record(self) -> dict[str, object]:
        selected = self.fit(self.selected_model)
        record: dict[str, object] = {
            "success": self.success,
            "reason": self.reason,
            "selected_model": self.selected_model,
            "edge_supported": self.edge_supported,
            "mirror_ratio": self.mirror_ratio,
            "effective_field_nT": self.effective_field_nT,
            "delta_u_eff_eV": self.delta_u_eff_eV,
            "sigma_ln_b": self.sigma_ln_b,
            "no_edge_delta_bic": self.no_edge_delta_bic,
            "electrostatic_delta_bic": self.electrostatic_delta_bic,
            "contrast_band_delta_bic": self.contrast_band_delta_bic,
            "contrast_band_screen_delta_bic": self.contrast_band_screen_delta_bic,
            "contrast_band_refined": self.contrast_band_refined,
            "spacecraft_potential_eV": self.spacecraft_potential_eV,
            "contrast_model": selected.contrast_model,
            "loss_cone_model": selected.loss_cone_model,
            "transition_model": selected.transition_model,
            "smooth_transition_delta_bic": selected.smooth_transition_delta_bic,
            "smooth_transition_screen_delta_bic": (
                selected.smooth_transition_screen_delta_bic
            ),
            "smooth_transition_refined": selected.smooth_transition_refined,
            "secondary_beam_enabled": selected.secondary_beam_enabled,
            "beam_amplitude": selected.beam_amplitude,
            "beam_center_eV": selected.beam_center_eV,
            "beam_sigma_ln_energy": selected.beam_sigma_ln_energy,
            "beam_sigma_pitch_deg": selected.beam_sigma_pitch_deg,
            "secondary_beam_delta_bic": selected.secondary_beam_delta_bic,
            "secondary_beam_screen_delta_bic": (
                selected.secondary_beam_screen_delta_bic
            ),
            "secondary_beam_refined": selected.secondary_beam_refined,
            "hemisphere_baseline_energy_eV": ";".join(
                f"{value:.8g}" for value in selected.hemisphere_baseline_energy_eV
            ),
            "hemisphere_baseline_log10_ratio": ";".join(
                f"{value / np.log(10.0):.8g}"
                for value in selected.hemisphere_baseline_log_ratio
            ),
            "boundary_bracket_fraction": selected.boundary_bracket_fraction,
            "strict_boundary_bracket_fraction": selected.strict_boundary_bracket_fraction,
            "n_cells": selected.n_cells,
            "n_parameters": selected.n_parameters,
            "at_bounds": ",".join(selected.at_bounds),
        }
        sensor_totals: dict[str, tuple[int, int, int]] = {}
        for sensor in selected.sensors:
            previous = sensor_totals.get(sensor.name, (0, 0, 0))
            sensor_totals[sensor.name] = (
                previous[0] + sensor.invalid_exposure_count_cells,
                previous[1] + sensor.n_cells,
                previous[2] + sensor.total_counts,
            )
        emitted: set[str] = set()
        for sensor in selected.sensors:
            if sensor.name in emitted:
                continue
            emitted.add(sensor.name)
            prefix = sensor.name.lower().replace("-", "_")
            invalid_cells, n_cells, total_counts = sensor_totals[sensor.name]
            record[f"{prefix}_gain"] = sensor.sensor_gain
            record[f"{prefix}_dispersion"] = sensor.dispersion
            record[f"{prefix}_background_rate_hz"] = sensor.background_rate_hz
            record[f"{prefix}_dead_time_seconds"] = sensor.dead_time_seconds
            record[f"{prefix}_response_kind"] = sensor.response_kind
            record[f"{prefix}_count_correction"] = sensor.count_correction
            record[f"{prefix}_count_correction_order"] = sensor.count_correction_order
            record[f"{prefix}_invalid_exposure_count_cells"] = invalid_cells
            record[f"{prefix}_n_cells"] = n_cells
            record[f"{prefix}_total_counts"] = total_counts
        return record


@dataclass(frozen=True)
class _PreparedGlobalObservation:
    name: str
    sensor_group: str
    energy_eV: FloatArray
    pitch_deg: FloatArray
    folded_pitch_deg: FloatArray
    energy_response_eV: FloatArray
    energy_response_weights: FloatArray
    folded_pitch_response_deg: FloatArray
    pitch_response_weights: FloatArray
    energy_edges_eV: FloatArray
    pitch_edges_deg: FloatArray
    physical_energy_row: NDArray[np.bool_]
    affected: NDArray[np.bool_]
    affected_side: Literal["low", "high"]
    counts: FloatArray
    exposure: FloatArray
    detector_response_matrix: FloatArray | None
    known_background_counts: FloatArray
    live_time_capacity_seconds: FloatArray
    dead_time_seconds: float
    response_kind: str
    count_correction: str
    count_correction_order: str
    invalid_exposure_count_cells: int
    valid: NDArray[np.bool_]
    b_sc_nT: float


@dataclass(frozen=True)
class _Layout:
    model: CandidateModel
    contrast_model: ResolvedContrastModel
    transition_model: ResolvedEdgeTransition
    physical: slice
    spectrum: slice
    hemisphere_baseline: slice
    contrast: slice | None
    beam: slice | None
    gains: slice
    backgrounds: slice
    dispersions: slice
    size: int


@dataclass(frozen=True)
class _Problem:
    observations: tuple[_PreparedGlobalObservation, ...]
    sensor_names: tuple[str, ...]
    sensor_indices: tuple[int, ...]
    layout: _Layout
    log_energy_knots: FloatArray
    log_baseline_knots: FloatArray
    initial: FloatArray
    bounds: tuple[tuple[float, float], ...]
    names: tuple[str, ...]
    settings: GlobalJointFitSettings


class _NativeObjective(Protocol):
    def objective(self, parameters: FloatArray, /) -> float: ...

    def value_and_gradient(
        self,
        parameters: FloatArray,
        /,
    ) -> tuple[float, FloatArray]: ...

    def value_and_gradient_indices(
        self,
        parameters: FloatArray,
        indices: list[int],
        /,
    ) -> tuple[float, FloatArray]: ...


def _native_hard_problem(problem: _Problem) -> _NativeObjective | None:
    layout = problem.layout
    if layout.transition_model not in {"none", "hard"}:
        return None
    try:
        from sopran import _native
    except ImportError:
        return None
    problem_type = getattr(_native, "GlobalHardProblem", None)
    if problem_type is None:
        return None

    def parameter_range(value: slice) -> tuple[int, int]:
        return int(value.start), int(value.stop)

    payload = {
        "model": layout.model,
        "contrast_model": layout.contrast_model,
        "physical": parameter_range(layout.physical),
        "spectrum": parameter_range(layout.spectrum),
        "baseline": parameter_range(layout.hemisphere_baseline),
        "contrast": None if layout.contrast is None else parameter_range(layout.contrast),
        "beam": None if layout.beam is None else parameter_range(layout.beam),
        "gains": parameter_range(layout.gains),
        "backgrounds": parameter_range(layout.backgrounds),
        "dispersions": parameter_range(layout.dispersions),
        "parameter_count": layout.size,
        "sensor_count": len(problem.sensor_names),
        "bounds": np.asarray(problem.bounds, dtype=float),
        "log_energy_knots": np.asarray(problem.log_energy_knots, dtype=float),
        "log_baseline_knots": np.asarray(problem.log_baseline_knots, dtype=float),
        "spacecraft_potential_eV": (
            problem.settings.effective_field.spacecraft_potential_eV
        ),
        "spectrum_smoothness": problem.settings.spectrum_smoothness,
        "observations": [
            {
                "sensor_index": problem.sensor_indices[index],
                "b_sc_nT": observation.b_sc_nT,
                "energy_response_eV": np.asarray(
                    observation.energy_response_eV,
                    dtype=float,
                ),
                "energy_response_weights": np.asarray(
                    observation.energy_response_weights,
                    dtype=float,
                ),
                "pitch_edges_deg": np.asarray(observation.pitch_edges_deg, dtype=float),
                "folded_pitch_response_deg": np.asarray(
                    observation.folded_pitch_response_deg,
                    dtype=float,
                ),
                "pitch_response_weights": np.asarray(
                    observation.pitch_response_weights,
                    dtype=float,
                ),
                "physical_energy_row": np.asarray(
                    observation.physical_energy_row,
                    dtype=bool,
                ),
                "affected": np.asarray(observation.affected, dtype=bool),
                "counts": np.asarray(observation.counts, dtype=float),
                "exposure": np.asarray(observation.exposure, dtype=float),
                "known_background_counts": np.asarray(
                    observation.known_background_counts,
                    dtype=float,
                ),
                "live_time_capacity_seconds": np.asarray(
                    observation.live_time_capacity_seconds,
                    dtype=float,
                ),
                "dead_time_seconds": observation.dead_time_seconds,
                "valid": np.asarray(observation.valid, dtype=bool),
                "detector_response_matrix": (
                    None
                    if observation.detector_response_matrix is None
                    else np.asarray(observation.detector_response_matrix, dtype=float)
                ),
            }
            for index, observation in enumerate(problem.observations)
        ],
    }
    return cast(_NativeObjective, problem_type(payload))


def fit_global_joint_effective_field(
    observations: Mapping[str, GlobalPitchCountObservation],
    *,
    settings: GlobalJointFitSettings | None = None,
) -> GlobalJointEstimate:
    """Fit raw full-pitch sensor counts through a shared latent flux surface."""

    settings = settings or GlobalJointFitSettings()
    if len(observations) < 2:
        raise ValueError("global joint fitting requires at least two sensors")
    prepared_all = tuple(
        _prepare_observation(str(name), observation, settings)
        for name, observation in observations.items()
    )
    prepared = tuple(item for item in prepared_all if np.count_nonzero(item.valid) > 0)
    if len({item.sensor_group for item in prepared}) < 2:
        raise ValueError("global joint fitting requires at least two sensor groups")
    _validate_global_support(prepared, settings)
    total_counts = sum(int(np.nansum(item.counts[item.valid])) for item in prepared)
    if total_counts < settings.effective_field.min_total_counts:
        raise ValueError("global observations have insufficient total counts")

    no_edge = _fit_candidate_with_beam(prepared, "no_edge", "none", settings)
    (
        mirror,
        mirror_contrast_delta,
        mirror_contrast_screen_delta,
        mirror_contrast_refined,
    ) = _fit_edge_contrast(
        prepared,
        "mirror_only",
        settings,
    )
    (
        electrostatic,
        electrostatic_contrast_delta,
        electrostatic_contrast_screen_delta,
        electrostatic_contrast_refined,
    ) = _fit_edge_contrast(
        prepared,
        "electrostatic",
        settings,
    )
    no_edge_delta = _bic_improvement(no_edge, mirror)
    electrostatic_delta = _bic_improvement(mirror, electrostatic)
    selected, reason = _select_global_model(
        no_edge,
        mirror,
        electrostatic,
        settings,
    )
    contrast_delta = (
        electrostatic_contrast_delta
        if selected.model == "electrostatic"
        else mirror_contrast_delta
    )
    contrast_screen_delta = (
        electrostatic_contrast_screen_delta
        if selected.model == "electrostatic"
        else mirror_contrast_screen_delta
    )
    contrast_refined = (
        electrostatic_contrast_refined
        if selected.model == "electrostatic"
        else mirror_contrast_refined
    )

    representative_b = float(np.median([item.b_sc_nT for item in prepared]))
    edge = selected.model != "no_edge"
    return GlobalJointEstimate(
        success=selected.success,
        reason=reason if selected.success else selected.reason,
        selected_model=selected.model,
        edge_supported=edge,
        mirror_ratio=selected.mirror_ratio if edge else None,
        effective_field_nT=(
            representative_b * cast(float, selected.mirror_ratio) if edge else None
        ),
        delta_u_eff_eV=(selected.delta_u_eff_eV if selected.model == "electrostatic" else None),
        sigma_ln_b=selected.sigma_ln_b if edge else None,
        representative_b_sc_nT=representative_b,
        no_edge_delta_bic=no_edge_delta,
        electrostatic_delta_bic=electrostatic_delta,
        contrast_band_delta_bic=contrast_delta,
        contrast_band_screen_delta_bic=contrast_screen_delta,
        contrast_band_refined=contrast_refined,
        model_fits=(no_edge, mirror, electrostatic),
        spacecraft_potential_eV=settings.effective_field.spacecraft_potential_eV,
    )


def plot_global_joint_effective_field_fit(
    estimate: GlobalJointEstimate,
    *,
    path: str | Path | None = None,
    model: CandidateModel | Literal["selected", "best_edge"] = "selected",
    pitch_orientation: PitchOrientation = "physical",
) -> Any:
    """Plot sensor-native surfaces and the globally folded normalized flux.

    Log-ratio surfaces are displayed in base-10 units.  The raw-count
    likelihood and its internal positive-parameter transforms remain in
    natural-log units; changing the display base does not change the fit.
    """

    import matplotlib.pyplot as plt  # type: ignore[import-untyped]
    from matplotlib.lines import Line2D  # type: ignore[import-untyped]
    from matplotlib.patches import Patch  # type: ignore[import-untyped]

    if pitch_orientation not in {"physical", "native"}:
        raise ValueError("pitch_orientation must be 'physical' or 'native'")
    fit = _plot_fit(estimate, model)
    flux = fit.normalized_flux
    if flux is None:
        raise RuntimeError("fit has no normalized flux")
    energy_bounds = _normalized_flux_energy_bounds(flux)
    plot_sensors = _group_sensor_fits_for_plot(
        fit.sensors,
        energy_bounds=energy_bounds,
        energy_bins=flux.energy_eV.size,
    )
    rows = len(plot_sensors) + 2
    figure, axes = plt.subplots(
        rows,
        3,
        figsize=(14.8, 3.7 * rows),
        squeeze=False,
        constrained_layout=True,
    )
    missing_color = "#404040"
    cmap = plt.colormaps["RdBu_r"].with_extremes(bad=missing_color)
    log10_scale = 1.0 / np.log(10.0)
    log10_limit = 4.0 * log10_scale
    for row, sensor in enumerate(plot_sensors):
        observed_sensor_log = sensor.observed_log_normalized_flux.copy()
        if sensor.observed_normalized_flux is not None:
            observed_sensor_log[sensor.observed_normalized_flux == 0.0] = np.log(
                np.finfo(float).tiny
            )
        panels = (
            (
                observed_sensor_log * log10_scale,
                "Observed normalized flux",
                log10_limit,
            ),
            (
                sensor.fitted_log_normalized_flux * log10_scale,
                "Fitted normalized flux",
                log10_limit,
            ),
            (sensor.standardized_residual, "Standardized count residual", 4.0),
        )
        order = np.argsort(sensor.energy_eV)
        meshes = []
        for column, (values, title, limit) in enumerate(panels):
            display_pitch, display_values = _orient_pitch_surface(
                sensor.pitch_deg,
                values[order],
                affected_side=sensor.affected_side,
                orientation=pitch_orientation,
            )
            mesh = axes[row, column].pcolormesh(
                display_pitch,
                sensor.energy_eV[order],
                np.ma.masked_invalid(display_values),
                shading="nearest",
                cmap=cmap,
                vmin=-limit,
                vmax=limit,
            )
            meshes.append(mesh)
            axes[row, column].set(
                yscale="log",
                ylim=energy_bounds,
                xlim=(0.0, 180.0),
                xlabel=(
                    "Moon-oriented pitch [deg] (0: outgoing)"
                    if pitch_orientation == "physical"
                    else "Native pitch [deg] (+B to -B)"
                ),
                title=f"{sensor.name}: {title}",
            )
            axes[row, column].axvline(90.0, color="#606060", linewidth=0.7, alpha=0.7)
        axes[row, 0].set_ylabel("Energy [eV]")
        figure.colorbar(
            meshes[1],
            ax=list(axes[row, :2]),
            pad=0.01,
            label="log10(normalized rate)",
        )
        figure.colorbar(
            meshes[2],
            ax=axes[row, 2],
            pad=0.01,
            label="standardized residual",
        )

    combined_energy, combined_pitch, combined_observed, combined_fitted, _ = (
        _combined_full_fov(fit, orientation=pitch_orientation)
    )
    combined_row = len(plot_sensors)
    combined_panels = (
        (combined_observed * log10_scale, "Combined global FOV: observed normalized flux"),
        (combined_fitted * log10_scale, "Combined global FOV: fitted normalized flux"),
        (
            (combined_observed - combined_fitted) * log10_scale,
            "Combined global FOV: log residual",
        ),
    )
    combined_meshes = []
    for column, (values, title) in enumerate(combined_panels):
        mesh = axes[combined_row, column].pcolormesh(
            combined_pitch,
            combined_energy,
            np.ma.masked_invalid(values),
            shading="nearest",
            cmap=cmap,
            vmin=-log10_limit,
            vmax=log10_limit,
        )
        combined_meshes.append(mesh)
        axes[combined_row, column].set(
            yscale="log",
            ylim=energy_bounds,
            xlim=(0.0, 180.0),
            xlabel=(
                "Moon-oriented pitch [deg] (0: outgoing)"
                if pitch_orientation == "physical"
                else "Native pitch [deg] (+B to -B)"
            ),
            title=title,
        )
        axes[combined_row, column].axvline(
            90.0,
            color="#606060",
            linewidth=0.7,
            alpha=0.7,
        )
    axes[combined_row, 0].set_ylabel("Energy [eV]")
    figure.colorbar(
        combined_meshes[1],
        ax=list(axes[combined_row, :]),
        pad=0.01,
        label="log10(exposure-weighted normalized rate)",
    )

    folded_panels = (
        (
            flux.observed_log_ratio * log10_scale,
            "Global-FOV fold: observed posterior rate ratio",
        ),
        (flux.fitted_log_ratio * log10_scale, "Global folded model ratio"),
        (
            (flux.observed_log_ratio - flux.fitted_log_ratio) * log10_scale,
            "Global folded residual",
        ),
    )
    selected_fit = estimate.fit(estimate.selected_model)
    boundary_lines: list[tuple[FloatArray, str, str, str]] = []
    selected_boundary = _boundary_pitch(
        selected_fit,
        flux.energy_eV,
        spacecraft_potential_eV=estimate.spacecraft_potential_eV,
    )
    if np.any(np.isfinite(selected_boundary)):
        boundary_lines.append(
            (
                selected_boundary,
                f"Selected boundary: {selected_fit.model}",
                "black",
                "-",
            )
        )
    if fit.model != selected_fit.model:
        shown_boundary = _boundary_pitch(
            fit,
            flux.energy_eV,
            spacecraft_potential_eV=estimate.spacecraft_potential_eV,
        )
        if np.any(np.isfinite(shown_boundary)):
            boundary_lines.append(
                (
                    shown_boundary,
                    f"Non-selected diagnostic: {fit.model}",
                    "#D55E00",
                    "--",
                )
            )
    low_count = (
        np.zeros(flux.observed_log_ratio.shape, dtype=bool)
        if flux.reliable is None
        else np.isfinite(flux.observed_log_ratio) & ~flux.reliable
    )
    folded_pitch_grid, folded_energy_grid = np.meshgrid(
        flux.pitch_deg,
        flux.energy_eV,
    )
    for column, (values, title) in enumerate(folded_panels):
        mesh = axes[-1, column].pcolormesh(
            flux.pitch_deg,
            flux.energy_eV,
            np.ma.masked_invalid(values),
            shading="nearest",
            cmap=cmap,
            vmin=-log10_limit,
            vmax=log10_limit,
        )
        axes[-1, column].set(
            yscale="log",
            ylim=energy_bounds,
            xlim=(0.0, 90.0),
            xlabel="Folded pitch [deg] (0: field-aligned, 90: perpendicular)",
            title=title,
        )
        for boundary_pitch, label, color, linestyle in boundary_lines:
            axes[-1, column].plot(
                boundary_pitch,
                flux.energy_eV,
                color=color,
                linewidth=1.4,
                linestyle=linestyle,
                label=label,
            )
        if np.any(low_count):
            axes[-1, column].scatter(
                folded_pitch_grid[low_count],
                folded_energy_grid[low_count],
                s=5.0,
                marker=".",
                color="#303030",
                alpha=0.45,
                linewidths=0.0,
                zorder=3,
            )
    axes[-1, 0].set_ylabel("Energy [eV]")
    figure.colorbar(
        mesh,
        ax=list(axes[-1, :]),
        pad=0.01,
        label="log10(affected/reference)",
    )
    fitted_field = (
        None if fit.mirror_ratio is None else estimate.representative_b_sc_nT * fit.mirror_ratio
    )
    selected_field = (
        None
        if selected_fit.mirror_ratio is None
        else estimate.representative_b_sc_nT * selected_fit.mirror_ratio
    )
    shown_role = (
        "selected" if fit.model == estimate.selected_model else "rejected diagnostic candidate"
    )
    shown_edge_delta = (
        float("nan") if fit.model == "no_edge" else _bic_improvement(estimate.fit("no_edge"), fit)
    )
    beam_summary = (
        f"beam={_format(fit.beam_center_eV, ' eV')} "
        f"(DeltaBIC={_format(fit.secondary_beam_delta_bic)})"
        if fit.secondary_beam_enabled
        else f"beam=off (DeltaBIC={_format(fit.secondary_beam_delta_bic)})"
    )
    baseline_log10 = np.asarray(fit.hemisphere_baseline_log_ratio) / np.log(10.0)
    baseline_summary = (
        "baseline=n/a"
        if baseline_log10.size == 0
        else (
            f"baseline log10(a/r)={np.min(baseline_log10):.3g}.."
            f"{np.max(baseline_log10):.3g}"
        )
    )
    figure.suptitle(
        f"Global-FOV raw-count joint ER fit | shown={fit.model} ({shown_role}) | "
        f"selected={estimate.selected_model} ({estimate.reason})\n"
        f"R_m(shown)={_format(fit.mirror_ratio)} | "
        f"B_eff(shown)={_format(fitted_field, ' nT')} | "
        f"transition(shown)={fit.transition_model} | "
        f"DeltaBIC(hard->smooth)={_format(fit.smooth_transition_delta_bic)} | "
        f"DeltaU={_format(fit.delta_u_eff_eV, ' eV')} | "
        f"DeltaBIC(no_edge->shown)={_format(shown_edge_delta)} | {beam_summary}\n"
        f"R_m(selected)={_format(selected_fit.mirror_ratio)} | "
        f"B_eff(selected)={_format(selected_field, ' nT')} | "
        f"transition(selected)={selected_fit.transition_model} | "
        f"DeltaU(selected)={_format(selected_fit.delta_u_eff_eV, ' eV')}\n"
        f"loss cone={fit.loss_cone_model} | {baseline_summary}\n"
        "S1/S2 remain separate in the likelihood; the combined row is a post-fit "
        "exposure-weighted global FOV diagnostic, and the bottom row is folded.\n"
        + (
            "Moon-oriented display: left=Moon-outgoing/affected, "
            "right=Moon-incoming/reference; sensor rows are not folded."
            if pitch_orientation == "physical"
            else "Native display: 0 deg=+B and 180 deg=-B; sensor rows are not folded."
        ),
        fontsize=10.5,
    )
    boundary_handles: list[Any] = [
        Line2D(
            [0],
            [0],
            color=color,
            linestyle=linestyle,
            linewidth=1.4,
            label=label,
        )
        for _boundary, label, color, linestyle in boundary_lines
    ]
    if np.any(low_count):
        boundary_handles.append(
            Line2D(
                [0],
                [0],
                color="#303030",
                marker=".",
                linestyle="none",
                markersize=4.0,
                label="Low-confidence posterior",
            )
        )
    if boundary_handles:
        axes[-1, 0].legend(
            handles=boundary_handles,
            loc="upper left",
            frameon=True,
            fontsize=7.5,
        )
    axes[0, 2].legend(
        handles=(
            Patch(facecolor=missing_color, edgecolor="#202020", label="No coverage / NaN"),
            Patch(
                facecolor=cmap(0.5),
                edgecolor="#808080",
                label="log10(normalized rate) = 0",
            ),
            Patch(
                facecolor=cmap(0.0),
                edgecolor="#305080",
                label="Observed zero count (lower color limit)",
            ),
        ),
        loc="upper right",
        frameon=True,
        fontsize=8,
    )
    if path is not None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, dpi=150)
    return figure


def _group_sensor_fits_for_plot(
    sensors: tuple[GlobalSensorFit, ...],
    *,
    energy_bounds: tuple[float, float],
    energy_bins: int,
) -> tuple[GlobalSensorFit, ...]:
    """Combine repeated native records only for the displayed sensor panels."""

    names = tuple(dict.fromkeys(sensor.name for sensor in sensors))
    if len(names) == len(sensors):
        return sensors
    energy_edges = np.geomspace(energy_bounds[0], energy_bounds[1], energy_bins + 1)
    energy = np.sqrt(energy_edges[:-1] * energy_edges[1:])
    grouped: list[GlobalSensorFit] = []
    for name in names:
        members = tuple(sensor for sensor in sensors if sensor.name == name)
        member_pitch_edges = tuple(
            (
                180.0 - cast(FloatArray, sensor.pitch_edges_deg)[::-1]
                if sensor.affected_side == "high"
                else cast(FloatArray, sensor.pitch_edges_deg)
            )
            for sensor in members
            if sensor.pitch_edges_deg is not None
        )
        if len(member_pitch_edges) != len(members):
            return sensors
        source_pitch_edges = np.unique(
            np.concatenate(member_pitch_edges)
        )
        if source_pitch_edges.size < 2:
            return sensors
        source_pitch_edges.sort()
        pitch = 0.5 * (source_pitch_edges[:-1] + source_pitch_edges[1:])
        shape = (energy.size, pitch.size)
        exposure_sum = np.zeros(shape, dtype=float)
        observed_rate_sum = np.zeros(shape, dtype=float)
        fitted_rate_sum = np.zeros(shape, dtype=float)
        observed_normalized_sum = np.zeros(shape, dtype=float)
        fitted_normalized_sum = np.zeros(shape, dtype=float)
        residual_sum = np.zeros(shape, dtype=float)
        for sensor, physical_pitch_edges in zip(
            members, member_pitch_edges, strict=True
        ):
            if (
                sensor.energy_edges_eV is None
                or sensor.pitch_edges_deg is None
                or sensor.exposure is None
            ):
                return sensors
            energy_overlap = _bin_overlap_fraction_with_tails(
                np.log(sensor.energy_edges_eV), np.log(energy_edges)
            )
            pitch_overlap = _bin_overlap_fraction(
                physical_pitch_edges, source_pitch_edges
            )
            reverse = sensor.affected_side == "high"
            oriented_valid = sensor.valid[:, ::-1] if reverse else sensor.valid
            oriented_exposure = sensor.exposure[:, ::-1] if reverse else sensor.exposure
            weight = np.where(oriented_valid, oriented_exposure, 0.0)
            exposure_sum += _aggregate_bin_overlap(
                weight, oriented_valid, energy_overlap, pitch_overlap
            )

            def weighted(
                values: FloatArray,
                *,
                source: GlobalSensorFit = sensor,
                source_weight: FloatArray = weight,
                source_energy_overlap: FloatArray = energy_overlap,
                source_pitch_overlap: FloatArray = pitch_overlap,
                source_reverse: bool = reverse,
                source_valid: NDArray[np.bool_] = oriented_valid,
            ) -> FloatArray:
                oriented_values = values[:, ::-1] if source_reverse else values
                valid = source_valid & np.isfinite(oriented_values) & (source_weight > 0.0)
                return _aggregate_bin_overlap(
                    np.where(valid, oriented_values * source_weight, 0.0),
                    valid,
                    source_energy_overlap,
                    source_pitch_overlap,
                )

            observed_rate_sum += weighted(
                np.exp(np.clip(sensor.observed_log_rate, -100.0, 100.0))
            )
            fitted_rate_sum += weighted(
                np.exp(np.clip(sensor.fitted_log_rate, -100.0, 100.0))
            )
            observed_normalized = (
                sensor.observed_normalized_flux
                if sensor.observed_normalized_flux is not None
                else np.exp(
                    np.clip(sensor.observed_log_normalized_flux, -100.0, 100.0)
                )
            )
            observed_normalized_sum += weighted(observed_normalized)
            fitted_normalized_sum += weighted(
                np.exp(np.clip(sensor.fitted_log_normalized_flux, -100.0, 100.0))
            )
            residual_sum += weighted(sensor.standardized_residual)
        valid = exposure_sum > 0.0

        def mean(
            values: FloatArray,
            *,
            denominator: FloatArray = exposure_sum,
            output_shape: tuple[int, int] = shape,
            supported: NDArray[np.bool_] = valid,
        ) -> FloatArray:
            return np.divide(
                values,
                denominator,
                out=np.full(output_shape, np.nan, dtype=float),
                where=supported,
            )

        observed_rate = mean(observed_rate_sum)
        fitted_rate = mean(fitted_rate_sum)
        observed_normalized = mean(observed_normalized_sum)
        fitted_normalized = mean(fitted_normalized_sum)
        with np.errstate(divide="ignore", invalid="ignore"):
            observed_log_rate = np.log(observed_rate)
            fitted_log_rate = np.log(fitted_rate)
            observed_log_normalized = np.log(observed_normalized)
            fitted_log_normalized = np.log(fitted_normalized)
        first = members[0]
        grouped.append(
            GlobalSensorFit(
                name=name,
                energy_eV=np.asarray(energy, dtype=float),
                pitch_deg=np.asarray(pitch, dtype=float),
                affected_side="low",
                valid=np.asarray(valid, dtype=bool),
                observed_log_rate=np.asarray(observed_log_rate, dtype=float),
                fitted_log_rate=np.asarray(fitted_log_rate, dtype=float),
                observed_log_normalized_flux=np.asarray(
                    observed_log_normalized, dtype=float
                ),
                fitted_log_normalized_flux=np.asarray(
                    fitted_log_normalized, dtype=float
                ),
                standardized_residual=mean(residual_sum),
                sensor_gain=first.sensor_gain,
                dispersion=first.dispersion,
                background_rate_hz=first.background_rate_hz,
                dead_time_seconds=first.dead_time_seconds,
                response_kind="+".join(
                    dict.fromkeys(sensor.response_kind for sensor in members)
                ),
                total_counts=sum(sensor.total_counts for sensor in members),
                n_cells=sum(sensor.n_cells for sensor in members),
                exposure=np.where(valid, exposure_sum, np.nan),
                observed_normalized_flux=observed_normalized,
                energy_edges_eV=np.asarray(energy_edges, dtype=float),
                pitch_edges_deg=np.asarray(source_pitch_edges, dtype=float),
                count_correction=first.count_correction,
                count_correction_order=first.count_correction_order,
                invalid_exposure_count_cells=sum(
                    sensor.invalid_exposure_count_cells for sensor in members
                ),
            )
        )
    return tuple(grouped)


def plot_global_joint_circular_pitch_view(
    estimate: GlobalJointEstimate,
    *,
    path: str | Path | None = None,
    model: CandidateModel | Literal["selected", "best_edge"] = "selected",
) -> Any:
    """Plot the combined pitch-energy surface around the magnetic-field axis.

    The measured 0--180 degree pitch distribution is mirrored around the magnetic
    axis to show its axisymmetric 360 degree interpretation. This does not recover
    gyrophase information.
    """

    import matplotlib.pyplot as plt  # type: ignore[import-untyped]

    fit = _plot_fit(estimate, model)
    energy, pitch, observed, fitted, exposure = _combined_full_fov(
        fit,
        orientation="native",
    )
    pitch_full = np.concatenate((pitch, 360.0 - pitch[::-1]))
    observed_full = np.concatenate((observed, observed[:, ::-1]), axis=1)
    fitted_full = np.concatenate((fitted, fitted[:, ::-1]), axis=1)
    theta_edges = _center_edges(pitch_full, lower=0.0, upper=360.0)
    log_energy = np.log10(energy)
    if fit.normalized_flux is not None and fit.normalized_flux.energy_edges_eV is not None:
        radial_edges = np.log10(fit.normalized_flux.energy_edges_eV)
    else:
        radial_edges = _center_edges(log_energy)
    radial_offset = radial_edges[0]
    radial_centers = log_energy - radial_offset
    radial_edges = radial_edges - radial_offset
    panels = (
        (observed_full / np.log(10.0), "Observed combined global FOV"),
        (fitted_full / np.log(10.0), "Fitted combined global FOV"),
        ((observed_full - fitted_full) / np.log(10.0), "Observed - fitted"),
    )
    low_confidence_full: NDArray[np.bool_] | None = None
    flux = fit.normalized_flux
    if (
        flux is not None
        and flux.reliable is not None
        and flux.reliable.shape[0] == energy.size
        and 2 * flux.reliable.shape[1] == pitch.size
    ):
        low_folded = np.isfinite(flux.observed_log_ratio) & ~flux.reliable
        low_native = np.concatenate((low_folded, low_folded[:, ::-1]), axis=1)
        low_confidence_full = np.concatenate(
            (low_native, low_native[:, ::-1]), axis=1
        )
    limit = 4.0 / np.log(10.0)
    missing_color = "#404040"
    cmap = plt.colormaps["RdBu_r"].with_extremes(bad=missing_color)
    figure, axes = plt.subplots(
        1,
        3,
        figsize=(15.6, 5.4),
        subplot_kw={"projection": "polar"},
        constrained_layout=True,
    )
    mesh = None
    theta_grid, radial_grid = np.meshgrid(np.deg2rad(pitch_full), radial_centers)
    for axis_index, (axis, (values, title)) in enumerate(
        zip(axes, panels, strict=True)
    ):
        mesh = axis.pcolormesh(
            np.deg2rad(theta_edges),
            radial_edges,
            np.ma.masked_invalid(values),
            cmap=cmap,
            vmin=-limit,
            vmax=limit,
            shading="flat",
        )
        axis.set_theta_zero_location("N")
        axis.set_theta_direction(-1)
        axis.set_thetagrids(
            np.arange(0.0, 360.0, 45.0),
            labels=("+B", "45", "90", "135", "-B", "135", "90", "45"),
        )
        tick_energies = np.geomspace(float(energy[0]), float(energy[-1]), 4)
        tick_radii = np.log10(tick_energies) - radial_offset
        axis.set_yticks(tick_radii)
        axis.set_yticklabels([f"{value:.0f} eV" for value in tick_energies])
        axis.set_rlabel_position(22.5)
        axis.set_ylim(0.0, float(radial_edges[-1]))
        axis.set_title(title, pad=18)
        if low_confidence_full is not None and np.any(low_confidence_full):
            axis.scatter(
                theta_grid[low_confidence_full],
                radial_grid[low_confidence_full],
                s=5.0,
                marker=".",
                color="#303030",
                alpha=0.45,
                linewidths=0.0,
                label=("Low-confidence folded pair" if axis_index == 0 else None),
                zorder=3,
            )
        axis.annotate(
            "",
            xy=(0.0, float(radial_edges[-1]) * 0.98),
            xytext=(0.0, 0.05),
            arrowprops={"arrowstyle": "-|>", "color": "black", "linewidth": 1.5},
            ha="center",
            va="bottom",
            fontsize=8,
        )
    assert mesh is not None
    boundary = _boundary_pitch(
        fit,
        energy,
        spacecraft_potential_eV=estimate.spacecraft_potential_eV,
    )
    affected_side = fit.sensors[0].affected_side
    boundary_native = boundary if affected_side == "low" else 180.0 - boundary
    boundary_pitch_edges = _center_edges(pitch, lower=0.0, upper=180.0)
    boundary_pitch_index = np.clip(
        np.digitize(boundary_native, boundary_pitch_edges) - 1,
        0,
        pitch.size - 1,
    )
    boundary_supported = np.isfinite(boundary) & (
        exposure[np.arange(energy.size), boundary_pitch_index] > 0.0
    )
    boundary[~boundary_supported] = np.nan
    selected_fit = estimate.fit(estimate.selected_model)
    shown_is_selected = fit.model == selected_fit.model
    boundary_label = (
        f"Selected boundary: {fit.model}"
        if shown_is_selected
        else f"Rejected diagnostic boundary: {fit.model}"
    )
    if np.any(np.isfinite(boundary)):
        if affected_side == "low":
            angles = (boundary, 360.0 - boundary)
        else:
            angles = (180.0 - boundary, 180.0 + boundary)
        for axis in axes:
            for index, angle in enumerate(angles):
                axis.plot(
                    np.deg2rad(angle),
                    radial_centers,
                    color="black",
                    linewidth=1.3,
                    linestyle="-" if shown_is_selected else "--",
                    label=boundary_label if index == 0 else None,
                )
    if np.any([line.get_label() != "_nolegend_" for line in axes[0].lines]) or (
        low_confidence_full is not None and np.any(low_confidence_full)
    ):
        axes[0].legend(loc="lower left", bbox_to_anchor=(-0.12, -0.08), fontsize=8)
    figure.colorbar(
        mesh,
        ax=list(axes),
        pad=0.06,
        shrink=0.82,
        label="log10(normalized rate or ratio residual)",
    )
    figure.suptitle(
        f"Axisymmetric pitch-energy view | shown={fit.model} "
        f"({'selected' if shown_is_selected else 'rejected diagnostic candidate'}) | "
        f"selected={selected_fit.model}\n"
        "+B is upward | mirrored across the magnetic axis\n"
        "Angular structure is pitch-angle information; gyrophase is not measured here.",
        fontsize=10.5,
    )
    if path is not None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, dpi=160)
    return figure


def _boundary_pitch(
    fit: GlobalJointModelFit,
    energy_eV: FloatArray,
    *,
    spacecraft_potential_eV: float,
) -> FloatArray:
    pitch = np.full(energy_eV.shape, np.nan, dtype=float)
    if fit.mirror_ratio is None:
        return pitch
    boundary = mirror_boundary_sin2(
        energy_eV,
        fit.mirror_ratio,
        fit.delta_u_eff_eV or 0.0,
        spacecraft_potential_eV=spacecraft_potential_eV,
    )
    physical = np.isfinite(boundary) & (boundary >= 0.0) & (boundary <= 1.0)
    pitch[physical] = np.degrees(np.arcsin(np.sqrt(boundary[physical])))
    return pitch


def _orient_pitch_surface(
    pitch_deg: FloatArray,
    values: FloatArray,
    *,
    affected_side: Literal["low", "high"],
    orientation: PitchOrientation,
) -> tuple[FloatArray, FloatArray]:
    display_pitch = (
        180.0 - pitch_deg
        if orientation == "physical" and affected_side == "high"
        else pitch_deg
    )
    order = np.argsort(display_pitch)
    return (
        np.asarray(display_pitch[order], dtype=float),
        np.asarray(values[:, order], dtype=float),
    )


def _combined_full_fov(
    fit: GlobalJointModelFit,
    *,
    orientation: PitchOrientation,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray]:
    if not fit.sensors:
        raise ValueError("fit has no sensor surfaces")
    if fit.normalized_flux is None:
        raise ValueError("fit has no normalized-flux energy grid")
    if fit.global_fov is not None:
        full_fov = fit.global_fov
        reverse = orientation == "physical" and full_fov.affected_side == "high"
        pitch = (
            180.0 - full_fov.pitch_deg[::-1]
            if reverse
            else full_fov.pitch_deg
        )
        observed = (
            full_fov.observed_log_normalized_flux[:, ::-1]
            if reverse
            else full_fov.observed_log_normalized_flux
        )
        fitted = (
            full_fov.fitted_log_normalized_flux[:, ::-1]
            if reverse
            else full_fov.fitted_log_normalized_flux
        )
        exposure = (
            full_fov.normalized_exposure[:, ::-1]
            if reverse
            else full_fov.normalized_exposure
        )
        return (
            np.asarray(full_fov.energy_eV, dtype=float),
            np.asarray(pitch, dtype=float),
            np.asarray(observed, dtype=float),
            np.asarray(fitted, dtype=float),
            np.asarray(exposure, dtype=float),
        )
    energy = np.asarray(fit.normalized_flux.energy_eV, dtype=float)
    oriented_pitch = [
        _orient_pitch_surface(
            sensor.pitch_deg,
            sensor.observed_log_normalized_flux,
            affected_side=sensor.affected_side,
            orientation=orientation,
        )[0]
        for sensor in fit.sensors
    ]
    pitch = np.unique(np.round(np.concatenate(oriented_pitch), 8))
    target_log_energy_edges = (
        np.log(np.asarray(fit.normalized_flux.energy_edges_eV, dtype=float))
        if fit.normalized_flux.energy_edges_eV is not None
        else _center_edges(np.log(energy))
    )
    source_energy_edges = [
        (
            np.asarray(sensor.energy_edges_eV, dtype=float)
            if sensor.energy_edges_eV is not None
            and np.all(np.diff(sensor.energy_eV) > 0.0)
            else np.exp(_center_edges(np.log(np.sort(sensor.energy_eV))))
        )
        for sensor in fit.sensors
    ]
    target_pitch_edges = _center_edges(pitch, lower=0.0, upper=180.0)
    shape = (energy.size, pitch.size)
    observed_sum = np.zeros(shape, dtype=float)
    observed_weight = np.zeros(shape, dtype=float)
    fitted_sum = np.zeros(shape, dtype=float)
    fitted_weight = np.zeros(shape, dtype=float)
    total_exposure = np.zeros(shape, dtype=float)
    for sensor, sensor_energy_edges in zip(fit.sensors, source_energy_edges, strict=True):
        energy_order = np.argsort(sensor.energy_eV)
        _, fitted = _orient_pitch_surface(
            sensor.pitch_deg,
            sensor.fitted_log_normalized_flux[energy_order],
            affected_side=sensor.affected_side,
            orientation=orientation,
        )
        raw_observed_linear = (
            np.exp(np.clip(sensor.observed_log_normalized_flux, -100.0, 100.0))
            if sensor.observed_normalized_flux is None
            else sensor.observed_normalized_flux
        )
        _, observed_linear = _orient_pitch_surface(
            sensor.pitch_deg,
            raw_observed_linear[energy_order],
            affected_side=sensor.affected_side,
            orientation=orientation,
        )
        raw_exposure = (
            np.ones_like(sensor.observed_log_normalized_flux)
            if sensor.exposure is None
            else sensor.exposure
        )
        _, exposure = _orient_pitch_surface(
            sensor.pitch_deg,
            raw_exposure[energy_order],
            affected_side=sensor.affected_side,
            orientation=orientation,
        )
        source_pitch_edges = (
            np.asarray(sensor.pitch_edges_deg, dtype=float)
            if sensor.pitch_edges_deg is not None
            else _center_edges(sensor.pitch_deg, lower=0.0, upper=180.0)
        )
        if orientation == "physical" and sensor.affected_side == "high":
            source_pitch_edges = 180.0 - source_pitch_edges[::-1]
        energy_overlap = _bin_overlap_fraction(
            np.log(sensor_energy_edges),
            target_log_energy_edges,
        )
        pitch_overlap = _bin_overlap_fraction(source_pitch_edges, target_pitch_edges)
        valid_exposure = np.where(np.isfinite(exposure) & (exposure > 0.0), exposure, 0.0)
        observed_valid = (
            np.isfinite(observed_linear)
            & (observed_linear >= 0.0)
            & (valid_exposure > 0.0)
        )
        fitted_valid = np.isfinite(fitted) & (valid_exposure > 0.0)
        observed_contribution = np.where(
            observed_valid,
            valid_exposure * observed_linear,
            0.0,
        )
        fitted_contribution = np.where(
            fitted_valid,
            valid_exposure * np.exp(np.clip(fitted, -100.0, 100.0)),
            0.0,
        )
        observed_sum += energy_overlap.T @ observed_contribution @ pitch_overlap
        observed_weight += energy_overlap.T @ np.where(
            observed_valid,
            valid_exposure,
            0.0,
        ) @ pitch_overlap
        fitted_sum += energy_overlap.T @ fitted_contribution @ pitch_overlap
        fitted_weight += energy_overlap.T @ np.where(
            fitted_valid,
            valid_exposure,
            0.0,
        ) @ pitch_overlap
        total_exposure += energy_overlap.T @ valid_exposure @ pitch_overlap
    observed_linear = np.divide(
        observed_sum,
        observed_weight,
        out=np.full(shape, np.nan),
        where=observed_weight > 0.0,
    )
    fitted_linear = np.divide(
        fitted_sum,
        fitted_weight,
        out=np.full(shape, np.nan),
        where=fitted_weight > 0.0,
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        observed_log = np.log(np.maximum(observed_linear, np.finfo(float).tiny))
        fitted_log = np.log(fitted_linear)
    return (
        np.asarray(energy, dtype=float),
        np.asarray(pitch, dtype=float),
        np.asarray(observed_log, dtype=float),
        np.asarray(fitted_log, dtype=float),
        total_exposure,
    )


def _bin_overlap_fraction(source_edges: FloatArray, target_edges: FloatArray) -> FloatArray:
    source = np.asarray(source_edges, dtype=float)
    target = np.asarray(target_edges, dtype=float)
    lower = np.maximum(source[:-1, None], target[None, :-1])
    upper = np.minimum(source[1:, None], target[None, 1:])
    overlap = np.maximum(0.0, upper - lower)
    return np.divide(
        overlap,
        (source[1:] - source[:-1])[:, None],
        out=np.zeros_like(overlap),
        where=(source[1:] > source[:-1])[:, None],
    )


def _bin_overlap_fraction_with_tails(
    source_edges: FloatArray,
    target_edges: FloatArray,
) -> FloatArray:
    source = np.asarray(source_edges, dtype=float)
    target = np.asarray(target_edges, dtype=float)
    fraction = _bin_overlap_fraction(source, target)
    width = source[1:] - source[:-1]
    lower_tail = np.maximum(
        0.0,
        np.minimum(source[1:], target[0]) - source[:-1],
    )
    upper_tail = np.maximum(
        0.0,
        source[1:] - np.maximum(source[:-1], target[-1]),
    )
    fraction[:, 0] += lower_tail / width
    fraction[:, -1] += upper_tail / width
    return np.asarray(fraction, dtype=float)


def _center_edges(
    centers: FloatArray,
    *,
    lower: float | None = None,
    upper: float | None = None,
) -> FloatArray:
    values = np.asarray(centers, dtype=float)
    if values.ndim != 1 or values.size < 2 or np.any(np.diff(values) <= 0.0):
        raise ValueError("centers must contain at least two strictly increasing values")
    edges = np.empty(values.size + 1, dtype=float)
    edges[1:-1] = 0.5 * (values[:-1] + values[1:])
    edges[0] = values[0] - 0.5 * (values[1] - values[0])
    edges[-1] = values[-1] + 0.5 * (values[-1] - values[-2])
    if lower is not None:
        edges[0] = lower
    if upper is not None:
        edges[-1] = upper
    return edges


def _normalized_flux_energy_bounds(flux: GlobalNormalizedFlux) -> tuple[float, float]:
    if flux.energy_edges_eV is not None:
        edges = np.asarray(flux.energy_edges_eV, dtype=float)
        return float(edges[0]), float(edges[-1])
    energy = np.asarray(flux.energy_eV, dtype=float)
    return float(energy[0]), float(energy[-1])


def _prepare_observation(
    name: str,
    observation: GlobalPitchCountObservation,
    settings: GlobalJointFitSettings,
) -> _PreparedGlobalObservation:
    energy = cast(FloatArray, observation.energy_eV)
    pitch = cast(FloatArray, observation.pitch_deg)
    counts = cast(FloatArray, observation.counts)
    exposure = cast(FloatArray, observation.exposure)
    energy_response, energy_weights = _bin_quadrature(
        cast(FloatArray, observation.energy_edges_eV),
        settings.energy_response_samples,
        logarithmic=False,
    )
    physical_energy_row = (
        cast(FloatArray, observation.energy_edges_eV)[:-1]
        > settings.effective_field.spacecraft_potential_eV
    )
    energy_range_row = (
        (energy >= settings.energy_bounds_eV[0])
        & (energy <= settings.energy_bounds_eV[1])
    )
    valid = (
        np.isfinite(counts)
        & np.isfinite(exposure)
        & (counts >= 0.0)
        & (exposure > 0.0)
        & physical_energy_row[:, None]
        & energy_range_row[:, None]
    )
    folded = np.minimum(pitch, 180.0 - pitch)
    affected = pitch < 90.0 if observation.affected_side == "low" else pitch > 90.0
    pitch_response, pitch_weights = _bin_quadrature(
        cast(FloatArray, observation.pitch_edges_deg),
        settings.pitch_response_samples,
        logarithmic=False,
    )
    return _PreparedGlobalObservation(
        name=name,
        sensor_group=observation.sensor_group or name,
        energy_eV=energy,
        pitch_deg=pitch,
        folded_pitch_deg=folded,
        energy_response_eV=energy_response,
        energy_response_weights=energy_weights,
        folded_pitch_response_deg=np.minimum(pitch_response, 180.0 - pitch_response),
        pitch_response_weights=pitch_weights,
        energy_edges_eV=cast(FloatArray, observation.energy_edges_eV),
        pitch_edges_deg=cast(FloatArray, observation.pitch_edges_deg),
        physical_energy_row=np.asarray(physical_energy_row, dtype=bool),
        affected=np.asarray(affected, dtype=bool),
        affected_side=observation.affected_side,
        counts=counts,
        exposure=exposure,
        detector_response_matrix=cast(FloatArray | None, observation.detector_response_matrix),
        known_background_counts=cast(FloatArray, observation.known_background_counts),
        live_time_capacity_seconds=cast(FloatArray, observation.live_time_capacity_seconds),
        dead_time_seconds=float(observation.dead_time_seconds),
        response_kind=str(
            (observation.metadata or {}).get(
                "response_kind",
                "user_matrix" if observation.detector_response_matrix is not None else "identity",
            )
        ),
        count_correction=str((observation.metadata or {}).get("count_correction", "none")),
        count_correction_order=str(
            (observation.metadata or {}).get(
                "count_correction_order",
                "trash_then_event",
            )
        ),
        invalid_exposure_count_cells=int(
            (observation.metadata or {}).get("invalid_exposure_count_cells", 0)
        ),
        valid=np.asarray(valid, dtype=bool),
        b_sc_nT=observation.b_sc_nT,
    )


def _validate_global_support(
    observations: tuple[_PreparedGlobalObservation, ...],
    settings: GlobalJointFitSettings,
) -> None:
    fit = settings.effective_field
    sensor_names, supported_bins, baseline_bins, _ = _sensor_window_support(
        observations, settings
    )
    for sensor_name, energy_bins in zip(sensor_names, supported_bins, strict=True):
        if len(energy_bins) < fit.min_energy_bins:
            raise ValueError(
                f"{sensor_name} has fewer than {fit.min_energy_bins} energy rows "
                f"with at least {fit.min_pitch_bins_per_energy} valid pitch cells "
                "across the integration window"
            )

    anchors = [bins for bins in baseline_bins if len(bins) >= fit.min_energy_bins]
    if not anchors:
        raise ValueError(
            "global observations need one sensor with affected/reference support "
            "across multiple energy rows to identify hemisphere baseline and sensor gain"
        )
    baseline_energy_bins = set().union(*baseline_bins)
    if len(baseline_energy_bins) < _baseline_knot_count(settings):
        raise ValueError(
            "hemisphere baseline has fewer independently supported energy rows than knots"
        )

    connected = {0}
    pending = [0]
    while pending:
        left_index = pending.pop()
        left = supported_bins[left_index]
        for right_index, right in enumerate(supported_bins):
            if right_index in connected:
                continue
            if len(left & right) >= fit.min_energy_bins:
                connected.add(right_index)
                pending.append(right_index)
    if len(connected) != len(sensor_names):
        disconnected = ", ".join(
            sensor_names[index]
            for index in range(len(sensor_names))
            if index not in connected
        )
        raise ValueError(
            "sensor energy support is not overlap-connected to the fixed-gain sensor: "
            f"{disconnected}"
        )


def _sensor_window_support(
    observations: tuple[_PreparedGlobalObservation, ...],
    settings: GlobalJointFitSettings,
) -> tuple[
    tuple[str, ...],
    tuple[set[int], ...],
    tuple[set[int], ...],
    FloatArray,
]:
    """Collect unique physical pitch support on one common energy grid."""

    sensor_names = tuple(dict.fromkeys(item.sensor_group for item in observations))
    sensor_lookup = {name: index for index, name in enumerate(sensor_names)}
    energy_edges = np.geomspace(
        settings.energy_bounds_eV[0],
        settings.energy_bounds_eV[1],
        settings.normalized_energy_bins + 1,
    )
    energy = np.sqrt(energy_edges[:-1] * energy_edges[1:])
    all_pitch: list[list[set[tuple[float, float]]]] = [
        [set() for _ in range(settings.normalized_energy_bins)]
        for _ in sensor_names
    ]
    affected_pitch = [
        [set() for _ in range(settings.normalized_energy_bins)]
        for _ in sensor_names
    ]
    reference_pitch = [
        [set() for _ in range(settings.normalized_energy_bins)]
        for _ in sensor_names
    ]
    for observation in observations:
        sensor_index = sensor_lookup[observation.sensor_group]
        energy_bins = np.digitize(observation.energy_eV, energy_edges) - 1
        for energy_index, target in enumerate(energy_bins):
            if target < 0 or target >= settings.normalized_energy_bins:
                continue
            valid_pitch = np.flatnonzero(observation.valid[energy_index])
            for pitch_index in valid_pitch:
                lower = float(observation.pitch_edges_deg[pitch_index])
                upper = float(observation.pitch_edges_deg[pitch_index + 1])
                if observation.affected_side == "high":
                    lower, upper = 180.0 - upper, 180.0 - lower
                pitch_bin = (round(lower, 8), round(upper, 8))
                all_pitch[sensor_index][target].add(pitch_bin)
                destination = (
                    affected_pitch if observation.affected[pitch_index] else reference_pitch
                )
                destination[sensor_index][target].add(pitch_bin)
    supported_bins = tuple(
        {
            index
            for index, pitch_bins in enumerate(sensor_pitch)
            if len(pitch_bins) >= settings.effective_field.min_pitch_bins_per_energy
        }
        for sensor_pitch in all_pitch
    )
    baseline_bins = tuple(
        {
            index
            for index in range(settings.normalized_energy_bins)
            if affected_pitch[sensor_index][index]
            and reference_pitch[sensor_index][index]
        }
        for sensor_index in range(len(sensor_names))
    )
    return sensor_names, supported_bins, baseline_bins, np.asarray(energy, dtype=float)


def _resolve_detector_response(
    provided: ArrayLike | None,
    shape: tuple[int, int],
) -> FloatArray | None:
    if provided is None:
        return None
    response = np.asarray(provided, dtype=float)
    cells = int(np.prod(shape))
    if response.shape == (*shape, *shape):
        response = response.reshape(cells, cells)
    if response.shape != (cells, cells):
        raise ValueError(
            "detector_response_matrix must have shape (cells, cells) or "
            "(energy, pitch, energy, pitch)"
        )
    if np.any(~np.isfinite(response)) or np.any(response < 0.0):
        raise ValueError("detector_response_matrix must be finite and non-negative")
    row_sum = np.sum(response, axis=1)
    if np.any(row_sum <= 0.0):
        raise ValueError("every detector_response_matrix row must have positive support")
    return np.asarray(response / row_sum[:, None], dtype=float)


def _reorder_detector_response(
    provided: ArrayLike | None,
    *,
    energy_order: NDArray[np.int64],
    pitch_bins: int,
) -> FloatArray | None:
    if provided is None:
        return None
    response = np.asarray(provided, dtype=float)
    energy_bins = energy_order.size
    cells = energy_bins * pitch_bins
    if response.shape == (energy_bins, pitch_bins, energy_bins, pitch_bins):
        response = response.reshape(cells, cells)
    if response.shape != (cells, cells):
        return np.asarray(response, dtype=float)
    cell_order = (energy_order[:, None] * pitch_bins + np.arange(pitch_bins)[None, :]).ravel()
    return np.asarray(response[np.ix_(cell_order, cell_order)], dtype=float)


def _resolve_cell_array(
    provided: ArrayLike | None,
    shape: tuple[int, int],
    *,
    default: float,
    name: str,
    allow_zero: bool,
) -> FloatArray:
    if provided is None:
        values = np.full(shape, default, dtype=float)
    else:
        values = np.broadcast_to(np.asarray(provided, dtype=float), shape).astype(float).copy()
    if np.any(~np.isfinite(values)):
        raise ValueError(f"{name} must be finite")
    if np.any(values < 0.0) or (not allow_zero and np.any(values <= 0.0)):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be {qualifier}")
    return values


def _resolve_energy_edges(
    centers: FloatArray,
    provided: ArrayLike | None,
) -> FloatArray:
    if provided is not None:
        edges = np.asarray(provided, dtype=float)
    elif centers.size == 1:
        edges = np.asarray([centers[0] / np.sqrt(2.0), centers[0] * np.sqrt(2.0)])
    else:
        if np.any(np.diff(centers) <= 0.0):
            raise ValueError("energy_eV must be strictly increasing to infer bin edges")
        middle = np.sqrt(centers[:-1] * centers[1:])
        edges = np.concatenate(
            ([centers[0] ** 2 / middle[0]], middle, [centers[-1] ** 2 / middle[-1]])
        )
    return _validate_edges(edges, centers, name="energy_edges_eV", lower=0.0, upper=None)


def _resolve_pitch_edges(
    centers: FloatArray,
    provided: ArrayLike | None,
) -> FloatArray:
    if provided is not None:
        edges = np.asarray(provided, dtype=float)
    elif centers.size == 1:
        half_width = min(float(centers[0]), 180.0 - float(centers[0]), 5.0)
        edges = np.asarray([centers[0] - half_width, centers[0] + half_width])
    else:
        if np.any(np.diff(centers) <= 0.0):
            raise ValueError("pitch_deg must be strictly increasing to infer bin edges")
        middle = 0.5 * (centers[:-1] + centers[1:])
        edges = np.concatenate(
            (
                [max(0.0, centers[0] - (middle[0] - centers[0]))],
                middle,
                [min(180.0, centers[-1] + (centers[-1] - middle[-1]))],
            )
        )
    return _validate_edges(edges, centers, name="pitch_edges_deg", lower=0.0, upper=180.0)


def _validate_edges(
    edges: FloatArray,
    centers: FloatArray,
    *,
    name: str,
    lower: float,
    upper: float | None,
) -> FloatArray:
    if edges.shape != (centers.size + 1,) or np.any(~np.isfinite(edges)):
        raise ValueError(f"{name} must contain one more finite value than its centers")
    if np.any(np.diff(edges) <= 0.0) or edges[0] < lower:
        raise ValueError(f"{name} must be strictly increasing and within its physical domain")
    if upper is not None and edges[-1] > upper:
        raise ValueError(f"{name} must be strictly increasing and within its physical domain")
    if np.any((centers <= edges[:-1]) | (centers >= edges[1:])):
        raise ValueError(f"{name} must bracket every center")
    return np.asarray(edges, dtype=float)


def _bin_quadrature(
    edges: FloatArray,
    count: int,
    *,
    logarithmic: bool,
) -> tuple[FloatArray, FloatArray]:
    nodes, weights = np.polynomial.legendre.leggauss(count)
    fractions = 0.5 * (nodes + 1.0)
    normalized_weights = np.asarray(0.5 * weights, dtype=float)
    lower = edges[:-1, None]
    upper = edges[1:, None]
    if logarithmic:
        samples = np.exp(
            np.log(lower) + fractions[None, :] * (np.log(upper) - np.log(lower))
        )
    else:
        samples = lower + fractions[None, :] * (upper - lower)
    return np.asarray(samples, dtype=float), normalized_weights


def _with_pitch_quadrature(
    observation: _PreparedGlobalObservation,
    count: int,
) -> _PreparedGlobalObservation:
    samples, weights = _bin_quadrature(
        observation.pitch_edges_deg,
        count,
        logarithmic=False,
    )
    return replace(
        observation,
        folded_pitch_response_deg=np.minimum(samples, 180.0 - samples),
        pitch_response_weights=weights,
    )


def _usable_seed(
    candidate: GlobalJointModelFit | None,
    fallback: GlobalJointModelFit,
) -> GlobalJointModelFit:
    if (
        candidate is not None
        and candidate.success
        and candidate._parameter_names
        and len(candidate._parameter_names) == len(candidate._parameter_values)
    ):
        return candidate
    return fallback


def _fit_edge_contrast(
    observations: tuple[_PreparedGlobalObservation, ...],
    model: Literal["mirror_only", "electrostatic"],
    settings: GlobalJointFitSettings,
) -> tuple[GlobalJointModelFit, float, float, bool]:
    requested = (
        settings.effective_field.contrast_model
        if settings.loss_cone_model == "flexible"
        else "constant"
    )
    if requested != "auto":
        if requested == "free":
            raise ValueError("global raw-count fitting does not support free contrast")
        contrast = cast(ResolvedContrastModel, requested)
        selected = _fit_transition_without_beam(
            observations,
            model,
            contrast,
            settings,
        )
        return (
            _fit_selected_beam(observations, selected, settings),
            float("nan"),
            float("nan"),
            False,
        )
    constant = _fit_transition_without_beam(observations, model, "constant", settings)
    constant_qualified = constant.success and _quality_reason(constant, settings) is None
    screen: GlobalJointModelFit | None = None
    screen_delta = float("nan")
    if settings.contrast_screening:
        screen_settings = replace(
            settings,
            effective_field=replace(
                settings.effective_field,
                optimizer_starts=1,
                max_iterations=min(
                    settings.effective_field.max_iterations,
                    settings.contrast_screen_max_iterations,
                ),
            ),
            pitch_response_samples=min(
                settings.pitch_response_samples,
                settings.contrast_screen_pitch_samples,
            ),
        )
        screen_observations = tuple(
            _with_pitch_quadrature(observation, screen_settings.pitch_response_samples)
            for observation in observations
        )
        screen = _fit_candidate(
            screen_observations,
            model,
            "band",
            screen_settings,
            beam_enabled=False,
            transition_model=constant.transition_model,
            seed_fit=constant,
            optimizer_starts=1,
            free_parameters=(
                "effective_field_nT",
                "delta_u_eff_eV",
                "contrast_floor",
                "contrast_excess",
                "contrast_center",
                "contrast_width",
            ),
        )
        screen_constant = _fit_candidate(
            screen_observations,
            model,
            "constant",
            screen_settings,
            beam_enabled=False,
            transition_model=constant.transition_model,
            seed_fit=constant,
            optimizer_starts=1,
            free_parameters=(),
        )
        screen_delta = _bic_improvement(screen_constant, screen)
        contrast_at_bound = _has_disallowed_contrast_bound(screen, settings)
        refine_threshold = (
            settings.effective_field.min_contrast_band_delta_bic
            - settings.contrast_screen_delta_bic_margin
        )
        if constant_qualified and (
            not screen.success
            or not np.isfinite(screen_delta)
            or screen_delta < refine_threshold
            or contrast_at_bound
        ):
            return (
                _fit_selected_beam(observations, constant, settings),
                float("nan"),
                screen_delta,
                False,
            )
    refine_optimizer_starts = (
        settings.contrast_refine_optimizer_starts
        if settings.contrast_screening
        else settings.effective_field.optimizer_starts
    )
    if not constant_qualified:
        refine_optimizer_starts = max(
            refine_optimizer_starts,
            settings.contrast_refine_optimizer_starts,
            settings.effective_field.optimizer_starts,
        )
    refine_settings = replace(
        settings,
        effective_field=replace(
            settings.effective_field,
            optimizer_starts=refine_optimizer_starts,
        ),
    )
    band = _fit_transition_without_beam(
        observations,
        model,
        "band",
        refine_settings,
        seed_fit=_usable_seed(screen, constant) if screen is not None else constant,
        hard_optimizer_starts=refine_optimizer_starts,
    )
    delta = _bic_improvement(constant, band)
    band_qualified = band.success and _quality_reason(band, settings) is None
    if (
        band_qualified
        and (
            not constant_qualified
            or delta >= settings.effective_field.min_contrast_band_delta_bic
        )
    ):
        selected = band
    else:
        selected = constant
    return (
        _fit_selected_beam(observations, selected, settings),
        delta,
        screen_delta,
        True,
    )


def _fit_candidate_with_beam(
    observations: tuple[_PreparedGlobalObservation, ...],
    model: CandidateModel,
    contrast_model: ResolvedContrastModel,
    settings: GlobalJointFitSettings,
) -> GlobalJointModelFit:
    selected = _fit_transition_without_beam(
        observations,
        model,
        contrast_model,
        settings,
    )
    return _fit_selected_beam(observations, selected, settings)


def _fit_transition_without_beam(
    observations: tuple[_PreparedGlobalObservation, ...],
    model: CandidateModel,
    contrast_model: ResolvedContrastModel,
    settings: GlobalJointFitSettings,
    *,
    seed_fit: GlobalJointModelFit | None = None,
    hard_optimizer_starts: int | None = None,
) -> GlobalJointModelFit:
    if model == "no_edge":
        return _fit_candidate(
            observations,
            model,
            contrast_model,
            settings,
            beam_enabled=False,
            transition_model="none",
        )
    if settings.edge_transition != "auto":
        return _fit_candidate(
            observations,
            model,
            contrast_model,
            settings,
            beam_enabled=False,
            transition_model=cast(ResolvedEdgeTransition, settings.edge_transition),
            seed_fit=seed_fit,
            optimizer_starts=hard_optimizer_starts,
        )

    hard = _fit_candidate(
        observations,
        model,
        contrast_model,
        settings,
        beam_enabled=False,
        transition_model="hard",
        seed_fit=seed_fit,
        optimizer_starts=hard_optimizer_starts,
    )
    screen: GlobalJointModelFit | None = None
    if settings.smooth_screening:
        screen_settings = replace(
            settings,
            effective_field=replace(
                settings.effective_field,
                optimizer_starts=1,
                max_iterations=min(
                    settings.effective_field.max_iterations,
                    settings.smooth_screen_max_iterations,
                ),
            ),
            pitch_response_samples=min(
                settings.pitch_response_samples,
                settings.smooth_screen_pitch_samples,
            ),
        )
        screen_observations = tuple(
            _with_pitch_quadrature(observation, screen_settings.pitch_response_samples)
            for observation in observations
        )
        screen = _fit_candidate(
            screen_observations,
            model,
            contrast_model,
            screen_settings,
            beam_enabled=False,
            transition_model="smooth",
            seed_fit=hard,
            optimizer_starts=1,
            free_parameters=("effective_field_nT", "delta_u_eff_eV", "sigma_ln_b"),
        )
        screen_delta = _bic_improvement(hard, screen)
        hard_qualified = hard.success and _quality_reason(hard, settings) is None
        should_refine = (
            not hard_qualified
            or (
                screen.success
                and np.isfinite(screen_delta)
                and screen_delta >= settings.smooth_screen_delta_bic
                and "sigma_ln_b" not in screen.at_bounds
            )
        )
        if not should_refine:
            return replace(
                hard,
                smooth_transition_screen_delta_bic=screen_delta,
                smooth_transition_refined=False,
            )

    smooth = _fit_candidate(
        observations,
        model,
        contrast_model,
        settings,
        beam_enabled=False,
        transition_model="smooth",
        seed_fit=_usable_seed(screen, hard) if screen is not None else hard,
        optimizer_starts=(
            settings.smooth_refine_optimizer_starts
            if settings.smooth_screening
            else None
        ),
    )
    candidates = [hard, smooth]
    successful = [fit for fit in candidates if fit.success and fit.bic is not None]
    qualified = [fit for fit in successful if _quality_reason(fit, settings) is None]
    selectable = qualified or successful
    selected = (
        min(selectable, key=lambda fit: cast(float, fit.bic))
        if selectable
        else candidates[0]
    )
    return replace(
        selected,
        smooth_transition_delta_bic=_bic_improvement(hard, smooth),
        smooth_transition_screen_delta_bic=(
            float("nan") if screen is None else _bic_improvement(hard, screen)
        ),
        smooth_transition_refined=True,
    )


def _fit_selected_beam(
    observations: tuple[_PreparedGlobalObservation, ...],
    selected: GlobalJointModelFit,
    settings: GlobalJointFitSettings,
) -> GlobalJointModelFit:
    if settings.secondary_beam == "off":
        return selected
    screen: GlobalJointModelFit | None = None
    screen_delta = float("nan")
    if settings.beam_screening:
        screen_settings = replace(
            settings,
            effective_field=replace(
                settings.effective_field,
                optimizer_starts=settings.beam_screen_optimizer_starts,
                max_iterations=min(
                    settings.effective_field.max_iterations,
                    settings.beam_screen_max_iterations,
                ),
            ),
            pitch_response_samples=min(
                settings.pitch_response_samples,
                settings.beam_screen_pitch_samples,
            ),
        )
        screen_observations = tuple(
            _with_pitch_quadrature(observation, screen_settings.pitch_response_samples)
            for observation in observations
        )
        screen = _fit_candidate(
            screen_observations,
            selected.model,
            selected.contrast_model,
            screen_settings,
            beam_enabled=True,
            transition_model=selected.transition_model,
            seed_fit=selected,
            optimizer_starts=settings.beam_screen_optimizer_starts,
            free_parameters=(
                "beam_amplitude",
                "beam_center_eV",
                "beam_sigma_ln_energy",
                "beam_sigma_pitch_deg",
            ),
        )
        screen_selected = _fit_candidate(
            screen_observations,
            selected.model,
            selected.contrast_model,
            screen_settings,
            beam_enabled=False,
            transition_model=selected.transition_model,
            seed_fit=selected,
            optimizer_starts=1,
            free_parameters=(),
        )
        screen_delta = _bic_improvement(screen_selected, screen)
        beam_at_bound = any(name.startswith("beam_") for name in screen.at_bounds)
        refine_threshold = (
            settings.min_secondary_beam_delta_bic
            - settings.beam_screen_delta_bic_margin
        )
        if settings.secondary_beam == "auto" and (
            selected.success
            and (selected.model == "no_edge" or _quality_reason(selected, settings) is None)
            and (
                not screen.success
                or not np.isfinite(screen_delta)
                or screen_delta < refine_threshold
                or beam_at_bound
            )
        ):
            return replace(
                selected,
                secondary_beam_screen_delta_bic=screen_delta,
                secondary_beam_refined=False,
            )
    with_beam = _fit_candidate(
        observations,
        selected.model,
        selected.contrast_model,
        settings,
        beam_enabled=True,
        transition_model=selected.transition_model,
        seed_fit=_usable_seed(screen, selected) if screen is not None else selected,
        optimizer_starts=(
            settings.beam_refine_optimizer_starts
            if settings.beam_screening
            else None
        ),
    )
    delta = _bic_improvement(selected, with_beam)
    selected = _with_beam_delta(selected, delta)
    with_beam = replace(
        _with_beam_delta(with_beam, delta),
        smooth_transition_delta_bic=selected.smooth_transition_delta_bic,
        smooth_transition_screen_delta_bic=(
            selected.smooth_transition_screen_delta_bic
        ),
        smooth_transition_refined=selected.smooth_transition_refined,
        secondary_beam_screen_delta_bic=screen_delta,
        secondary_beam_refined=True,
    )
    if settings.secondary_beam == "on":
        return with_beam
    beam_at_bound = any(name.startswith("beam_") for name in with_beam.at_bounds)
    beam_fit_qualified = (
        selected.model == "no_edge" or _quality_reason(with_beam, settings) is None
    )
    if (
        with_beam.success
        and beam_fit_qualified
        and delta >= settings.min_secondary_beam_delta_bic
        and not beam_at_bound
    ):
        return with_beam
    return replace(
        selected,
        secondary_beam_screen_delta_bic=screen_delta,
        secondary_beam_refined=True,
    )


def _fit_candidate(
    observations: tuple[_PreparedGlobalObservation, ...],
    model: CandidateModel,
    contrast_model: ResolvedContrastModel,
    settings: GlobalJointFitSettings,
    *,
    beam_enabled: bool,
    transition_model: ResolvedEdgeTransition,
    seed_fit: GlobalJointModelFit | None = None,
    optimizer_starts: int | None = None,
    free_parameters: tuple[str, ...] | None = None,
) -> GlobalJointModelFit:
    from scipy.optimize import OptimizeResult, minimize  # type: ignore[import-untyped]

    problem = _build_problem(
        observations,
        model,
        contrast_model,
        settings,
        beam_enabled=beam_enabled,
        transition_model=transition_model,
    )
    native_problem = _native_hard_problem(problem)
    free_indices: NDArray[np.int_] | None = None
    seed_vector: FloatArray | None = None
    if free_parameters is not None:
        free_indices = np.asarray(
            [index for index, name in enumerate(problem.names) if name in free_parameters],
            dtype=int,
        )
        if free_indices.size == 0 and free_parameters:
            raise ValueError("free_parameters did not match any candidate parameters")
        seed_vector = _seed_vector(problem, seed_fit)
    best = None
    best_nonconverged = None
    starts = (
        (seed_vector,)
        if free_indices is not None and free_indices.size == 0
        else _starts(problem, seed_fit=seed_fit, count=optimizer_starts)
    )
    for start in starts:
        assert start is not None
        if free_indices is None:
            if native_problem is None:
                result = minimize(
                    _objective,
                    start,
                    args=(problem,),
                    method="L-BFGS-B",
                    bounds=problem.bounds,
                    options={
                        "maxiter": settings.effective_field.max_iterations,
                        "ftol": 1.0e-9,
                    },
                )
            else:
                result = minimize(
                    native_problem.value_and_gradient,
                    start,
                    jac=True,
                    method="L-BFGS-B",
                    bounds=problem.bounds,
                    options={
                        "maxiter": settings.effective_field.max_iterations,
                        "ftol": 1.0e-9,
                    },
                )
        elif free_indices.size:
            assert seed_vector is not None
            partial_start = seed_vector.copy()
            partial_start[free_indices] = start[free_indices]
            partial_objective = (
                _partial_objective
                if native_problem is None
                else _native_partial_value_and_gradient
            )
            objective_owner: _Problem | _NativeObjective = (
                problem if native_problem is None else native_problem
            )
            result = minimize(
                partial_objective,
                partial_start[free_indices],
                args=(objective_owner, partial_start, free_indices),
                jac=(native_problem is not None),
                method="L-BFGS-B",
                bounds=[problem.bounds[index] for index in free_indices],
                options={
                    "maxiter": settings.effective_field.max_iterations,
                    "ftol": 1.0e-9,
                },
            )
            full_vector = partial_start.copy()
            full_vector[free_indices] = result.x
            result.x = full_vector
        else:
            result = OptimizeResult(
                x=start,
                fun=(
                    _objective(start, problem)
                    if native_problem is None
                    else native_problem.objective(start)
                ),
                success=True,
                status=0,
                message="fixed-parameter score",
            )
        if not np.isfinite(result.fun):
            continue
        if result.success:
            if best is None or float(result.fun) < float(best.fun):
                best = result
        elif best_nonconverged is None or float(result.fun) < float(best_nonconverged.fun):
            best_nonconverged = result
    if best is None:
        if best_nonconverged is None:
            return _empty_fit(
                model,
                contrast_model,
                transition_model,
                "optimizer_failed",
                loss_cone_model=settings.loss_cone_model,
            )
        return _empty_fit(
            model,
            contrast_model,
            transition_model,
            f"optimizer_nonconvergence_status_{best_nonconverged.status}",
            loss_cone_model=settings.loss_cone_model,
        )
    if (
        settings.boundary_grid_refinement
        and settings.loss_cone_model != "flexible"
        and model != "no_edge"
        and transition_model == "hard"
        and not beam_enabled
        and free_parameters is None
    ):
        # Hard boundaries have flat local regions. Revisit physical coordinates
        # with fitted nuisance parameters before accepting a local optimum.
        for _ in range(2):
            grid_start = _boundary_grid_start(np.asarray(best.x), problem, native_problem)
            if np.array_equal(grid_start, best.x):
                break
            refined = minimize(
                _objective if native_problem is None else native_problem.value_and_gradient,
                grid_start,
                args=(problem,) if native_problem is None else (),
                jac=native_problem is not None,
                method="L-BFGS-B",
                bounds=problem.bounds,
                options={"maxiter": settings.effective_field.max_iterations, "ftol": 1.0e-9},
            )
            if not refined.success or not np.isfinite(refined.fun) or refined.fun >= best.fun:
                break
            best = refined
    vector = np.asarray(best.x, dtype=float)
    log_likelihood = _data_log_likelihood(vector, problem)
    effective_field, delta_u, sigma = _physical(vector, problem.layout)
    representative_b = float(np.median([item.b_sc_nT for item in observations]))
    mirror_ratio = (
        effective_field / representative_b if effective_field is not None else None
    )
    beam = _beam_parameters(vector, problem.layout)
    at_bounds = _at_bounds(vector, problem)
    sensors = _sensor_fits(vector, problem)
    global_fov = _global_full_fov(vector, problem)
    normalized = _fold_global_fov(global_fov, settings)
    baseline_values = vector[problem.layout.hemisphere_baseline]
    bracket_fraction, strict_bracket_fraction = _global_boundary_support(
        observations,
        effective_field,
        delta_u,
        spacecraft_potential_eV=settings.effective_field.spacecraft_potential_eV,
        min_transition_energy_bins=settings.effective_field.min_energy_bins,
        normalized_energy_bins=settings.normalized_energy_bins,
    )
    n_cells = sum(sensor.n_cells for sensor in sensors)
    n_parameters = sum(lower < upper for lower, upper in problem.bounds)
    success = bool(
        np.isfinite(log_likelihood)
        and (
            model == "no_edge"
            or (
                effective_field is not None
                and np.isfinite(effective_field)
                and effective_field > 0.0
            )
        )
    )
    return GlobalJointModelFit(
        model=model,
        contrast_model=contrast_model,
        success=success,
        reason="ok" if success else "non_physical_or_nonfinite_fit",
        mirror_ratio=mirror_ratio,
        delta_u_eff_eV=delta_u,
        sigma_ln_b=sigma,
        secondary_beam_enabled=problem.layout.beam is not None,
        beam_amplitude=beam[0],
        beam_center_eV=beam[1],
        beam_sigma_ln_energy=beam[2],
        beam_sigma_pitch_deg=beam[3],
        secondary_beam_delta_bic=float("nan"),
        log_likelihood=log_likelihood,
        bic=float(n_parameters * np.log(max(n_cells, 1)) - 2.0 * log_likelihood),
        n_parameters=n_parameters,
        n_cells=n_cells,
        at_bounds=at_bounds,
        sensors=sensors,
        normalized_flux=normalized,
        global_fov=global_fov,
        hemisphere_baseline_energy_eV=tuple(
            float(value) for value in np.exp(problem.log_baseline_knots)
        ),
        hemisphere_baseline_log_ratio=tuple(float(value) for value in baseline_values),
        loss_cone_model=settings.loss_cone_model,
        boundary_bracket_fraction=bracket_fraction,
        strict_boundary_bracket_fraction=strict_bracket_fraction,
        transition_model=transition_model,
        _parameter_names=problem.names,
        _parameter_values=tuple(float(value) for value in vector),
    )


def _boundary_grid_start(
    vector: FloatArray,
    problem: _Problem,
    native: _NativeObjective | None,
) -> FloatArray:
    best = vector.copy()
    score = _objective(best, problem) if native is None else native.objective(best)
    physical = problem.layout.physical
    fields = np.unique(
        np.append(np.linspace(*problem.bounds[physical.start], 25), vector[physical.start])
    )
    deltas = (
        np.unique(
            np.append(np.linspace(*problem.bounds[physical.start + 1], 31),
                      vector[physical.start + 1])
        )
        if problem.layout.model == "electrostatic" else np.array([0.0])
    )
    candidate = vector.copy()
    for field_value in fields:
        candidate[physical.start] = field_value
        for delta in deltas:
            if problem.layout.model == "electrostatic":
                candidate[physical.start + 1] = delta
            value = (
                _objective(candidate, problem) if native is None else native.objective(candidate)
            )
            if value < score:
                score, best = value, candidate.copy()
    return best


def _baseline_knot_count(settings: GlobalJointFitSettings) -> int:
    return settings.hemisphere_baseline_knots if settings.loss_cone_model == "flexible" else 1


def _build_problem(
    observations: tuple[_PreparedGlobalObservation, ...],
    model: CandidateModel,
    contrast_model: ResolvedContrastModel,
    settings: GlobalJointFitSettings,
    *,
    beam_enabled: bool,
    transition_model: ResolvedEdgeTransition = "none",
) -> _Problem:
    if (
        settings.loss_cone_model != "flexible"
        and model != "no_edge"
        and contrast_model != "constant"
    ):
        raise ValueError("boundary-centered models require constant contrast")
    sensor_names = tuple(dict.fromkeys(item.sensor_group for item in observations))
    sensor_lookup = {name: index for index, name in enumerate(sensor_names)}
    sensor_indices = tuple(sensor_lookup[item.sensor_group] for item in observations)
    sensor_count = len(sensor_names)
    all_energy = np.concatenate(
        [
            item.energy_eV[
                (item.energy_eV >= settings.energy_bounds_eV[0])
                & (item.energy_eV <= settings.energy_bounds_eV[1])
            ]
            for item in observations
        ]
    )
    log_knots = np.linspace(
        float(np.log(np.min(all_energy))),
        float(np.log(np.max(all_energy))),
        settings.spectrum_knots,
    )
    _, _, baseline_bins, support_energy = _sensor_window_support(
        observations, settings
    )
    baseline_indices = sorted(set().union(*baseline_bins))
    baseline_energy = support_energy[baseline_indices]
    if baseline_energy.size < 2:
        baseline_energy = np.unique(all_energy)
    if baseline_energy.size < 2:
        raise ValueError("global fitting requires at least two distinct energy values")
    log_baseline_knots = np.linspace(
        float(np.log(np.min(baseline_energy))),
        float(np.log(np.max(baseline_energy))),
        _baseline_knot_count(settings),
    )
    index = 0
    physical_size = 0
    if model != "no_edge":
        physical_size = 1 + int(model == "electrostatic") + int(transition_model == "smooth")
    physical = slice(index, index + physical_size)
    index += physical_size
    spectrum = slice(index, index + settings.spectrum_knots)
    index += settings.spectrum_knots
    hemisphere_baseline = slice(index, index + _baseline_knot_count(settings))
    index = hemisphere_baseline.stop
    contrast_size = 0 if model == "no_edge" else (4 if contrast_model == "band" else 1)
    contrast = None if contrast_size == 0 else slice(index, index + contrast_size)
    index += contrast_size
    beam = slice(index, index + 4) if beam_enabled else None
    if beam is not None:
        index = beam.stop
    gains = slice(index, index + sensor_count - 1)
    index = gains.stop
    background_size = sensor_count if settings.background_model == "sensor_constant" else 0
    backgrounds = slice(index, index + background_size)
    index = backgrounds.stop
    dispersions = slice(index, index + sensor_count)
    index = dispersions.stop
    layout = _Layout(
        model=model,
        contrast_model=contrast_model,
        transition_model=transition_model,
        physical=physical,
        spectrum=spectrum,
        hemisphere_baseline=hemisphere_baseline,
        contrast=contrast,
        beam=beam,
        gains=gains,
        backgrounds=backgrounds,
        dispersions=dispersions,
        size=index,
    )
    initial = np.zeros(index, dtype=float)
    bounds: list[tuple[float, float]] = [(-20.0, 20.0)] * index
    fit = settings.effective_field
    if model != "no_edge":
        b_sc = np.asarray([item.b_sc_nT for item in observations], dtype=float)
        effective_field_bounds = (
            float(np.max(b_sc) * fit.mirror_ratio_bounds[0]),
            float(np.min(b_sc) * fit.mirror_ratio_bounds[1]),
        )
        if effective_field_bounds[0] >= effective_field_bounds[1]:
            raise ValueError(
                "spacecraft-field variation is incompatible with mirror-ratio bounds"
            )
        bounds[physical.start] = tuple(log(value) for value in effective_field_bounds)
        initial[physical.start] = log(
            float(np.clip(3.0 * np.median(b_sc), *effective_field_bounds))
        )
        if model == "electrostatic":
            initial[physical.start + 1] = 0.0
            bounds[physical.start + 1] = fit.delta_u_bounds_eV
        if transition_model == "smooth":
            initial[physical.stop - 1] = log(0.25)
            bounds[physical.stop - 1] = tuple(log(value) for value in fit.sigma_ln_b_bounds)
    initial[spectrum] = _initial_spectrum(observations, log_knots)
    for spectrum_index in range(spectrum.start, spectrum.stop):
        bounds[spectrum_index] = (-100.0, 100.0)
    for baseline_index in range(hemisphere_baseline.start, hemisphere_baseline.stop):
        bounds[baseline_index] = fit.baseline_log_ratio_bounds
    if contrast is not None:
        if contrast_model == "constant":
            initial[contrast] = 1.0
            bounds[contrast.start] = fit.amplitude_log_ratio_bounds
        else:
            initial[contrast] = (0.2, 1.5, float(np.median(log_knots)), log(0.7))
            bounds[contrast.start] = fit.amplitude_log_ratio_bounds
            bounds[contrast.start + 1] = fit.amplitude_log_ratio_bounds
            bounds[contrast.start + 2] = (float(log_knots[0]), float(log_knots[-1]))
            bounds[contrast.start + 3] = tuple(
                log(value) for value in fit.contrast_band_width_bounds_ln
            )
    if beam is not None:
        median_energy = float(np.exp(np.median(log_knots)))
        initial[beam] = (
            log(0.2),
            log(np.clip(median_energy, *settings.beam_center_bounds_eV)),
            log(0.3),
            log(15.0),
        )
        bounds[beam.start] = tuple(log(value) for value in settings.beam_amplitude_bounds)
        bounds[beam.start + 1] = tuple(log(value) for value in settings.beam_center_bounds_eV)
        bounds[beam.start + 2] = tuple(log(value) for value in settings.beam_sigma_ln_energy_bounds)
        bounds[beam.start + 3] = tuple(log(value) for value in settings.beam_sigma_pitch_bounds_deg)
    for gain_index in range(gains.start, gains.stop):
        bounds[gain_index] = settings.sensor_gain_log_bounds
    if backgrounds.stop > backgrounds.start:
        lower, upper = (log(value) for value in settings.background_rate_bounds_hz)
        initial[backgrounds] = lower + 0.15 * (upper - lower)
        for background_index in range(backgrounds.start, backgrounds.stop):
            bounds[background_index] = (lower, upper)
    initial[dispersions] = log(100.0)
    for dispersion_index in range(dispersions.start, dispersions.stop):
        bounds[dispersion_index] = tuple(log(value) for value in fit.concentration_bounds)
    if settings.loss_cone_model == "fixed" and model != "no_edge":
        # Equal bounds keep the native layout while removing fixed levels from BIC.
        initial[hemisphere_baseline] = 0.0
        bounds[hemisphere_baseline.start] = (0.0, 0.0)
        assert contrast is not None
        initial[contrast] = log(10.0)
        bounds[contrast.start] = (log(10.0), log(10.0))
    names = _parameter_names(layout, sensor_names, settings.spectrum_knots)
    return _Problem(
        observations=observations,
        sensor_names=sensor_names,
        sensor_indices=sensor_indices,
        layout=layout,
        log_energy_knots=log_knots,
        log_baseline_knots=log_baseline_knots,
        initial=initial,
        bounds=tuple(bounds),
        names=names,
        settings=settings,
    )


def _initial_spectrum(
    observations: tuple[_PreparedGlobalObservation, ...],
    log_knots: FloatArray,
) -> FloatArray:
    energies: list[float] = []
    rates: list[float] = []
    for observation in observations:
        with np.errstate(divide="ignore", invalid="ignore"):
            log_rate = np.log((observation.counts + 0.5) / observation.exposure)
        for index, energy in enumerate(observation.energy_eV):
            valid = observation.valid[index] & np.isfinite(log_rate[index])
            if np.any(valid):
                energies.append(log(float(energy)))
                rates.append(float(np.median(log_rate[index, valid])))
    order = np.argsort(energies)
    return np.interp(log_knots, np.asarray(energies)[order], np.asarray(rates)[order])


def _starts(
    problem: _Problem,
    *,
    seed_fit: GlobalJointModelFit | None = None,
    count: int | None = None,
) -> list[FloatArray]:
    requested = problem.settings.effective_field.optimizer_starts if count is None else count
    seed = _seed_vector(problem, seed_fit)
    starts = [seed]
    if problem.layout.model == "no_edge" and problem.layout.beam is None:
        return starts
    canonical = problem.initial.copy()
    if (
        seed_fit is not None
        and len(starts) < requested
        and not np.allclose(seed, canonical, rtol=0.0, atol=1.0e-12)
    ):
        starts.append(canonical.copy())
    fit = problem.settings.effective_field
    ratios = (1.3, 10.0, 30.0)
    if problem.layout.model == "electrostatic" and fit.mirror_ratio_bounds[0] < 1.0:
        ratios = (0.8, 10.0, 30.0)
    deltas = (-100.0, 150.0, 0.0)
    sigmas = (0.12, 0.3, 0.7)
    beam_amplitudes = (0.1, 0.5, 2.0)
    beam_centers_eV = (40.0, 150.0, 800.0)
    beam_sigma_energies = (0.15, 0.4, 0.8)
    beam_sigma_pitches_deg = (6.0, 15.0, 35.0)
    representative_b = float(np.median([item.b_sc_nT for item in problem.observations]))
    variant_offset = len(starts)
    for index in range(variant_offset, requested):
        start_index = (index - variant_offset) % len(ratios)
        candidate = canonical.copy()
        physical = problem.layout.physical
        if problem.layout.model != "no_edge":
            lower, upper = problem.bounds[physical.start]
            candidate[physical.start] = np.clip(
                log(representative_b * ratios[start_index]), lower, upper
            )
            if problem.layout.transition_model == "smooth":
                candidate[physical.stop - 1] = log(
                    np.clip(sigmas[start_index], *fit.sigma_ln_b_bounds)
                )
            if problem.layout.model == "electrostatic":
                candidate[physical.start + 1] = np.clip(
                    deltas[start_index], *fit.delta_u_bounds_eV
                )
        if problem.layout.beam is not None:
            beam = problem.layout.beam
            candidate[beam] = np.log(
                (
                    np.clip(
                        beam_amplitudes[start_index],
                        *problem.settings.beam_amplitude_bounds,
                    ),
                    np.clip(
                        beam_centers_eV[start_index],
                        *problem.settings.beam_center_bounds_eV,
                    ),
                    np.clip(
                        beam_sigma_energies[start_index],
                        *problem.settings.beam_sigma_ln_energy_bounds,
                    ),
                    np.clip(
                        beam_sigma_pitches_deg[start_index],
                        *problem.settings.beam_sigma_pitch_bounds_deg,
                    ),
                )
            )
        starts.append(candidate)
    return starts


def _seed_vector(
    problem: _Problem,
    fit: GlobalJointModelFit | None,
) -> FloatArray:
    vector = problem.initial.copy()
    if fit is None or not fit._parameter_names:
        return vector
    previous = dict(zip(fit._parameter_names, fit._parameter_values, strict=True))
    for index, (name, bounds) in enumerate(zip(problem.names, problem.bounds, strict=True)):
        if name in previous:
            vector[index] = np.clip(previous[name], bounds[0], bounds[1])
    return vector


def _objective(vector: FloatArray, problem: _Problem) -> float:
    likelihood = _data_log_likelihood(vector, problem)
    if not np.isfinite(likelihood):
        return 1.0e30
    spectrum = vector[problem.layout.spectrum]
    penalty = (
        0.5 * problem.settings.spectrum_smoothness * float(np.sum(np.diff(spectrum, n=2) ** 2))
    )
    return float(-likelihood + penalty)


def _partial_objective(
    values: FloatArray,
    problem: _Problem,
    base: FloatArray,
    indices: NDArray[np.int_],
) -> float:
    vector = base.copy()
    vector[indices] = values
    return _objective(vector, problem)


def _native_partial_value_and_gradient(
    values: FloatArray,
    problem: _NativeObjective,
    base: FloatArray,
    indices: NDArray[np.int_],
) -> tuple[float, FloatArray]:
    vector = base.copy()
    vector[indices] = values
    indexed = getattr(problem, "value_and_gradient_indices", None)
    if indexed is not None:
        value, gradient = indexed(vector, indices.tolist())
        return value, np.asarray(gradient, dtype=float)
    value, gradient = problem.value_and_gradient(vector)
    return value, np.asarray(gradient[indices], dtype=float)


def _data_log_likelihood(vector: FloatArray, problem: _Problem) -> float:
    from scipy.special import gammaln  # type: ignore[import-untyped]

    total = 0.0
    for observation_index, observation in enumerate(problem.observations):
        sensor_index = problem.sensor_indices[observation_index]
        log_mean, _log_normalized, _log_incident = _predicted_surfaces(
            vector,
            problem,
            sensor_index,
            observation,
        )
        valid = observation.valid & np.isfinite(log_mean)
        if not np.any(valid):
            return float("-inf")
        counts = observation.counts[valid]
        log_mu = np.clip(log_mean[valid], -30.0, 30.0)
        mu = np.exp(log_mu)
        dispersion = exp(float(vector[problem.layout.dispersions.start + sensor_index]))
        values = (
            gammaln(counts + dispersion)
            - gammaln(dispersion)
            - gammaln(counts + 1.0)
            + dispersion * (log(dispersion) - np.log(dispersion + mu))
            + counts * (log_mu - np.log(dispersion + mu))
        )
        if not np.all(np.isfinite(values)):
            return float("-inf")
        total += float(np.sum(values))
    return total


def _transition_probability(
    pitch_deg: FloatArray,
    energy_eV: FloatArray,
    mirror_ratio: float,
    *,
    sigma_ln_b: float | None,
    transition_model: ResolvedEdgeTransition,
    delta_u_eff_eV: float,
    spacecraft_potential_eV: float,
) -> FloatArray:
    if transition_model == "smooth":
        if sigma_ln_b is None:
            raise ValueError("smooth transition requires sigma_ln_b")
        return mirror_transmission_probability(
            pitch_deg,
            energy_eV,
            mirror_ratio,
            sigma_ln_b,
            delta_u_eff_eV=delta_u_eff_eV,
            spacecraft_potential_eV=spacecraft_potential_eV,
        )
    if transition_model != "hard":
        raise ValueError("edge fit requires a hard or smooth transition")
    boundary = mirror_boundary_sin2(
        energy_eV,
        mirror_ratio,
        delta_u_eff_eV,
        spacecraft_potential_eV=spacecraft_potential_eV,
    )
    sin2_pitch = np.sin(np.deg2rad(pitch_deg)) ** 2
    probability = sin2_pitch[None, :] >= boundary[:, None]
    return np.asarray(
        np.where(np.isfinite(boundary)[:, None], probability, np.nan),
        dtype=float,
    )


def _hard_pitch_bin_transmission(
    energy_eV: FloatArray,
    pitch_edges_deg: FloatArray,
    mirror_ratio: float,
    *,
    delta_u_eff_eV: float,
    spacecraft_potential_eV: float,
) -> FloatArray:
    boundary = mirror_boundary_sin2(
        energy_eV,
        mirror_ratio,
        delta_u_eff_eV,
        spacecraft_potential_eV=spacecraft_potential_eV,
    )
    boundary_pitch = np.full(boundary.shape, np.nan, dtype=float)
    boundary_pitch[boundary <= 0.0] = 0.0
    boundary_pitch[boundary >= 1.0] = 90.0
    interior = np.isfinite(boundary) & (boundary > 0.0) & (boundary < 1.0)
    boundary_pitch[interior] = np.degrees(np.arcsin(np.sqrt(boundary[interior])))
    lower = pitch_edges_deg[:-1][None, :]
    upper = pitch_edges_deg[1:][None, :]
    transmitted_lower = np.maximum(lower, boundary_pitch[:, None])
    transmitted_upper = np.minimum(upper, 180.0 - boundary_pitch[:, None])
    overlap = np.maximum(0.0, transmitted_upper - transmitted_lower)
    fraction = overlap / (upper - lower)
    fraction[~np.isfinite(boundary), :] = np.nan
    return np.asarray(fraction, dtype=float)


def _predicted_surfaces(
    vector: FloatArray,
    problem: _Problem,
    sensor_index: int,
    observation: _PreparedGlobalObservation,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    gain = (
        0.0 if sensor_index == 0 else float(vector[problem.layout.gains.start + sensor_index - 1])
    )
    effective_field, delta_u, sigma = _physical(vector, problem.layout)
    mirror_ratio = (
        effective_field / observation.b_sc_nT
        if effective_field is not None
        else None
    )
    rate_sum = np.zeros(observation.counts.shape, dtype=float)
    incident_sum = np.zeros(observation.energy_eV.shape, dtype=float)
    pitch_samples = observation.folded_pitch_response_deg
    pitch_weights = observation.pitch_response_weights
    flattened_pitch = pitch_samples.reshape(-1)
    for sample_index, energy_weight in enumerate(observation.energy_response_weights):
        energy = observation.energy_response_eV[:, sample_index]
        incident_log = np.interp(
            np.log(energy),
            problem.log_energy_knots,
            vector[problem.layout.spectrum],
        )
        incident_rate = np.exp(np.clip(incident_log, -100.0, 100.0))
        incident_sum += energy_weight * incident_rate
        baseline_log = _hemisphere_baseline_log_ratio(vector, problem, energy)
        if problem.layout.beam is None:
            beam_ratio: FloatArray | float = 0.0
        else:
            beam_ratio = np.sum(
                _secondary_beam_ratio(
                    vector,
                    problem.layout,
                    energy,
                    pitch_samples,
                    observation.affected,
                )
                * pitch_weights[None, None, :],
                axis=2,
            )
        if mirror_ratio is None:
            normalized_rate = np.ones(observation.counts.shape, dtype=float)
            normalized_rate[:, observation.affected] = np.exp(baseline_log[:, None])
            normalized_rate += beam_ratio
            rate_sum += energy_weight * incident_rate[:, None] * normalized_rate
            continue
        if mirror_ratio is not None and problem.layout.transition_model == "hard":
            transmitted = _hard_pitch_bin_transmission(
                energy,
                observation.pitch_edges_deg,
                mirror_ratio,
                delta_u_eff_eV=delta_u or 0.0,
                spacecraft_potential_eV=(
                    problem.settings.effective_field.spacecraft_potential_eV
                ),
            )
            amplitude = _contrast(vector, problem, energy)[:, None]
            loss_factor = transmitted + (1.0 - transmitted) * np.exp(-amplitude)
            normalized_rate = np.ones(observation.counts.shape, dtype=float)
            normalized_rate[:, observation.affected] = (
                np.exp(baseline_log[:, None])
                * loss_factor[:, observation.affected]
            )
            normalized_rate += beam_ratio
            rate_sum += energy_weight * incident_rate[:, None] * normalized_rate
            continue
        log_normalized_samples = np.zeros(
            (energy.size, pitch_samples.shape[0], pitch_samples.shape[1]),
            dtype=float,
        )
        log_normalized_samples[:, observation.affected, :] = baseline_log[:, None, None]
        if mirror_ratio is not None:
            transition = _transition_probability(
                flattened_pitch,
                energy,
                mirror_ratio,
                sigma_ln_b=sigma,
                transition_model=problem.layout.transition_model,
                delta_u_eff_eV=delta_u or 0.0,
                spacecraft_potential_eV=(problem.settings.effective_field.spacecraft_potential_eV),
            ).reshape(energy.size, pitch_samples.shape[0], pitch_samples.shape[1])
            amplitude = _contrast(vector, problem, energy)
            if problem.settings.loss_cone_model == "flexible":
                log_loss = -amplitude[:, None, None] * (1.0 - transition)
            else:
                floor = np.exp(-amplitude[:, None, None])
                log_loss = np.log(floor + (1.0 - floor) * transition)
            log_loss[:, ~observation.affected, :] = 0.0
            log_normalized_samples += log_loss
        normalized_samples = np.exp(np.clip(log_normalized_samples, -100.0, 100.0))
        if problem.layout.beam is not None:
            normalized_samples += cast(FloatArray, beam_ratio)[:, :, None]
        pitch_averaged_rate = np.sum(
            normalized_samples * pitch_weights[None, None, :],
            axis=2,
        )
        rate_sum += energy_weight * incident_rate[:, None] * pitch_averaged_rate
    incident_rate = incident_sum
    rate = rate_sum
    incident_surface = np.broadcast_to(incident_rate[:, None], observation.counts.shape).astype(
        float
    )
    if observation.detector_response_matrix is not None:
        response = observation.detector_response_matrix
        physical = observation.physical_energy_row[:, None]
        latent_rate = np.where(physical & np.isfinite(rate), rate, 0.0)
        latent_incident = np.where(
            physical & np.isfinite(incident_surface),
            incident_surface,
            0.0,
        )
        rate = (response @ latent_rate.reshape(-1)).reshape(rate.shape)
        incident_surface = (response @ latent_incident.reshape(-1)).reshape(rate.shape)
    gain_factor = exp(gain)
    source_mean = observation.exposure * gain_factor * rate
    background_rate = _background_rate(vector, problem.layout, sensor_index)
    background_mean = (
        observation.known_background_counts
        + background_rate * observation.live_time_capacity_seconds
    )
    pre_dead_time_mean = source_mean + background_mean
    mean = _apply_nonparalyzable_dead_time(
        pre_dead_time_mean,
        observation.live_time_capacity_seconds,
        observation.dead_time_seconds,
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        log_incident = np.log(incident_surface)
        normalized = np.log(rate) - log_incident
        log_mean = np.log(mean)
    return (
        np.asarray(log_mean, dtype=float),
        np.asarray(normalized, dtype=float),
        np.asarray(log_incident, dtype=float),
    )


def _hemisphere_baseline_log_ratio(
    vector: FloatArray,
    problem: _Problem,
    energy_eV: FloatArray,
) -> FloatArray:
    return np.asarray(
        np.interp(
            np.log(energy_eV),
            problem.log_baseline_knots,
            vector[problem.layout.hemisphere_baseline],
        ),
        dtype=float,
    )


def _physical(
    vector: FloatArray,
    layout: _Layout,
) -> tuple[float | None, float | None, float | None]:
    if layout.model == "no_edge":
        return None, None, None
    effective_field = exp(float(vector[layout.physical.start]))
    sigma = (
        exp(float(vector[layout.physical.stop - 1]))
        if layout.transition_model == "smooth"
        else None
    )
    delta = float(vector[layout.physical.start + 1]) if layout.model == "electrostatic" else None
    return effective_field, delta, sigma


def _beam_parameters(
    vector: FloatArray,
    layout: _Layout,
) -> tuple[float | None, float | None, float | None, float | None]:
    if layout.beam is None:
        return None, None, None, None
    values = vector[layout.beam]
    return tuple(exp(float(value)) for value in values)  # type: ignore[return-value]


def _secondary_beam_ratio(
    vector: FloatArray,
    layout: _Layout,
    energy_eV: FloatArray,
    folded_pitch_samples_deg: FloatArray,
    affected: NDArray[np.bool_],
) -> FloatArray:
    output = np.zeros(
        (energy_eV.size, folded_pitch_samples_deg.shape[0], folded_pitch_samples_deg.shape[1]),
        dtype=float,
    )
    amplitude, center, sigma_energy, sigma_pitch = _beam_parameters(vector, layout)
    if amplitude is None or center is None or sigma_energy is None or sigma_pitch is None:
        return output
    energy_profile = np.exp(-0.5 * (np.log(energy_eV / center) / sigma_energy) ** 2)
    pitch_profile = np.exp(-0.5 * (folded_pitch_samples_deg / sigma_pitch) ** 2)
    output = amplitude * energy_profile[:, None, None] * pitch_profile[None, :, :]
    output[:, ~affected, :] = 0.0
    return np.asarray(output, dtype=float)


def _background_rate(vector: FloatArray, layout: _Layout, sensor_index: int) -> float:
    if layout.backgrounds.stop == layout.backgrounds.start:
        return 0.0
    return exp(float(vector[layout.backgrounds.start + sensor_index]))


def _apply_nonparalyzable_dead_time(
    expected_counts: FloatArray,
    live_time_capacity_seconds: FloatArray,
    dead_time_seconds: float,
) -> FloatArray:
    if dead_time_seconds == 0.0:
        return np.asarray(expected_counts, dtype=float)
    return np.asarray(
        expected_counts / (1.0 + dead_time_seconds * expected_counts / live_time_capacity_seconds),
        dtype=float,
    )


def _invert_nonparalyzable_dead_time(
    observed_counts: FloatArray,
    live_time_capacity_seconds: FloatArray,
    dead_time_seconds: float,
) -> FloatArray:
    if dead_time_seconds == 0.0:
        return np.asarray(observed_counts, dtype=float).copy()
    denominator = 1.0 - dead_time_seconds * observed_counts / live_time_capacity_seconds
    return np.divide(
        observed_counts,
        denominator,
        out=np.full_like(observed_counts, np.nan, dtype=float),
        where=denominator > 0.0,
    )


def _contrast(vector: FloatArray, problem: _Problem, energy_eV: FloatArray) -> FloatArray:
    contrast = problem.layout.contrast
    if contrast is None:
        return np.zeros(energy_eV.shape, dtype=float)
    values = vector[contrast]
    if problem.layout.contrast_model == "constant":
        return np.full(energy_eV.shape, float(values[0]), dtype=float)
    floor, excess, center, log_width = (float(value) for value in values)
    distance = np.log(energy_eV) - center
    return floor + excess * np.exp(-0.5 * (distance / exp(log_width)) ** 2)


def _sensor_fits(vector: FloatArray, problem: _Problem) -> tuple[GlobalSensorFit, ...]:
    fits: list[GlobalSensorFit] = []
    for index, observation in enumerate(problem.observations):
        sensor_index = problem.sensor_indices[index]
        log_mean, normalized, incident = _predicted_surfaces(
            vector,
            problem,
            sensor_index,
            observation,
        )
        gain_log = (
            0.0
            if sensor_index == 0
            else float(vector[problem.layout.gains.start + sensor_index - 1])
        )
        background_rate = _background_rate(vector, problem.layout, sensor_index)
        corrected_counts = _invert_nonparalyzable_dead_time(
            observation.counts,
            observation.live_time_capacity_seconds,
            observation.dead_time_seconds,
        )
        corrected_counts -= (
            observation.known_background_counts
            + background_rate * observation.live_time_capacity_seconds
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            observed_rate = corrected_counts / observation.exposure
            observed_log_rate = np.log(observed_rate)
        observed_normalized = observed_log_rate - incident - gain_log
        observed_normalized_linear = np.divide(
            observed_rate,
            np.exp(np.clip(incident + gain_log, -100.0, 100.0)),
            out=np.full_like(observed_rate, np.nan),
            where=np.isfinite(observed_rate) & (observed_rate >= 0.0),
        )
        observed_log_rate[~np.isfinite(observed_log_rate)] = np.nan
        observed_normalized[~np.isfinite(observed_normalized)] = np.nan
        mu = np.exp(np.clip(log_mean, -30.0, 30.0))
        dispersion = exp(float(vector[problem.layout.dispersions.start + sensor_index]))
        variance = mu + mu**2 / dispersion
        standardized = np.divide(
            observation.counts - mu,
            np.sqrt(variance),
            out=np.full_like(mu, np.nan),
            where=variance > 0.0,
        )
        for values in (observed_log_rate, log_mean, observed_normalized, normalized, standardized):
            values[~observation.valid] = np.nan
        observed_normalized_linear[~observation.valid] = np.nan
        fits.append(
            GlobalSensorFit(
                name=observation.sensor_group,
                energy_eV=observation.energy_eV,
                pitch_deg=observation.pitch_deg,
                affected_side=observation.affected_side,
                valid=observation.valid,
                observed_log_rate=observed_log_rate,
                fitted_log_rate=log_mean,
                observed_log_normalized_flux=observed_normalized,
                fitted_log_normalized_flux=normalized,
                standardized_residual=standardized,
                sensor_gain=exp(gain_log),
                dispersion=dispersion,
                background_rate_hz=background_rate,
                dead_time_seconds=observation.dead_time_seconds,
                response_kind=observation.response_kind,
                count_correction=observation.count_correction,
                count_correction_order=observation.count_correction_order,
                invalid_exposure_count_cells=observation.invalid_exposure_count_cells,
                total_counts=int(np.nansum(observation.counts[observation.valid])),
                n_cells=int(np.count_nonzero(observation.valid)),
                exposure=np.where(observation.valid, observation.exposure, np.nan),
                observed_normalized_flux=observed_normalized_linear,
                energy_edges_eV=observation.energy_edges_eV,
                pitch_edges_deg=observation.pitch_edges_deg,
            )
        )
    return tuple(fits)


def _global_pitch_edges(
    observations: tuple[_PreparedGlobalObservation, ...],
) -> FloatArray:
    source_edges = np.concatenate([item.pitch_edges_deg for item in observations])
    symmetric = np.concatenate(
        (source_edges, 180.0 - source_edges, np.asarray([0.0, 90.0, 180.0]))
    )
    edges = np.unique(np.round(np.clip(symmetric, 0.0, 180.0), 8))
    edges.sort()
    if edges.size < 3 or np.any(np.diff(edges) <= 0.0):
        raise ValueError("global pitch grid must contain increasing bins")
    return np.asarray(edges, dtype=float)


def _aggregate_bin_overlap(
    values: FloatArray,
    valid: NDArray[np.bool_],
    energy_overlap: FloatArray,
    pitch_overlap: FloatArray,
) -> FloatArray:
    contribution = np.where(valid, values, 0.0)
    return np.asarray(energy_overlap.T @ contribution @ pitch_overlap, dtype=float)


def _global_full_fov(vector: FloatArray, problem: _Problem) -> GlobalFullFOV:
    lower, upper = problem.settings.energy_bounds_eV
    energy_edges = np.geomspace(
        lower,
        upper,
        problem.settings.normalized_energy_bins + 1,
    )
    energy = np.sqrt(energy_edges[:-1] * energy_edges[1:])
    pitch_edges = _global_pitch_edges(problem.observations)
    pitch = 0.5 * (pitch_edges[:-1] + pitch_edges[1:])
    shape = (energy.size, pitch.size)
    corrected_counts = np.zeros(shape, dtype=float)
    fitted_counts = np.zeros(shape, dtype=float)
    raw_counts = np.zeros(shape, dtype=float)
    exposure = np.zeros(shape, dtype=float)
    normalized_exposure = np.zeros(shape, dtype=float)
    for observation_index, observation in enumerate(problem.observations):
        sensor_index = problem.sensor_indices[observation_index]
        gain_log = (
            0.0
            if sensor_index == 0
            else float(vector[problem.layout.gains.start + sensor_index - 1])
        )
        _log_mean, fitted_normalized, incident = _predicted_surfaces(
            vector,
            problem,
            sensor_index,
            observation,
        )
        corrected = _invert_nonparalyzable_dead_time(
            observation.counts,
            observation.live_time_capacity_seconds,
            observation.dead_time_seconds,
        )
        corrected -= (
            observation.known_background_counts
            + _background_rate(vector, problem.layout, sensor_index)
            * observation.live_time_capacity_seconds
        )
        source_normalized_exposure = observation.exposure * np.exp(
            np.clip(gain_log + incident, -100.0, 100.0)
        )
        source_fitted_counts = source_normalized_exposure * np.exp(
            np.clip(fitted_normalized, -100.0, 100.0)
        )
        valid = (
            observation.valid
            & np.isfinite(corrected)
            & np.isfinite(source_normalized_exposure)
            & (source_normalized_exposure > 0.0)
            & np.isfinite(source_fitted_counts)
        )
        energy_overlap = _bin_overlap_fraction_with_tails(
            np.log(observation.energy_edges_eV),
            np.log(energy_edges),
        )
        source_pitch_edges = observation.pitch_edges_deg
        source_counts = observation.counts
        source_exposure = observation.exposure
        if observation.affected_side == "high":
            source_pitch_edges = 180.0 - source_pitch_edges[::-1]
            corrected = corrected[:, ::-1]
            source_fitted_counts = source_fitted_counts[:, ::-1]
            source_counts = source_counts[:, ::-1]
            source_exposure = source_exposure[:, ::-1]
            source_normalized_exposure = source_normalized_exposure[:, ::-1]
            valid = valid[:, ::-1]
        pitch_overlap = _bin_overlap_fraction(source_pitch_edges, pitch_edges)

        corrected_counts += _aggregate_bin_overlap(
            corrected, valid, energy_overlap, pitch_overlap
        )
        fitted_counts += _aggregate_bin_overlap(
            source_fitted_counts, valid, energy_overlap, pitch_overlap
        )
        raw_counts += _aggregate_bin_overlap(
            source_counts, valid, energy_overlap, pitch_overlap
        )
        exposure += _aggregate_bin_overlap(
            source_exposure, valid, energy_overlap, pitch_overlap
        )
        normalized_exposure += _aggregate_bin_overlap(
            source_normalized_exposure, valid, energy_overlap, pitch_overlap
        )

    posterior_counts = np.maximum(corrected_counts, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        observed_rate = posterior_counts / normalized_exposure
        observed = np.log(np.maximum(observed_rate, np.finfo(float).tiny))
        fitted = np.log(fitted_counts / normalized_exposure)
    observed[(normalized_exposure <= 0.0) | ~np.isfinite(observed_rate)] = np.nan
    fitted[(normalized_exposure <= 0.0) | ~np.isfinite(fitted)] = np.nan
    return GlobalFullFOV(
        energy_eV=np.asarray(energy, dtype=float),
        energy_edges_eV=np.asarray(energy_edges, dtype=float),
        pitch_deg=np.asarray(pitch, dtype=float),
        pitch_edges_deg=np.asarray(pitch_edges, dtype=float),
        observed_log_normalized_flux=np.asarray(observed, dtype=float),
        fitted_log_normalized_flux=np.asarray(fitted, dtype=float),
        corrected_counts=corrected_counts,
        posterior_counts=posterior_counts,
        fitted_counts=fitted_counts,
        raw_counts=raw_counts,
        exposure=exposure,
        normalized_exposure=normalized_exposure,
        affected_side="low",
    )


def _fold_global_fov(
    full_fov: GlobalFullFOV,
    settings: GlobalJointFitSettings,
) -> GlobalNormalizedFlux:
    split_candidates = np.flatnonzero(np.isclose(full_fov.pitch_edges_deg, 90.0))
    if split_candidates.size != 1:
        raise ValueError("global pitch grid must contain exactly one 90 degree edge")
    split = int(split_candidates[0])
    if split == 0 or full_fov.pitch_deg.size - split != split:
        raise ValueError("global pitch grid must be symmetric around 90 degrees")

    def halves(values: FloatArray) -> tuple[FloatArray, FloatArray]:
        low = np.asarray(values[:, :split], dtype=float)
        high = np.asarray(values[:, split:][:, ::-1], dtype=float)
        return (low, high) if full_fov.affected_side == "low" else (high, low)

    affected_corrected_counts, reference_corrected_counts = halves(
        full_fov.corrected_counts
    )
    affected_counts, reference_counts = halves(full_fov.posterior_counts)
    fitted_affected_counts, fitted_reference_counts = halves(full_fov.fitted_counts)
    affected_raw, reference_raw = halves(full_fov.raw_counts)
    affected_exposure, reference_exposure = halves(full_fov.exposure)
    affected_normalized_exposure, reference_normalized_exposure = halves(
        full_fov.normalized_exposure
    )
    support = (affected_normalized_exposure > 0.0) & (
        reference_normalized_exposure > 0.0
    )
    prior_count = settings.normalized_rate_prior_count
    from scipy.special import digamma, polygamma

    with np.errstate(divide="ignore", invalid="ignore"):
        observed = (
            digamma(affected_counts + prior_count)
            - np.log(affected_normalized_exposure)
            - digamma(reference_counts + prior_count)
            + np.log(reference_normalized_exposure)
        )
        fitted = np.log(
            fitted_affected_counts / affected_normalized_exposure
        ) - np.log(
            fitted_reference_counts / reference_normalized_exposure
        )
        observed_std = np.sqrt(
            polygamma(1, affected_counts + prior_count)
            + polygamma(1, reference_counts + prior_count)
        )
    observed[~support | ~np.isfinite(observed)] = np.nan
    fitted[~support | ~np.isfinite(fitted)] = np.nan
    observed_std[~support | ~np.isfinite(observed_std)] = np.nan
    total_raw_counts = affected_raw + reference_raw
    reliable = (
        support
        & (total_raw_counts >= settings.normalized_min_counts)
        & (observed_std / np.log(10.0) <= settings.normalized_max_log10_std)
    )
    return GlobalNormalizedFlux(
        energy_eV=full_fov.energy_eV,
        pitch_deg=full_fov.pitch_deg[:split],
        observed_log_ratio=observed,
        fitted_log_ratio=fitted,
        affected_exposure=affected_exposure,
        reference_exposure=reference_exposure,
        energy_edges_eV=full_fov.energy_edges_eV,
        affected_counts=affected_counts,
        reference_counts=reference_counts,
        affected_normalized_exposure=affected_normalized_exposure,
        reference_normalized_exposure=reference_normalized_exposure,
        observed_log_ratio_std=np.asarray(observed_std, dtype=float),
        total_raw_counts=total_raw_counts,
        reliable=np.asarray(reliable, dtype=bool),
        affected_corrected_counts=affected_corrected_counts,
        reference_corrected_counts=reference_corrected_counts,
    )


def _normalized_flux(vector: FloatArray, problem: _Problem) -> GlobalNormalizedFlux:
    return _fold_global_fov(_global_full_fov(vector, problem), problem.settings)


def _parameter_names(
    layout: _Layout,
    sensor_names: tuple[str, ...],
    spectrum_knots: int,
) -> tuple[str, ...]:
    names: list[str] = []
    if layout.model != "no_edge":
        names.append("effective_field_nT")
        if layout.model == "electrostatic":
            names.append("delta_u_eff_eV")
        if layout.transition_model == "smooth":
            names.append("sigma_ln_b")
    names.extend(f"incident_spectrum[{index}]" for index in range(spectrum_knots))
    names.extend(
        f"hemisphere_baseline[{index}]"
        for index in range(layout.hemisphere_baseline.stop - layout.hemisphere_baseline.start)
    )
    if layout.contrast is not None:
        labels = (
            ("contrast_amplitude",)
            if layout.contrast_model == "constant"
            else ("contrast_floor", "contrast_excess", "contrast_center", "contrast_width")
        )
        names.extend(labels)
    if layout.beam is not None:
        names.extend(
            (
                "beam_amplitude",
                "beam_center_eV",
                "beam_sigma_ln_energy",
                "beam_sigma_pitch_deg",
            )
        )
    names.extend(f"{name}.gain" for name in sensor_names[1:])
    if layout.backgrounds.stop > layout.backgrounds.start:
        names.extend(f"{name}.background_rate_hz" for name in sensor_names)
    names.extend(f"{name}.dispersion" for name in sensor_names)
    return tuple(names)


def _at_bounds(vector: FloatArray, problem: _Problem) -> tuple[str, ...]:
    output: list[str] = []
    for value, bounds, name in zip(vector, problem.bounds, problem.names, strict=True):
        if bounds[0] == bounds[1]:
            continue
        tolerance = 1.0e-4 * max(1.0, abs(bounds[0]), abs(bounds[1]))
        if abs(float(value) - bounds[0]) <= tolerance or abs(float(value) - bounds[1]) <= tolerance:
            output.append(name)
    return tuple(output)


def _global_boundary_support(
    observations: tuple[_PreparedGlobalObservation, ...],
    effective_field_nT: float | None,
    delta_u: float | None,
    *,
    spacecraft_potential_eV: float,
    min_transition_energy_bins: int,
    normalized_energy_bins: int,
) -> tuple[float | None, float | None]:
    if effective_field_nT is None:
        return None, None
    all_energy = np.concatenate(
        [
            observation.energy_eV[np.any(observation.valid, axis=1)]
            for observation in observations
        ]
    )
    energy_edges = np.geomspace(
        float(np.min(all_energy)),
        float(np.max(all_energy)),
        normalized_energy_bins + 1,
    )
    below: list[set[tuple[float, float]]] = [
        set() for _ in range(normalized_energy_bins)
    ]
    above: list[set[tuple[float, float]]] = [
        set() for _ in range(normalized_energy_bins)
    ]
    active = np.zeros(normalized_energy_bins, dtype=bool)
    for observation in observations:
        boundary = mirror_boundary_sin2(
            observation.energy_eV,
            effective_field_nT / observation.b_sc_nT,
            delta_u or 0.0,
            spacecraft_potential_eV=spacecraft_potential_eV,
        )
        energy_bins = np.clip(
            np.digitize(observation.energy_eV, energy_edges) - 1,
            0,
            normalized_energy_bins - 1,
        )
        transition_rows = np.flatnonzero(
            np.isfinite(boundary) & (boundary > 0.0) & (boundary < 1.0)
        )
        for energy_index in transition_rows:
            boundary_pitch = float(
                np.rad2deg(np.arcsin(np.sqrt(boundary[energy_index])))
            )
            valid = observation.valid[energy_index] & observation.affected
            pitch_edges = observation.pitch_edges_deg
            folded_edges = np.minimum(pitch_edges, 180.0 - pitch_edges)
            folded_lower = np.minimum(folded_edges[:-1], folded_edges[1:])
            folded_upper = np.maximum(folded_edges[:-1], folded_edges[1:])
            crosses_perpendicular = (pitch_edges[:-1] < 90.0) & (pitch_edges[1:] > 90.0)
            folded_upper[crosses_perpendicular] = 90.0
            target = energy_bins[energy_index]
            for lower, upper in zip(
                folded_lower[valid], folded_upper[valid], strict=True
            ):
                pitch_bin = (round(float(lower), 8), round(float(upper), 8))
                if lower < boundary_pitch:
                    below[target].add(pitch_bin)
                if upper > boundary_pitch:
                    above[target].add(pitch_bin)
            active[target] = active[target] or bool(np.any(valid))
    if np.count_nonzero(active) < min_transition_energy_bins:
        return None, None
    return (
        float(
            np.mean(
                [
                    len(below[index]) >= 1 and len(above[index]) >= 1
                    for index in np.flatnonzero(active)
                ]
            )
        ),
        float(
            np.mean(
                [
                    len(below[index]) >= 2 and len(above[index]) >= 2
                    for index in np.flatnonzero(active)
                ]
            )
        ),
    )


def _quality_reason(
    fit: GlobalJointModelFit,
    settings: GlobalJointFitSettings,
) -> str | None:
    if not fit.success:
        return fit.reason
    if any(
        name in {"effective_field_nT", "delta_u_eff_eV", "sigma_ln_b"}
        for name in fit.at_bounds
    ):
        return "edge_parameter_at_bound"
    if _has_disallowed_contrast_bound(fit, settings):
        return "contrast_parameter_at_bound"
    if any(name.startswith("hemisphere_baseline[") for name in fit.at_bounds):
        return "hemisphere_baseline_parameter_at_bound"
    if fit.model != "no_edge" and (
        fit.boundary_bracket_fraction is None
        or fit.strict_boundary_bracket_fraction is None
        or fit.boundary_bracket_fraction
        < settings.effective_field.min_boundary_bracket_fraction
        or fit.strict_boundary_bracket_fraction
        < settings.effective_field.min_strict_boundary_bracket_fraction
    ):
        return "insufficient_boundary_bracketing"
    return None


def _has_disallowed_contrast_bound(
    fit: GlobalJointModelFit,
    settings: GlobalJointFitSettings,
) -> bool:
    """Allow a localized contrast band to have exactly zero outside the band."""

    for name in fit.at_bounds:
        if not name.startswith("contrast_"):
            continue
        if name != "contrast_floor" or fit.contrast_model != "band":
            return True
        try:
            index = fit._parameter_names.index(name)
        except ValueError:
            return True
        lower, upper = settings.effective_field.amplitude_log_ratio_bounds
        tolerance = 1.0e-4 * max(1.0, abs(lower), abs(upper))
        value = fit._parameter_values[index]
        if lower != 0.0 or abs(value - lower) > tolerance:
            return True
    return False


def _select_global_model(
    no_edge: GlobalJointModelFit,
    mirror: GlobalJointModelFit,
    electrostatic: GlobalJointModelFit,
    settings: GlobalJointFitSettings,
) -> tuple[GlobalJointModelFit, str]:
    mirror_supported = bool(
        mirror.success
        and _bic_improvement(no_edge, mirror) >= settings.effective_field.min_edge_delta_bic
    )
    electrostatic_supported = bool(
        electrostatic.success
        and _bic_improvement(no_edge, electrostatic) >= settings.effective_field.min_edge_delta_bic
        and (
            not mirror_supported
            or _bic_improvement(mirror, electrostatic)
            >= settings.effective_field.min_electrostatic_delta_bic
        )
    )
    candidates = ([electrostatic] if electrostatic_supported else []) + (
        [mirror] if mirror_supported else []
    )
    first_quality_reason: str | None = None
    for candidate in candidates:
        quality_reason = _quality_reason(candidate, settings)
        if quality_reason is None:
            reason = (
                "global_electrostatic_curvature_supported"
                if candidate.model == "electrostatic"
                else "global_mirror_edge_supported"
            )
            return candidate, reason
        if first_quality_reason is None:
            first_quality_reason = quality_reason
    return no_edge, first_quality_reason or "no_edge_evidence"


def _bic_improvement(simple: GlobalJointModelFit, complex: GlobalJointModelFit) -> float:
    if simple.bic is None or complex.bic is None:
        return float("nan")
    return float(simple.bic - complex.bic)


def _plot_fit(
    estimate: GlobalJointEstimate,
    model: CandidateModel | Literal["selected", "best_edge"],
) -> GlobalJointModelFit:
    if model == "selected":
        return estimate.fit(estimate.selected_model)
    if model != "best_edge":
        return estimate.fit(model)
    candidates = [
        fit
        for fit in estimate.model_fits
        if fit.model != "no_edge" and fit.success and fit.bic is not None
    ]
    return (
        min(candidates, key=lambda fit: cast(float, fit.bic))
        if candidates
        else estimate.fit(estimate.selected_model)
    )


def _empty_fit(
    model: CandidateModel,
    contrast_model: ResolvedContrastModel,
    transition_model: ResolvedEdgeTransition,
    reason: str,
    *,
    loss_cone_model: LossConeModel = "flexible",
) -> GlobalJointModelFit:
    return GlobalJointModelFit(
        model=model,
        contrast_model=contrast_model,
        success=False,
        reason=reason,
        mirror_ratio=None,
        delta_u_eff_eV=None,
        sigma_ln_b=None,
        secondary_beam_enabled=False,
        beam_amplitude=None,
        beam_center_eV=None,
        beam_sigma_ln_energy=None,
        beam_sigma_pitch_deg=None,
        secondary_beam_delta_bic=float("nan"),
        log_likelihood=None,
        bic=None,
        n_parameters=0,
        n_cells=0,
        at_bounds=(),
        sensors=(),
        normalized_flux=None,
        transition_model=transition_model,
        loss_cone_model=loss_cone_model,
    )


def _with_beam_delta(fit: GlobalJointModelFit, delta_bic: float) -> GlobalJointModelFit:
    return replace(fit, secondary_beam_delta_bic=delta_bic)


def _format(value: float | None, suffix: str = "") -> str:
    return "n/a" if value is None or not np.isfinite(value) else f"{value:.3g}{suffix}"


__all__ = [
    "BackgroundModel",
    "EdgeTransition",
    "GlobalFullFOV",
    "GlobalJointEstimate",
    "GlobalJointFitSettings",
    "GlobalJointModelFit",
    "GlobalNormalizedFlux",
    "GlobalPitchCountObservation",
    "GlobalSensorFit",
    "PitchOrientation",
    "ResolvedEdgeTransition",
    "SecondaryBeamMode",
    "fit_global_joint_effective_field",
    "plot_global_joint_effective_field_fit",
]
