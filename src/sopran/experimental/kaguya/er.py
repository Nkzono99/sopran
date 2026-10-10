from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import numpy as np
from numpy.typing import ArrayLike, NDArray

from sopran.core.data import SopranArray
from sopran.core.pages import InfoPage
from sopran.core.time import TimeRange
from sopran.experimental.electron_reflection import (
    ElectronReflectionCounts,
    FiniteBinFit,
    FiniteBinFitSettings,
    FiniteBinObservation,
    FiniteBinParameters,
    FiniteBinProfile,
    HalekasDistributionFit,
    HalekasFitSettings,
    fit_finite_bin_distribution,
    fit_halekas_distribution,
    profile_mirror_ratio,
)
from sopran.missions.kaguya.magnetic_geometry import MAX_GEOMETRY_GAP_SECONDS, load_lmag_with_margin
from sopran.missions.kaguya.pace import PaceCalibration, PaceData
from sopran.missions.kaguya.pitch import (
    CountCorrection,
    PitchAngleSpectrumOptions,
    build_aligned_pitch_angle_spectra,
    build_combined_pitch_angle_spectrum,
)

if TYPE_CHECKING:
    import xarray as xr

    from sopran.frames import FrameContext
    from sopran.missions.kaguya.mission import Kaguya

AffectedSide = Literal["low", "high", "auto"]
ResolvedSide = Literal["low", "high"]
DownloadMode = Literal["never", "missing", "always"]
FloatArray = NDArray[np.float64]


def affected_side_from_geometry(
    magnetic_field: ArrayLike,
    position: ArrayLike,
) -> NDArray[np.str_]:
    """Return the outgoing, loss-cone-affected pitch hemisphere.

    Pitch zero follows ``+B``. When ``+B`` points radially outward, outgoing
    electrons occupy the low-pitch hemisphere; otherwise they occupy the
    high-pitch hemisphere.
    """

    magnetic = _vector_array(magnetic_field, name="magnetic_field")
    radial = _vector_array(position, name="position")
    if magnetic.shape != radial.shape:
        raise ValueError("magnetic_field and position must have the same shape")
    dot = np.sum(magnetic * radial, axis=1)
    if np.any(~np.isfinite(dot)) or np.any(dot == 0.0):
        raise ValueError("geometry must have finite, non-perpendicular B and position vectors")
    return np.where(dot > 0.0, "low", "high").astype(str)


class EffectiveFieldEndpoint:
    """Explicit estimator entry points; results are returned without Store writes."""

    def info(self) -> InfoPage:
        return InfoPage(
            title="Experimental KAGUYA ER effective field",
            lines=(
                "fit_finite_bin: paired counts, beta-binomial (or Huber), optional D_out",
                "profile_finite_bin: Rm profile and count-likelihood interval",
                "fit_halekas: paired counts, fixed backscatter, hard/probit boundary",
                "B_eff = Rm * B_sc [nT]; delta U [eV] is surface minus spacecraft",
            ),
        )

    def fit_finite_bin(
        self,
        observation: FiniteBinObservation,
        *,
        settings: FiniteBinFitSettings | None = None,
        starts: Sequence[FiniteBinParameters] = (),
    ) -> FiniteBinFit:
        """Fit a folded finite-bin distribution with optional D_out."""
        return fit_finite_bin_distribution(observation, settings=settings, starts=starts)

    def profile_finite_bin(
        self,
        observation: FiniteBinObservation,
        fit: FiniteBinFit,
        *,
        mirror_ratios: ArrayLike | None = None,
    ) -> FiniteBinProfile:
        """Profile Rm around a finite-bin fit; count losses also give an interval."""
        return profile_mirror_ratio(observation, fit, mirror_ratios=mirror_ratios)

    def fit_halekas(
        self,
        counts: ElectronReflectionCounts,
        *,
        settings: HalekasFitSettings | None = None,
    ) -> HalekasDistributionFit:
        """Fit the fixed-backscatter full distribution with hard/probit edge."""
        return fit_halekas_distribution(counts, settings=settings)


@dataclass(frozen=True)
class _PitchInputs:
    paces: tuple[PaceData | None, PaceData | None]
    calibration: PaceCalibration
    magnetic_field: SopranArray
    files: tuple[Path, ...]
    context: FrameContext


class KaguyaErInstrument:
    """Opt-in KAGUYA counts/geometry adapter for finite-bin and Halekas fits."""

    def __init__(self, mission: Kaguya) -> None:
        self.mission = mission
        self.name = "er"
        self.effective_field = EffectiveFieldEndpoint()

    def info(self) -> InfoPage:
        return InfoPage(
            title="Experimental KAGUYA electron reflectometry",
            lines=(
                "effective_field: finite-bin or Halekas candidate estimates",
                "pitch_angle_spectrum: combined ESA1+ESA2 full-FOV counts",
                "pitch_angle_spectra: separate ESA1/ESA2 sensor counts",
                "paired_counts: fold one sample with exposure and outgoing geometry",
            ),
        )

    def paired_counts(
        self,
        pitch_spectrum: SopranArray | xr.DataArray,
        *,
        index: int,
        b_sc_nT: float | None = None,
        magnetic_field: SopranArray | ArrayLike | None = None,
        position: SopranArray | ArrayLike | None = None,
        affected_side: AffectedSide = "auto",
        exposure: ArrayLike | None = None,
    ) -> ElectronReflectionCounts:
        """Prepare one folded affected/reference sample for either estimator.

        Geometry vectors must share a frame. Explicit exposure broadcasts to
        the selected sample's energy x pitch cells; otherwise its exposure
        coordinate is used, or equal exposure is recorded as an assumption.
        Finite-bin fitting additionally requires the actual bin edges.
        """
        array = _pitch_array(pitch_spectrum)
        _validate_count_spectrum(array)
        if not 0 <= index < array.sizes["time"]:
            raise IndexError("index must select an existing time sample")
        times = np.asarray(array.coords["time"].values, dtype="datetime64[ns]")
        magnetic = (
            None
            if magnetic_field is None
            else _vectors_at(magnetic_field, times, "magnetic_field", index=index)
        )
        radial = None if position is None else _vectors_at(position, times, "position", index=index)
        b_values = _resolve_b_sc(b_sc_nT, magnetic, 1)
        sides = _resolve_sides(affected_side, magnetic_field=magnetic, position=radial, size=1)
        selected = array.isel(time=slice(index, index + 1))
        values = np.asarray(selected.values, dtype=float)
        exposure_values, mode = _exposure_array(selected, exposure, values)
        low, high, folded = _symmetric_pitch_pairs(
            np.asarray(array.coords["pitch_angle"].values, dtype=float)
        )
        return _paired_event(
            energy_eV=_energy_values(selected)[0],
            folded_pitch=folded,
            counts=values[0],
            exposure=exposure_values[0],
            low_indices=low,
            high_indices=high,
            b_sc_nT=float(b_values[0]),
            affected_side=cast(ResolvedSide, sides[0]),
            time_value=times[index],
            exposure_assumed_equal=mode == "assumed_equal",
            exposure_mode=mode,
        )

    def _load_pitch_inputs(
        self,
        time: TimeRange,
        download: DownloadMode | None,
        frame_context: FrameContext | None,
    ) -> _PitchInputs:
        from sopran.frames import FrameContext
        from sopran.missions.kaguya.spice import selene_spice_kernels

        resolved = self.mission.download if download is None else download
        c1 = self.mission.esa1.load_calibration(download=resolved)
        c2 = self.mission.esa2.load_calibration(download=resolved)
        calibration = PaceCalibration(fov={**c1.fov, **c2.fov}, info={**c1.info, **c2.info})
        esa1 = self.mission.esa1.load(
            time, calibration=calibration, download=resolved, missing="error"
        )
        esa2 = self.mission.esa2.load(
            time, calibration=calibration, download=resolved, missing="error"
        )
        lmag = load_lmag_with_margin(self.mission.lmag, time, download=resolved)
        context = frame_context
        if context is None:
            context = FrameContext(
                spice_kernels=selene_spice_kernels(self.mission.store, time, download=resolved),
                default_backend="spiceypy",
            )
        return _PitchInputs(
            paces=(esa1.pace, esa2.pace),
            calibration=calibration,
            magnetic_field=lmag.magnetic_field,
            files=esa1.files + esa2.files + lmag.files,
            context=context,
        )

    def pitch_angle_spectrum(
        self,
        time: TimeRange,
        *,
        cadence_seconds: float | None = 600.0,
        pitch_bins: int = 16,
        energy_bins: int = 24,
        count_correction: CountCorrection = "event_trash",
        download: DownloadMode | None = None,
        frame_context: FrameContext | None = None,
    ) -> SopranArray:
        """Load and combine ESA1/ESA2 into one calibrated full-FOV spectrum."""
        inputs = self._load_pitch_inputs(time, download, frame_context)
        return build_combined_pitch_angle_spectrum(
            paces=inputs.paces,
            time=time,
            calibration=inputs.calibration,
            magnetic_field=inputs.magnetic_field,
            files=inputs.files,
            options=PitchAngleSpectrumOptions(
                value="counts",
                pitch_bins=pitch_bins,
                cadence_seconds=cadence_seconds,
                count_correction=count_correction,
            ),
            frame_context=inputs.context,
            energy_bins=energy_bins,
        )

    def pitch_angle_spectra(
        self,
        time: TimeRange,
        *,
        cadence_seconds: float | None = 600.0,
        pitch_bins: int = 16,
        count_correction: CountCorrection = "event_trash",
        download: DownloadMode | None = None,
        frame_context: FrameContext | None = None,
        max_time_offset_seconds: float = 16.0,
        align: bool = True,
    ) -> dict[str, SopranArray]:
        """Load sensor counts; align=False retains independent native times."""
        inputs = self._load_pitch_inputs(time, download, frame_context)
        return build_aligned_pitch_angle_spectra(
            paces=inputs.paces,
            time=time,
            calibration=inputs.calibration,
            magnetic_field=inputs.magnetic_field,
            files=inputs.files,
            options=PitchAngleSpectrumOptions(
                value="counts",
                pitch_bins=pitch_bins,
                cadence_seconds=cadence_seconds,
                count_correction=count_correction,
            ),
            frame_context=inputs.context,
            max_time_offset_seconds=max_time_offset_seconds,
            align=align,
        )


def _paired_event(
    *,
    energy_eV: FloatArray,
    folded_pitch: FloatArray,
    counts: FloatArray,
    exposure: FloatArray,
    low_indices: NDArray[np.int64],
    high_indices: NDArray[np.int64],
    b_sc_nT: float,
    affected_side: ResolvedSide,
    time_value: np.datetime64,
    exposure_assumed_equal: bool,
    exposure_mode: str,
) -> ElectronReflectionCounts:
    if affected_side == "low":
        affected_counts = counts[:, low_indices]
        reference_counts = counts[:, high_indices]
        affected_exposure = exposure[:, low_indices]
        reference_exposure = exposure[:, high_indices]
    else:
        affected_counts = counts[:, high_indices]
        reference_counts = counts[:, low_indices]
        affected_exposure = exposure[:, high_indices]
        reference_exposure = exposure[:, low_indices]
    return ElectronReflectionCounts(
        energy_eV=energy_eV,
        pitch_deg=folded_pitch,
        affected_counts=affected_counts,
        reference_counts=reference_counts,
        b_sc_nT=b_sc_nT,
        affected_exposure=affected_exposure,
        reference_exposure=reference_exposure,
        metadata={
            "mission": "kaguya",
            "time": str(time_value),
            "affected_side": affected_side,
            "exposure_assumed_equal": exposure_assumed_equal,
            "exposure_mode": exposure_mode,
        },
    )


def _symmetric_pitch_pairs(
    pitch: FloatArray,
    *,
    tolerance_deg: float = 1.0e-6,
) -> tuple[NDArray[np.int64], NDArray[np.int64], FloatArray]:
    low = np.flatnonzero((pitch > 0.0) & (pitch < 90.0)).astype(np.int64)
    high_candidates = np.flatnonzero((pitch > 90.0) & (pitch < 180.0)).astype(np.int64)
    high: list[int] = []
    kept_low: list[int] = []
    for low_index in low:
        target = 180.0 - float(pitch[low_index])
        if not high_candidates.size:
            continue
        distance = np.abs(pitch[high_candidates] - target)
        best = int(np.argmin(distance))
        if float(distance[best]) <= tolerance_deg:
            kept_low.append(int(low_index))
            high.append(int(high_candidates[best]))
    if len(kept_low) < 3:
        raise ValueError("pitch_angle must contain at least three symmetric 0-180 degree pairs")
    low_array = np.asarray(kept_low, dtype=np.int64)
    high_array = np.asarray(high, dtype=np.int64)
    return low_array, high_array, np.asarray(pitch[low_array], dtype=float)


def _pitch_array(spectrum: SopranArray | xr.DataArray) -> xr.DataArray:
    if isinstance(spectrum, SopranArray):
        return cast("xr.DataArray", spectrum.to_xarray())
    if not hasattr(spectrum, "dims") or "time" not in spectrum.dims:
        raise TypeError("pitch_spectrum must be a SopranArray or time-indexed xarray DataArray")
    return spectrum


def _validate_count_spectrum(array: xr.DataArray) -> None:
    expected = ("time", "energy", "pitch_angle")
    if tuple(array.dims) != expected:
        raise ValueError(f"pitch_spectrum dims must be {expected}")
    value = str(array.attrs.get("value", "counts"))
    units = str(array.attrs.get("units", ""))
    if value != "counts" or units not in {"count", "counts"}:
        raise ValueError("effective-field fitting requires a pitch spectrum of counts")


def _energy_values(array: xr.DataArray) -> FloatArray:
    if "energy_eV" in array.coords:
        values = np.asarray(array.coords["energy_eV"].values, dtype=float)
        if values.ndim == 1:
            values = np.broadcast_to(values, (array.sizes["time"], values.size))
    else:
        values = np.asarray(array.coords["energy"].values, dtype=float)
        values = np.broadcast_to(values, (array.sizes["time"], values.size))
    if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
        raise ValueError("pitch_spectrum requires finite positive energy_eV coordinates")
    return np.asarray(values, dtype=float)


def _exposure_array(
    array: xr.DataArray,
    explicit: ArrayLike | None,
    counts: FloatArray,
) -> tuple[FloatArray, str]:
    source = explicit
    mode = "explicit" if explicit is not None else "provided"
    if source is None and "exposure" in array.coords:
        source = array.coords["exposure"].values
        mode = str(array.coords["exposure"].attrs.get("mode") or "provided")
    if source is None:
        source = 1.0
        mode = "assumed_equal"
    try:
        values = np.broadcast_to(np.asarray(source, dtype=float), counts.shape).astype(
            float,
            copy=True,
        )
    except ValueError as exc:
        raise ValueError("exposure must broadcast to time x energy x pitch_angle") from exc
    invalid = ~np.isfinite(values) | (values <= 0.0)
    if np.any(invalid & np.isfinite(counts)):
        raise ValueError("exposure must be finite and positive wherever counts are finite")
    values[invalid] = 1.0
    return values, mode


def _resolve_b_sc(
    explicit: ArrayLike | float | None,
    magnetic_field: FloatArray | None,
    size: int,
) -> FloatArray:
    if explicit is None:
        if magnetic_field is None:
            raise TypeError("pass b_sc_nT=... or magnetic_field=...")
        values = np.linalg.norm(magnetic_field, axis=1)
    else:
        try:
            values = np.broadcast_to(np.asarray(explicit, dtype=float), (size,)).astype(float)
        except ValueError as exc:
            raise ValueError("b_sc_nT must be scalar or match the time dimension") from exc
    if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
        raise ValueError("b_sc_nT must contain finite positive values")
    return np.asarray(values, dtype=float)


def _resolve_sides(
    side: AffectedSide,
    *,
    magnetic_field: FloatArray | None,
    position: FloatArray | None,
    size: int,
) -> NDArray[np.str_]:
    if side == "auto":
        if magnetic_field is None or position is None:
            raise TypeError("affected_side='auto' requires magnetic_field=... and position=...")
        return affected_side_from_geometry(magnetic_field, position)
    if side not in {"low", "high"}:
        raise ValueError("affected_side must be 'auto', 'low', or 'high'")
    return np.full(size, side, dtype="U4")


def _vectors_at(
    source: SopranArray | ArrayLike,
    times: NDArray[np.datetime64],
    name: str,
    *,
    max_gap_seconds: float = MAX_GEOMETRY_GAP_SECONDS,
    index: int | None = None,
) -> FloatArray:
    from sopran.missions.kaguya.magnetic_geometry import interpolate_vectors

    if index is not None:
        if not isinstance(source, SopranArray):
            values = np.asarray(source, dtype=float)
            if values.shape == (times.size, 3):
                source = values[index : index + 1]
        times = times[index : index + 1]
    if isinstance(source, SopranArray):
        array = source.to_xarray()
        vectors = np.asarray(array.values, dtype=float)
        source_times = np.asarray(array.coords["time"].values, dtype="datetime64[ns]")
        if vectors.ndim != 2 or vectors.shape[1] != 3:
            raise ValueError(f"{name} SopranArray must have time x component=3")
        source_unix = source_times.astype("int64").astype(float) / 1e9
        target_unix = times.astype("datetime64[ns]").astype("int64").astype(float) / 1e9
        return interpolate_vectors(
            source_unix, vectors, target_unix, max_gap_seconds=max_gap_seconds
        ).values
    values = _vector_array(source, name=name)
    if values.shape[0] == 1:
        return np.broadcast_to(values, (times.size, 3)).astype(float, copy=True)
    if values.shape[0] != times.size:
        raise ValueError(f"{name} must have one row or match the time dimension")
    return values


def _vector_array(value: ArrayLike, *, name: str) -> FloatArray:
    array = np.asarray(value, dtype=float)
    if array.shape == (3,):
        array = array[None, :]
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(f"{name} must have shape (3,) or (time, 3)")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain finite values")
    return np.asarray(array, dtype=float)
