from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray

from sopran.analysis.electron_reflection import (
    EffectiveFieldEstimate,
    EffectiveFieldFitSettings,
    ElectronReflectionCounts,
    GlobalJointEstimate,
    GlobalJointFitSettings,
    GlobalPitchCountObservation,
    JointEffectiveFieldEstimate,
    fit_effective_field,
    fit_global_joint_effective_field,
    fit_joint_effective_field,
)
from sopran.core.data import SopranArray
from sopran.core.errors import DatasetNotFoundError
from sopran.core.pages import InfoPage
from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.store import Store
from sopran.core.time import TimeRange
from sopran.missions.kaguya.er_geometry import MAX_GEOMETRY_GAP_SECONDS, load_lmag_for_er
from sopran.missions.kaguya.geometry import MOON_MEAN_RADIUS_KM
from sopran.missions.kaguya.pace import PaceCalibration
from sopran.missions.kaguya.pitch import (
    CountCorrection,
    PitchAngleSpectrumOptions,
    build_aligned_pitch_angle_spectra,
    build_combined_pitch_angle_spectrum,
)
from sopran.missions.kaguya.schema import KAGUYA_ER_SCHEMA

if TYPE_CHECKING:
    import polars as pl
    import xarray as xr
    from matplotlib.figure import Figure

    from sopran.frames import FrameContext
    from sopran.missions.kaguya.er_catalog import EffectiveFieldCatalogBuildResult
    from sopran.missions.kaguya.mission import Kaguya

AffectedSide = Literal["low", "high", "auto"]
ResolvedSide = Literal["low", "high"]
CacheMode = Literal["use", "refresh", "never"]
DownloadMode = Literal["never", "missing", "always"]
ParallelExecutor = Literal["thread", "process"]
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


@dataclass(frozen=True)
class KaguyaEffectiveFieldData:
    """Time-indexed KAGUYA electron-reflectometry fit catalog."""

    frame: pd.DataFrame
    time: TimeRange
    files: tuple[Path, ...] = ()
    variant_id: str | None = None

    def to_pandas(self) -> pd.DataFrame:
        return self.frame.copy()

    def to_polars(self) -> pl.DataFrame:
        try:
            import polars as pl
        except ImportError as exc:
            raise RuntimeError("polars is required for KAGUYA ER parquet output") from exc
        return pl.from_pandas(self.to_pandas())

    def to_xarray(self) -> xr.Dataset:
        try:
            import xarray as xr
        except ImportError as exc:
            raise RuntimeError("xarray is required for KAGUYA ER conversion") from exc
        frame = self.to_pandas()
        if frame.empty:
            return xr.Dataset(coords={"time": np.array([], dtype="datetime64[ns]")})
        indexed = frame.copy()
        indexed["time"] = pd.to_datetime(indexed["time"], utc=True).dt.tz_convert(None)
        return xr.Dataset.from_dataframe(indexed.set_index("time"))

    def plot(self, *, y: str = "effective_field") -> Figure:
        if y not in self.frame.columns:
            raise KeyError(y)
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.plot(pd.to_datetime(self.frame["time"], utc=True), self.frame[y])
        units = KAGUYA_ER_SCHEMA.variable(y).units
        ax.set_xlabel("time")
        ax.set_ylabel(f"{y} [{units}]" if units else y)
        return fig

    def quality_summary(self) -> pd.DataFrame:
        """Return counts and fractions by quality grade and selection reason."""

        if self.frame.empty:
            return pd.DataFrame(
                columns=["quality_grade", "reason", "count", "fraction"]
            )
        grouped = (
            self.frame.groupby(["quality_grade", "reason"], dropna=False)
            .size()
            .rename("count")
            .reset_index()
        )
        grouped["fraction"] = grouped["count"] / len(self.frame)
        return grouped.sort_values(
            ["quality_grade", "count"],
            ascending=[True, False],
            ignore_index=True,
        )

    def review_queue(self, *, per_group: int = 8) -> pd.DataFrame:
        """Return a deterministic visual-audit sample across grade/reason groups."""

        if per_group <= 0:
            raise ValueError("per_group must be positive")
        if self.frame.empty:
            return self.frame.copy()
        rows: list[pd.DataFrame] = []
        for _key, group in self.frame.groupby(
            ["quality_grade", "reason"],
            dropna=False,
            sort=True,
        ):
            count = min(per_group, len(group))
            positions = np.linspace(0, len(group) - 1, count, dtype=int)
            rows.append(group.iloc[np.unique(positions)])
        return pd.concat(rows, ignore_index=True).sort_values(
            "time",
            ignore_index=True,
        )


class EffectiveFieldEndpoint:
    dataset_id = "kaguya.er.effective_field"
    name = "effective_field"

    def __init__(self, instrument: KaguyaErInstrument) -> None:
        self.instrument = instrument

    def info(self) -> InfoPage:
        return InfoPage(
            title="KAGUYA.er.effective_field",
            lines=(
                "input: full-pitch paired electron counts",
                "primary estimate: B_eff/B_sc mirror ratio",
                "models: no_edge, mirror_only, electrostatic",
                "time series: fit_timeseries(time, integration='16s')",
                "contrast: auto-select constant or log-energy band",
                "diagnostic: separate all-pitch energy-ratio change point",
                "example: kg.er.effective_field.fit(pitch_counts, b_sc_nT=..., affected_side=...)",
            ),
        )

    def schema(self) -> VariableSchema:
        return KAGUYA_ER_SCHEMA.variable("effective_field")

    def fit_joint(
        self,
        observations: Mapping[str, ElectronReflectionCounts],
        *,
        settings: EffectiveFieldFitSettings | None = None,
    ) -> JointEffectiveFieldEstimate:
        """Fit shared physical parameters to separate sensor count surfaces."""

        return fit_joint_effective_field(observations, settings=settings)

    def fit_global_joint(
        self,
        observations: Mapping[str, GlobalPitchCountObservation],
        *,
        settings: GlobalJointFitSettings | None = None,
    ) -> GlobalJointEstimate:
        """Fit unpaired full-pitch raw counts through one latent flux surface."""

        return fit_global_joint_effective_field(observations, settings=settings)

    def fit_global_spectra(
        self,
        spectra: Mapping[str, SopranArray | xr.DataArray],
        *,
        index: int,
        b_sc_nT: float,
        affected_side: ResolvedSide,
        settings: GlobalJointFitSettings | None = None,
        dead_time_seconds: float | Mapping[str, float] = 0.0,
        detector_response_matrices: Mapping[str, ArrayLike] | None = None,
        known_background_counts: Mapping[str, ArrayLike] | None = None,
    ) -> GlobalJointEstimate:
        """Fit one aligned S1/S2 sample with sensor response and count corrections."""

        observations = {
            name: GlobalPitchCountObservation.from_spectrum(
                spectrum,
                index=index,
                b_sc_nT=b_sc_nT,
                affected_side=affected_side,
                dead_time_seconds=(
                    float(dead_time_seconds.get(name, 0.0))
                    if isinstance(dead_time_seconds, Mapping)
                    else float(dead_time_seconds)
                ),
                detector_response_matrix=(
                    detector_response_matrices.get(name)
                    if detector_response_matrices is not None
                    else None
                ),
                known_background_counts=(
                    known_background_counts.get(name)
                    if known_background_counts is not None
                    else None
                ),
            )
            for name, spectrum in spectra.items()
        }
        return self.fit_global_joint(observations, settings=settings)

    def fit_timeseries(
        self,
        time: TimeRange,
        *,
        integration: str | float = "16s",
        pitch_bins: int = 16,
        min_window_coverage: float = 0.5,
        settings: GlobalJointFitSettings | None = None,
        count_correction: CountCorrection = "event_trash",
        workers: int | None = None,
        executor: ParallelExecutor = "process",
        download: DownloadMode | None = None,
        frame_context: FrameContext | None = None,
        max_time_offset_seconds: float = 1.0,
        native_cadence_seconds: float = 2.0,
        cache: CacheMode = "use",
        dataset_id: str = "kaguya.er.global_joint_effective_field",
        layer: str = "features",
        progress: Callable[[int, int], None] | None = None,
    ) -> KaguyaEffectiveFieldData:
        """Fit S1/S2 raw counts in fixed integration windows across a period."""

        from sopran.missions.kaguya.er_timeseries import fit_effective_field_timeseries

        return fit_effective_field_timeseries(
            self,
            time,
            integration=integration,
            pitch_bins=pitch_bins,
            min_window_coverage=min_window_coverage,
            settings=settings,
            count_correction=count_correction,
            workers=workers,
            executor=executor,
            download=download,
            frame_context=frame_context,
            max_time_offset_seconds=max_time_offset_seconds,
            native_cadence_seconds=native_cadence_seconds,
            cache=cache,
            dataset_id=dataset_id,
            layer=layer,
            progress=progress,
        )

    def fit(
        self,
        pitch_spectrum: SopranArray | xr.DataArray,
        *,
        b_sc_nT: ArrayLike | float | None = None,
        magnetic_field: SopranArray | ArrayLike | None = None,
        position: SopranArray | ArrayLike | None = None,
        affected_side: AffectedSide | Sequence[ResolvedSide] = "auto",
        exposure: ArrayLike | None = None,
        settings: EffectiveFieldFitSettings | None = None,
        cache: CacheMode = "use",
        variant_id: str | None = None,
        dataset_id: str | None = None,
        layer: str = "features",
        workers: int = 1,
        executor: ParallelExecutor = "thread",
    ) -> KaguyaEffectiveFieldData:
        """Fit one robust ER model comparison per time sample.

        The input must retain both 0-90 and 90-180 degree count hemispheres.
        For physically selected sides, pass magnetic-field and position vectors
        in the same frame and leave ``affected_side='auto'``.
        """

        _validate_cache(cache)
        if workers <= 0:
            raise ValueError("workers must be positive")
        if executor not in {"thread", "process"}:
            raise ValueError("executor must be 'thread' or 'process'")
        settings = settings or EffectiveFieldFitSettings()
        array, time_range, files = _pitch_array(pitch_spectrum)
        _validate_count_spectrum(array)
        times = np.asarray(array.coords["time"].values, dtype="datetime64[ns]")
        magnetic_vectors = (
            None if magnetic_field is None else _vectors_at(magnetic_field, times, "magnetic_field")
        )
        position_vectors = (
            None if position is None else _vectors_at(position, times, "position")
        )
        b_values = _resolve_b_sc(b_sc_nT, magnetic_vectors, times.size)
        sides = _resolve_sides(
            affected_side,
            magnetic_field=magnetic_vectors,
            position=position_vectors,
            size=times.size,
        )
        values = np.asarray(array.values, dtype=float)
        exposure_values, exposure_mode = _exposure_array(
            array,
            exposure,
            values,
        )
        exposure_assumed_equal = exposure_mode == "assumed_equal"
        resolved_dataset_id = dataset_id or self.dataset_id
        resolved_variant_id = variant_id or _effective_field_variant_id(
            array,
            settings=settings,
            sides=sides,
            exposure_mode=exposure_mode,
        )
        if cache == "use":
            cached = _read_cached_effective_field(
                self.instrument.mission.store,
                dataset_id=resolved_dataset_id,
                layer=layer,
                variant_id=resolved_variant_id,
                time=time_range,
            )
            if cached is not None:
                return cached

        pitch = np.asarray(array.coords["pitch_angle"].values, dtype=float)
        low_indices, high_indices, folded_pitch = _symmetric_pitch_pairs(pitch)
        energy_values = _energy_values(array)
        events: list[ElectronReflectionCounts] = []
        for index, time_value in enumerate(times):
            events.append(
                _paired_event(
                    energy_eV=energy_values[index],
                    folded_pitch=folded_pitch,
                    counts=values[index],
                    exposure=exposure_values[index],
                    low_indices=low_indices,
                    high_indices=high_indices,
                    b_sc_nT=float(b_values[index]),
                    affected_side=cast(ResolvedSide, sides[index]),
                    time_value=time_value,
                    exposure_assumed_equal=exposure_assumed_equal,
                    exposure_mode=exposure_mode,
                )
            )
        if workers == 1:
            estimates = [_fit_event(event, settings) for event in events]
        else:
            executor_class = (
                ThreadPoolExecutor if executor == "thread" else ProcessPoolExecutor
            )
            chunksize = max(1, len(events) // (workers * 4))
            with executor_class(max_workers=workers) as pool:
                estimates = list(
                    pool.map(
                        _fit_event_from_pair,
                        ((event, settings) for event in events),
                        chunksize=chunksize,
                    )
                )

        rows: list[dict[str, object]] = []
        for index, (time_value, estimate) in enumerate(
            zip(times, estimates, strict=True)
        ):
            row = estimate.to_record()
            row.update(
                {
                    "time": pd.Timestamp(time_value).tz_localize("UTC"),
                    "affected_side": str(sides[index]),
                    "b_sc_nT": float(b_values[index]),
                    "exposure_assumed_equal": exposure_assumed_equal,
                    "exposure_mode": exposure_mode,
                }
            )
            row.update(
                _geometry_record(
                    magnetic_vectors[index] if magnetic_vectors is not None else None,
                    position_vectors[index] if position_vectors is not None else None,
                )
            )
            rows.append(row)
        frame = pd.DataFrame(rows)
        result = KaguyaEffectiveFieldData(
            frame=frame,
            time=time_range,
            files=files,
            variant_id=resolved_variant_id,
        )
        if cache != "never" and not frame.empty:
            _write_effective_field(
                result,
                self.instrument.mission.store,
                dataset_id=resolved_dataset_id,
                layer=layer,
                variant_id=resolved_variant_id,
                settings=settings,
                exposure_assumed_equal=exposure_assumed_equal,
                exposure_mode=exposure_mode,
                overwrite=cache == "refresh",
            )
        return result

    def build(
        self,
        time: TimeRange,
        *,
        cadence: str | float | None = None,
        pitch_bins: int = 16,
        settings: EffectiveFieldFitSettings | None = None,
        workers: int | None = None,
        download: DownloadMode | None = None,
        frame_context: FrameContext | None = None,
        include_sza: bool = True,
        resume: bool = True,
        retry_missing: bool = False,
        dataset_id: str | None = None,
        variant_id: str | None = None,
        layer: str = "features",
        max_days: int | None = None,
        executor: ParallelExecutor = "process",
    ) -> EffectiveFieldCatalogBuildResult:
        """Build a resumable day-sharded fit catalog for a requested period."""

        from sopran.missions.kaguya.er_catalog import build_effective_field_catalog

        return build_effective_field_catalog(
            self,
            time,
            cadence=cadence,
            pitch_bins=pitch_bins,
            settings=settings,
            workers=workers,
            download=download,
            frame_context=frame_context,
            include_sza=include_sza,
            resume=resume,
            retry_missing=retry_missing,
            dataset_id=dataset_id,
            variant_id=variant_id,
            layer=layer,
            max_days=max_days,
            executor=executor,
        )

    def build_archive(
        self,
        *,
        cadence: str | float | None = "10min",
        pitch_bins: int = 16,
        settings: EffectiveFieldFitSettings | None = None,
        workers: int | None = None,
        download: DownloadMode | None = None,
        frame_context: FrameContext | None = None,
        include_sza: bool = True,
        resume: bool = True,
        retry_missing: bool = False,
        dataset_id: str | None = None,
        variant_id: str | None = None,
        layer: str = "features",
        max_days: int | None = None,
        executor: ParallelExecutor = "process",
    ) -> EffectiveFieldCatalogBuildResult:
        """Build the map-oriented catalog across the public ESA1 archive period."""

        from sopran.missions.kaguya.er_catalog import KAGUYA_ESA1_ARCHIVE_TIME

        return self.build(
            KAGUYA_ESA1_ARCHIVE_TIME,
            cadence=cadence,
            pitch_bins=pitch_bins,
            settings=settings,
            workers=workers,
            download=download,
            frame_context=frame_context,
            include_sza=include_sza,
            resume=resume,
            retry_missing=retry_missing,
            dataset_id=dataset_id,
            variant_id=variant_id,
            layer=layer,
            max_days=max_days,
            executor=executor,
        )


class KaguyaErInstrument:
    def __init__(self, mission: Kaguya) -> None:
        self.mission = mission
        self.name = "er"
        self.effective_field = EffectiveFieldEndpoint(self)

    def info(self) -> InfoPage:
        return InfoPage(
            title="KAGUYA electron reflectometry",
            lines=(
                "effective_field: robust count-likelihood mirror-field estimate",
                "pitch_angle_spectrum: combined ESA1+ESA2 full-FOV counts",
                "requires: full-pitch PACE counts and LMAG field magnitude",
            ),
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

        from sopran.frames import FrameContext
        from sopran.missions.kaguya.spice import selene_spice_kernels

        resolved_download = self.mission.download if download is None else download
        esa1_calibration = self.mission.esa1.load_calibration(
            download=resolved_download
        )
        esa2_calibration = self.mission.esa2.load_calibration(
            download=resolved_download
        )
        calibration = PaceCalibration(
            fov={**esa1_calibration.fov, **esa2_calibration.fov},
            info={**esa1_calibration.info, **esa2_calibration.info},
        )
        esa1 = self.mission.esa1.load(
            time,
            calibration=calibration,
            download=resolved_download,
            missing="error",
        )
        esa2 = self.mission.esa2.load(
            time,
            calibration=calibration,
            download=resolved_download,
            missing="error",
        )
        lmag = load_lmag_for_er(
            self.mission.lmag,
            time,
            download=resolved_download,
        )
        context = frame_context
        if context is None:
            kernels = selene_spice_kernels(
                self.mission.store,
                time,
                download=resolved_download,
            )
            context = FrameContext(
                spice_kernels=kernels,
                default_backend="spiceypy",
            )
        return build_combined_pitch_angle_spectrum(
            paces=(esa1.pace, esa2.pace),
            time=time,
            calibration=calibration,
            magnetic_field=lmag.magnetic_field,
            files=esa1.files + esa2.files + lmag.files,
            options=PitchAngleSpectrumOptions(
                value="counts",
                pitch_bins=pitch_bins,
                cadence_seconds=cadence_seconds,
                count_correction=count_correction,
            ),
            frame_context=context,
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
        """Load sensor counts; ``align=False`` retains independent native times."""

        from sopran.frames import FrameContext
        from sopran.missions.kaguya.spice import selene_spice_kernels

        resolved_download = self.mission.download if download is None else download
        esa1_calibration = self.mission.esa1.load_calibration(download=resolved_download)
        esa2_calibration = self.mission.esa2.load_calibration(download=resolved_download)
        calibration = PaceCalibration(
            fov={**esa1_calibration.fov, **esa2_calibration.fov},
            info={**esa1_calibration.info, **esa2_calibration.info},
        )
        esa1 = self.mission.esa1.load(
            time,
            calibration=calibration,
            download=resolved_download,
            missing="error",
        )
        esa2 = self.mission.esa2.load(
            time,
            calibration=calibration,
            download=resolved_download,
            missing="error",
        )
        lmag = load_lmag_for_er(
            self.mission.lmag,
            time,
            download=resolved_download,
        )
        context = frame_context
        if context is None:
            kernels = selene_spice_kernels(
                self.mission.store,
                time,
                download=resolved_download,
            )
            context = FrameContext(
                spice_kernels=kernels,
                default_backend="spiceypy",
            )
        return build_aligned_pitch_angle_spectra(
            paces=(esa1.pace, esa2.pace),
            time=time,
            calibration=calibration,
            magnetic_field=lmag.magnetic_field,
            files=esa1.files + esa2.files + lmag.files,
            options=PitchAngleSpectrumOptions(
                value="counts",
                pitch_bins=pitch_bins,
                cadence_seconds=cadence_seconds,
                count_correction=count_correction,
            ),
            frame_context=context,
            max_time_offset_seconds=max_time_offset_seconds,
            align=align,
        )

    def schema(self) -> InstrumentSchema:
        return KAGUYA_ER_SCHEMA


def _fit_event(
    event: ElectronReflectionCounts,
    settings: EffectiveFieldFitSettings,
) -> EffectiveFieldEstimate:
    return fit_effective_field(event, settings=settings)


def _fit_event_from_pair(
    pair: tuple[ElectronReflectionCounts, EffectiveFieldFitSettings],
) -> EffectiveFieldEstimate:
    return _fit_event(*pair)


def _geometry_record(
    magnetic_field: FloatArray | None,
    position: FloatArray | None,
) -> dict[str, object]:
    row: dict[str, object] = {}
    if magnetic_field is not None:
        row.update(
            {
                "magnetic_field_x": float(magnetic_field[0]),
                "magnetic_field_y": float(magnetic_field[1]),
                "magnetic_field_z": float(magnetic_field[2]),
            }
        )
    if position is None:
        return row
    radius = float(np.linalg.norm(position))
    longitude = float(np.degrees(np.arctan2(position[1], position[0])))
    latitude = (
        float(np.degrees(np.arcsin(np.clip(position[2] / radius, -1.0, 1.0))))
        if radius > 0.0
        else float("nan")
    )
    row.update(
        {
            "position_x": float(position[0]),
            "position_y": float(position[1]),
            "position_z": float(position[2]),
            "radial_distance": radius,
            "altitude": radius - MOON_MEAN_RADIUS_KM,
            "longitude": longitude,
            "latitude": latitude,
        }
    )
    if magnetic_field is not None and radius > 0.0:
        row["radial_magnetic_field"] = float(
            np.dot(magnetic_field, position / radius)
        )
    return row


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


def _pitch_array(
    spectrum: SopranArray | xr.DataArray,
) -> tuple[xr.DataArray, TimeRange, tuple[Path, ...]]:
    if isinstance(spectrum, SopranArray):
        return spectrum.to_xarray(), spectrum.time, spectrum.files
    if not hasattr(spectrum, "dims") or "time" not in spectrum.dims:
        raise TypeError("pitch_spectrum must be a SopranArray or time-indexed xarray DataArray")
    times = np.asarray(spectrum.coords["time"].values, dtype="datetime64[ns]")
    if not times.size:
        raise ValueError("pitch_spectrum contains no time samples")
    from sopran.core.time import period

    start = pd.Timestamp(times.min()).to_pydatetime()
    stop = (pd.Timestamp(times.max()) + pd.Timedelta(nanoseconds=1)).to_pydatetime()
    return spectrum, period(start, stop), ()


def _validate_count_spectrum(array: Any) -> None:
    expected = ("time", "energy", "pitch_angle")
    if tuple(array.dims) != expected:
        raise ValueError(f"pitch_spectrum dims must be {expected}")
    value = str(array.attrs.get("value", "counts"))
    units = str(array.attrs.get("units", ""))
    if value != "counts" or units not in {"count", "counts"}:
        raise ValueError("effective-field fitting requires a pitch spectrum of counts")


def _energy_values(array: Any) -> FloatArray:
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
    array: Any,
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
    side: AffectedSide | Sequence[ResolvedSide],
    *,
    magnetic_field: FloatArray | None,
    position: FloatArray | None,
    size: int,
) -> NDArray[np.str_]:
    if isinstance(side, str):
        if side == "auto":
            if magnetic_field is None or position is None:
                raise TypeError(
                    "affected_side='auto' requires magnetic_field=... and position=..."
                )
            return affected_side_from_geometry(magnetic_field, position)
        if side not in {"low", "high"}:
            raise ValueError("affected_side must be 'auto', 'low', or 'high'")
        return np.full(size, side, dtype="U4")
    values = np.asarray(tuple(side), dtype=str)
    if values.shape != (size,) or not set(values) <= {"low", "high"}:
        raise ValueError("affected_side sequence must match time and contain low/high")
    return values


def _vectors_at(
    source: SopranArray | ArrayLike,
    times: NDArray[np.datetime64],
    name: str,
    *,
    max_gap_seconds: float = MAX_GEOMETRY_GAP_SECONDS,
) -> FloatArray:
    from sopran.missions.kaguya.er_geometry import interpolate_vectors

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


def _effective_field_variant_id(
    array: Any,
    *,
    settings: EffectiveFieldFitSettings,
    sides: NDArray[np.str_],
    exposure_mode: str,
) -> str:
    payload = {
        "model_version": 2,
        "settings": asdict(settings),
        "pitch": np.asarray(array.coords["pitch_angle"].values, dtype=float).tolist(),
        "sample_shape": list(array.shape[1:]),
        "sides": sorted(set(str(value) for value in sides)),
        "exposure_mode": exposure_mode,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    return f"robust_counts_v1_{digest}"


def _read_cached_effective_field(
    store: Store,
    *,
    dataset_id: str,
    layer: str,
    variant_id: str,
    time: TimeRange,
) -> KaguyaEffectiveFieldData | None:
    try:
        record = store.dataset(dataset_id, layer=layer, variant_id=variant_id)
    except DatasetNotFoundError:
        return None
    coverage = record.manifest().get("time_coverage") or {}
    if coverage.get("start") is None or coverage.get("stop") is None:
        return None
    if str(coverage["start"]) > time.start_iso or str(coverage["stop"]) < time.stop_iso:
        return None
    frame = record.scan(dataset_id=dataset_id).collect().to_pandas()
    timestamps = pd.to_datetime(frame["time"], utc=True)
    mask = (timestamps >= time.start) & (timestamps < time.stop)
    selected = frame.loc[mask].reset_index(drop=True)
    return KaguyaEffectiveFieldData(
        frame=selected,
        time=time,
        files=(),
        variant_id=variant_id,
    )


def _write_effective_field(
    data: KaguyaEffectiveFieldData,
    store: Store,
    *,
    dataset_id: str,
    layer: str,
    variant_id: str,
    settings: EffectiveFieldFitSettings,
    exposure_assumed_equal: bool,
    exposure_mode: str,
    overwrite: bool,
) -> None:
    exists = True
    try:
        store.dataset(dataset_id, layer=layer, variant_id=variant_id)
    except DatasetNotFoundError:
        exists = False
    store.write_parquet_dataset(
        dataset_id=dataset_id,
        layer=layer,
        variant_id=variant_id,
        variant={
            "model_family": "robust_counts",
            "model_version": 2,
            "settings": asdict(settings),
            "exposure_assumed_equal": exposure_assumed_equal,
            "exposure_mode": exposure_mode,
        },
        mission="kaguya",
        instrument="er",
        product="effective_field",
        schema=KAGUYA_ER_SCHEMA,
        time_coverage=data.time,
        frame=data.to_polars(),
        source_files=tuple(str(path) for path in data.files),
        source_datasets=(
            "kaguya.pace.pitch_angle_spectrum",
            "kaguya.lmag.magnetic_field",
        ),
        overwrite=overwrite,
        append=exists and not overwrite,
        producer="sopran.kaguya.er.robust_counts",
        parameters={"effective_field_fit": asdict(settings)},
        status="candidate",
    )


def _validate_cache(cache: str) -> None:
    if cache not in {"use", "refresh", "never"}:
        raise ValueError("cache must be 'use', 'refresh', or 'never'")
