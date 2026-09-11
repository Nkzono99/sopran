"""KAGUYA LRS/WFC-H wave-candidate preset and quality adapter.

The detector itself is mission independent and lives in :mod:`sopran.analysis.waves`.
This module contains only the instrument knowledge that should not leak into that
generic API: WFC fixed lines, the V1 thresholds, and WFC support-flag handling.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
from numpy.typing import ArrayLike, NDArray

from sopran.analysis.waves import (
    FixedLine,
    FrequencyBand,
    LineDetectionRule,
    PeakRule,
    RidgeTrackerConfig,
    WaveDetectorConfig,
    WindowConfig,
)

__all__ = [
    "KAGUYA_WFC_FIXED_LINES",
    "KAGUYA_WFC_FIXED_LINES_BY_PURPOSE",
    "KAGUYA_WFC_V1",
    "KaguyaWfcQualityMask",
    "build_kaguya_wfc_quality_mask",
    "kaguya_wfc_fixed_lines",
]


_LINE_30_KHZ_RIDGE = FixedLine(
    name="kaguya_wfc_30_khz_ridge_mask",
    frequency_khz=30.0,
    half_width_khz=2.0,
)
_LINE_200_KHZ_RADIO = FixedLine(
    name="kaguya_wfc_200_khz_radio_mask",
    frequency_khz=200.0,
    half_width_khz=12.0,
)
_LINE_957_KHZ_HIGH = FixedLine(
    name="kaguya_wfc_957_khz_high_mask",
    frequency_khz=957.0,
    half_width_khz=3.0,
)

# Clustering inherited the legacy common ±3 kHz exclusion width. Keep these as
# separate objects: reusing the detector masks would incorrectly give 200 kHz a
# ±12 kHz cluster exclusion and 30 kHz a ±2 kHz exclusion.
_LINE_30_KHZ_CLUSTERING = FixedLine(
    name="kaguya_wfc_30_khz_clustering_exclusion",
    frequency_khz=30.0,
    half_width_khz=3.0,
)
_LINE_200_KHZ_CLUSTERING = FixedLine(
    name="kaguya_wfc_200_khz_clustering_exclusion",
    frequency_khz=200.0,
    half_width_khz=3.0,
)
_LINE_957_KHZ_CLUSTERING = FixedLine(
    name="kaguya_wfc_957_khz_clustering_exclusion",
    frequency_khz=957.0,
    half_width_khz=3.0,
)

KAGUYA_WFC_FIXED_LINES: tuple[FixedLine, ...] = (
    _LINE_30_KHZ_CLUSTERING,
    _LINE_200_KHZ_CLUSTERING,
    _LINE_957_KHZ_CLUSTERING,
)
"""Legacy ±3 kHz fixed-line exclusions for raw-spectrum clustering."""

KAGUYA_WFC_FIXED_LINES_BY_PURPOSE: Mapping[str, tuple[FixedLine, ...]] = (
    MappingProxyType(
        {
            # The 30 kHz line is not masked from the overlapping low-fpe rule.
            "low_fpe": (),
            "ridge": (_LINE_30_KHZ_RIDGE,),
            "tracker": (_LINE_30_KHZ_RIDGE,),
            "radio": (_LINE_200_KHZ_RADIO,),
            "high": (_LINE_957_KHZ_HIGH,),
            # Raw peak locations at these frequencies must not dominate clusters.
            "clustering": KAGUYA_WFC_FIXED_LINES,
            # Preserve 200/957 kHz as positive RFI diagnostics instead of erasing them.
            "rfi_diagnostic": (_LINE_200_KHZ_RADIO, _LINE_957_KHZ_HIGH),
        }
    )
)
"""Purpose-specific fixed-line policy used by feature and clustering stages."""


def kaguya_wfc_fixed_lines(purpose: str) -> tuple[FixedLine, ...]:
    """Return the fixed lines applicable to one WFC analysis purpose.

    Parameters
    ----------
    purpose:
        One of ``low_fpe``, ``ridge``, ``tracker``, ``radio``, ``high``,
        ``clustering``, or ``rfi_diagnostic``. An unknown purpose is rejected
        so that a typo cannot silently disable an instrument-line mask.
    """

    try:
        return KAGUYA_WFC_FIXED_LINES_BY_PURPOSE[purpose]
    except KeyError as exc:
        choices = ", ".join(sorted(KAGUYA_WFC_FIXED_LINES_BY_PURPOSE))
        raise ValueError(
            f"unknown KAGUYA WFC fixed-line purpose {purpose!r}; expected {choices}"
        ) from exc


KAGUYA_WFC_V1 = WaveDetectorConfig(
    detector="sopran.kaguya.lrs.wfc_h.wave_candidates",
    detector_version="1",
    feature_spec_version="kaguya-wfc-wave-features-v1",
    window=WindowConfig(
        duration_seconds=120.0,
        step_seconds=60.0,
        minimum_points=8,
        minimum_frequency_bins=8,
        minimum_finite_fraction=0.65,
        frequency_minimum_khz=0.1,
        frequency_maximum_khz=1000.0,
        frequency_bins=128,
        robust_minimum_scale_db=0.5,
        z_clip=8.0,
        shape_normalize=False,
        anchor="first_sample",
    ),
    bbn_band=FrequencyBand("kaguya_wfc_bbn", 0.1, 10.0),
    bbn_core_band=FrequencyBand("kaguya_wfc_bbn_core", 0.1, 3.0),
    bbn_minimum_p90_z=2.0,
    bbn_broad_threshold_z=1.5,
    bbn_minimum_broad_fraction=0.15,
    low_ridge_rule=PeakRule(
        name="kaguya_wfc_low_fpe",
        band=FrequencyBand("kaguya_wfc_low_fpe", 2.0, 30.0),
        minimum_peak_z=1.5,
        minimum_quality=0.08,
        support_drop_z=0.75,
        maximum_log10_half_width=0.35,
        # Deliberately empty: the 30 kHz boundary is not a global low-fpe veto.
        mask_lines=(),
    ),
    high_ridge_rule=PeakRule(
        name="kaguya_wfc_plasma_ridge",
        band=FrequencyBand("kaguya_wfc_plasma_ridge", 10.0, 100.0),
        minimum_peak_z=2.5,
        minimum_quality=0.15,
        support_drop_z=1.0,
        mask_lines=kaguya_wfc_fixed_lines("ridge"),
    ),
    radio_rule=PeakRule(
        name="kaguya_wfc_radio",
        band=FrequencyBand("kaguya_wfc_radio", 100.0, 500.0),
        minimum_peak_z=3.0,
        minimum_quality=0.0,
        support_drop_z=1.0,
        mask_lines=kaguya_wfc_fixed_lines("radio"),
    ),
    radio_broad_threshold_z=1.5,
    radio_minimum_broad_fraction=0.08,
    high_band=FrequencyBand("kaguya_wfc_high", 500.0, 1000.0),
    line_rules=(
        LineDetectionRule(
            name="kaguya_wfc_200_khz_rfi",
            line_band=FrequencyBand("kaguya_wfc_200_khz_line", 180.0, 220.0),
            side_band=FrequencyBand("kaguya_wfc_200_khz_reference", 150.0, 260.0),
            minimum_peak_z=3.0,
            minimum_prominence_z=2.0,
            veto_radio=True,
        ),
        LineDetectionRule(
            name="kaguya_wfc_957_khz_rfi",
            line_band=FrequencyBand("kaguya_wfc_957_khz_line", 900.0, 1000.0),
            side_band=FrequencyBand("kaguya_wfc_957_khz_reference", 700.0, 1000.0),
            minimum_peak_z=3.0,
            minimum_prominence_z=1.5,
            veto_radio=False,
        ),
    ),
    low_tracker=RidgeTrackerConfig(
        name="kaguya_wfc_tracked_low_fpe",
        band=FrequencyBand("kaguya_wfc_tracked_low_fpe", 2.0, 30.0),
        # A path tracker must not lock to the 30 kHz boundary line even though
        # the independent low-fpe peak metric retains that boundary for review.
        mask_lines=kaguya_wfc_fixed_lines("tracker"),
    ),
    high_tracker=RidgeTrackerConfig(
        name="kaguya_wfc_tracked_plasma_ridge",
        band=FrequencyBand("kaguya_wfc_tracked_plasma_ridge", 30.0, 100.0),
        mask_lines=kaguya_wfc_fixed_lines("tracker"),
    ),
    data_warning_minimum_points=4,
    interval_merge_gap_seconds=1.0,
)
"""Versioned KAGUYA LRS/WFC-H wave-candidate detector preset."""


@dataclass(frozen=True, slots=True)
class KaguyaWfcQualityMask:
    """Hard-validity masks and non-fatal WFC state-transition warnings.

    ``sample_valid`` has the same ``(time, frequency)`` shape as the supplied
    spectrum. ``record_valid`` is suitable for the generic detector's
    ``valid_time`` argument. A warning never changes ``record_valid`` by itself.
    """

    sample_valid: NDArray[np.bool_]
    record_valid: NDArray[np.bool_]
    finite_fraction: NDArray[np.float64]
    warning: NDArray[np.bool_]
    mode_warning: NDArray[np.bool_]
    gain_warning: NDArray[np.bool_]
    fband_warning: NDArray[np.bool_]
    postgap_warning: NDArray[np.bool_]

    @property
    def valid_time(self) -> NDArray[np.bool_]:
        """Alias accepted by ``detect_wave_candidates(..., valid_time=...)``."""

        return self.record_valid

    @property
    def warning_flags(self) -> Mapping[str, NDArray[np.bool_]]:
        """Named warning arrays for feature-shard metadata."""

        return MappingProxyType(
            {
                "mode_transition": self.mode_warning,
                "gain_transition": self.gain_warning,
                "fband_transition": self.fband_warning,
                "postgap_transition": self.postgap_warning,
            }
        )

    def to_metadata(self) -> dict[str, int]:
        """Return JSON-compatible summary counts for detector/shard metadata."""

        return {
            "record_count": int(self.record_valid.size),
            "valid_record_count": int(np.count_nonzero(self.record_valid)),
            "invalid_record_count": int(np.count_nonzero(~self.record_valid)),
            "warning_record_count": int(np.count_nonzero(self.warning)),
            "mode_transition_count": int(np.count_nonzero(self.mode_warning)),
            "gain_transition_count": int(np.count_nonzero(self.gain_warning)),
            "fband_transition_count": int(np.count_nonzero(self.fband_warning)),
            "postgap_transition_count": int(np.count_nonzero(self.postgap_warning)),
        }


def build_kaguya_wfc_quality_mask(
    spectrum: ArrayLike,
    *,
    mode: ArrayLike | None = None,
    gain: ArrayLike | None = None,
    fband: ArrayLike | None = None,
    postgap: ArrayLike | None = None,
    pad_values: Sequence[float] = (254.0, 65534.0),
) -> KaguyaWfcQualityMask:
    """Build hard masks and transition warnings for a WFC-H spectrum.

    The expected spectrum shape is ``(time, frequency)``. Non-finite values and
    configured CDF pad values are invalid per frequency bin. A record remains
    usable when at least one bin is valid and every supplied support flag is
    finite/non-pad. Finite changes in Mode/Gain/Fband/PostGap are warnings, not
    hard invalidity.
    """

    values = np.asarray(spectrum, dtype=float)
    if values.ndim != 2:
        raise ValueError(
            "KAGUYA WFC spectrum must be two-dimensional with shape (time, frequency)"
        )
    if values.shape[1] == 0:
        raise ValueError("KAGUYA WFC spectrum must contain at least one frequency bin")

    pads = tuple(float(value) for value in pad_values)
    sample_valid = _finite_non_pad(values, pads)
    finite_fraction = np.mean(sample_valid, axis=1, dtype=float)
    record_valid = np.any(sample_valid, axis=1)

    warnings: dict[str, NDArray[np.bool_]] = {}
    for name, series in (
        ("mode", mode),
        ("gain", gain),
        ("fband", fband),
        ("postgap", postgap),
    ):
        series_valid, transition = _support_quality(
            name,
            series,
            n_records=values.shape[0],
            pad_values=pads,
        )
        record_valid &= series_valid
        warnings[name] = transition

    warning = np.logical_or.reduce(tuple(warnings.values()))
    return KaguyaWfcQualityMask(
        sample_valid=sample_valid,
        record_valid=record_valid,
        finite_fraction=finite_fraction,
        warning=warning,
        mode_warning=warnings["mode"],
        gain_warning=warnings["gain"],
        fband_warning=warnings["fband"],
        postgap_warning=warnings["postgap"],
    )


def _finite_non_pad(
    values: NDArray[np.float64],
    pad_values: tuple[float, ...],
) -> NDArray[np.bool_]:
    valid = np.isfinite(values)
    for pad in pad_values:
        if np.isfinite(pad):
            valid &= values != pad
    return valid


def _support_quality(
    name: str,
    values: ArrayLike | None,
    *,
    n_records: int,
    pad_values: tuple[float, ...],
) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:
    if values is None:
        return (
            np.ones(n_records, dtype=bool),
            np.zeros(n_records, dtype=bool),
        )

    array = np.asarray(values, dtype=float)
    if array.shape != (n_records,):
        raise ValueError(
            f"{name} must have shape ({n_records},), got {array.shape}"
        )
    valid = _finite_non_pad(array, pad_values)
    transition = np.zeros(n_records, dtype=bool)
    if n_records > 1:
        transition[1:] = (
            valid[1:]
            & valid[:-1]
            & np.not_equal(array[1:], array[:-1])
        )
    return valid, transition
