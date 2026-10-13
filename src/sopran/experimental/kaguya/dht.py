"""de Hoffmann-Teller (dHT) frame for KAGUYA ESA pitch-angle spectra.

The convention follows the 2026-09-27 lunarsat validation (``er-dht-velocity-
convention``): OMNI's published GSE velocity has the mean Earth aberration
removed, so ``+29.8 km/s`` is restored once in ``Vy``; the vector is rotated at
its own OMNI epoch from GSE to J2000, the Moon's geocentric velocity is
subtracted, the tangential dHT velocity is formed in the Moon frame with the
local radial as the boundary normal, the spacecraft's selenocentric velocity is
subtracted, and the result is rotated into the look frame. Measured electron
velocities are then shifted by that boost before pitch angle and energy are
recomputed. Counts are unchanged; the response for differential energy flux
scales as ``(E/E')^2`` (Liouville).

Coverage is limited by design: records whose field is nearly tangent to the
surface (``|B.n|/|B|`` below ``min_abs_b_normal_fraction``) and records
without an OMNI sample at the lunar arrival time get no boost. In the 2026-04
lunarsat full-period runs the dHT branch retained about a quarter of the
non-dHT fits, so keep the non-dHT spectrum as the reference.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray

from sopran.core.data import SopranArray
from sopran.core.time import TimeRange
from sopran.frames import FrameContext, normalize_frame, spice_kernel_context
from sopran.missions.kaguya.magnetic_geometry import MAX_GEOMETRY_GAP_SECONDS, interpolate_vectors
from sopran.missions.kaguya.pace import PaceCalibration, PaceData
from sopran.missions.kaguya.pitch import (
    PitchAngleSpectrumOptions,
    _CountCorrectionTelemetryError,
    _datetime64_from_unix,
    _magnetic_vectors_at,
    _record_angular_data,
    _sample_records,
    _selected_records,
    pitch_angles_deg,
)
from sopran.missions.omni.hro import EARTH_RADIUS_KM, OMNI_ABERRATION_CORRECTION_KM_S

if TYPE_CHECKING:
    from sopran.missions.omni.hro import OmniHroData

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]

#: ``sqrt(2 e / m_e)`` in km/s per sqrt(eV).
ELECTRON_SPEED_KM_S_PER_SQRT_EV = 593.0967822173509
MEAN_OBLIQUITY_J2000_DEG = 23.439291111
_ECLIPTIC_NORTH_J2000 = np.array(
    [
        0.0,
        -np.sin(np.deg2rad(MEAN_OBLIQUITY_J2000_DEG)),
        np.cos(np.deg2rad(MEAN_OBLIQUITY_J2000_DEG)),
    ]
)
FRAME_POLICY = "dht_moon_frame_v1"
STATUSES = (
    "ok",
    "omni_missing",
    "geometry_missing",
    "field_tangent",
    "spice_failed",
)


@dataclass(frozen=True)
class DhtSettings:
    """Velocity convention and matching tolerances for the dHT boost."""

    min_abs_b_normal_fraction: float = 0.15
    restore_omni_aberration: bool = True
    omni_tolerance_seconds: float = 600.0
    arrival_shift: str = "radial"
    look_sign: float = 1.0
    spacecraft_id: str = "-131"
    moon_id: str = "MOON"
    earth_id: str = "EARTH"
    sun_id: str = "SUN"

    def __post_init__(self) -> None:
        if not np.isfinite(self.min_abs_b_normal_fraction) or self.min_abs_b_normal_fraction < 0.0:
            raise ValueError("min_abs_b_normal_fraction must be finite and non-negative")
        if not np.isfinite(self.omni_tolerance_seconds) or self.omni_tolerance_seconds <= 0.0:
            raise ValueError("omni_tolerance_seconds must be finite and positive")
        if self.arrival_shift not in {"radial", "none"}:
            raise ValueError("arrival_shift must be 'radial' or 'none'")
        if self.look_sign not in {1.0, -1.0}:
            raise ValueError("look_sign must be +1 or -1")

    def metadata(self) -> dict[str, Any]:
        return {
            "frame_policy": FRAME_POLICY,
            "min_abs_b_normal_fraction": self.min_abs_b_normal_fraction,
            "restore_omni_aberration": self.restore_omni_aberration,
            "aberration_correction_km_s": list(OMNI_ABERRATION_CORRECTION_KM_S),
            "omni_tolerance_seconds": self.omni_tolerance_seconds,
            "arrival_shift": self.arrival_shift,
            "look_sign": self.look_sign,
            "boost": (
                "HT velocity in the Moon frame from (V_omni + aberration - V_moon/earth), "
                "minus V_sc/moon, rotated to the look frame"
            ),
        }


@dataclass(frozen=True)
class DhtFrameVelocity:
    """Per-record boost and the diagnostics that explain missing rows."""

    times_unix: FloatArray
    velocity_look_frame_km_s: FloatArray
    velocity_moon_me_km_s: FloatArray
    ok: BoolArray
    status: NDArray[np.str_]
    b_normal_fraction: FloatArray
    omni_source_time_unix: FloatArray
    omni_dt_seconds: FloatArray
    arrival_correction_seconds: FloatArray
    moon_speed_km_s: FloatArray
    spacecraft_speed_km_s: FloatArray
    look_frame: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def coverage(self) -> dict[str, int]:
        counts = {name: int(np.count_nonzero(self.status == name)) for name in STATUSES}
        counts["records"] = int(self.times_unix.size)
        return counts

    def to_pandas(self) -> pd.DataFrame:
        import pandas as pd

        return pd.DataFrame(
            {
                "time_unix": self.times_unix,
                "ok": self.ok,
                "status": self.status,
                "b_normal_fraction": self.b_normal_fraction,
                "boost_x_km_s": self.velocity_look_frame_km_s[:, 0],
                "boost_y_km_s": self.velocity_look_frame_km_s[:, 1],
                "boost_z_km_s": self.velocity_look_frame_km_s[:, 2],
                "boost_speed_km_s": np.linalg.norm(self.velocity_look_frame_km_s, axis=1),
                "omni_source_time_unix": self.omni_source_time_unix,
                "omni_dt_seconds": self.omni_dt_seconds,
                "arrival_correction_seconds": self.arrival_correction_seconds,
                "moon_speed_km_s": self.moon_speed_km_s,
                "spacecraft_speed_km_s": self.spacecraft_speed_km_s,
            }
        )


def gse_basis_j2000(sun_direction_j2000: ArrayLike) -> FloatArray:
    """Row-wise GSE basis columns ``(+X, +Y, +Z)`` expressed in J2000."""

    sun = np.asarray(sun_direction_j2000, dtype=float).reshape(-1, 3)
    x_axis = _unit_rows(sun)
    seed = np.broadcast_to(_ECLIPTIC_NORTH_J2000, x_axis.shape)
    z_axis = _unit_rows(seed - np.sum(seed * x_axis, axis=1)[:, None] * x_axis)
    y_axis = _unit_rows(np.cross(z_axis, x_axis))
    return cast(FloatArray, np.stack((x_axis, y_axis, z_axis), axis=2))


def dht_tangential_velocity(
    plasma_velocity_km_s: ArrayLike,
    magnetic_field: ArrayLike,
    normal: ArrayLike,
    *,
    min_abs_b_normal_fraction: float = 0.15,
) -> tuple[FloatArray, BoolArray, FloatArray]:
    """Tangential dHT velocity ``u - B (u.n)/(B.n)`` per row (native kernel or numpy)."""

    plasma = _rows3(plasma_velocity_km_s, "plasma_velocity_km_s")
    magnetic = _rows3(magnetic_field, "magnetic_field")
    normals = _rows3(normal, "normal")
    if magnetic.shape != plasma.shape or normals.shape != plasma.shape:
        raise ValueError(
            "plasma velocity, magnetic field and normal must share one (rows, 3) shape"
        )
    native = _native_module()
    if native is not None:
        raw = native.dht_tangential_velocity_batch(
            np.ascontiguousarray(plasma),
            np.ascontiguousarray(magnetic),
            np.ascontiguousarray(normals),
            float(min_abs_b_normal_fraction),
        )
        return (
            np.asarray(raw["velocity_km_s"], dtype=float),
            np.asarray(raw["ok"]).astype(bool),
            np.asarray(raw["b_normal_fraction"], dtype=float),
        )
    b_norm = np.linalg.norm(magnetic, axis=1)
    n_hat = _unit_rows(normals)
    b_normal = np.sum(magnetic * n_hat, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        fraction = np.abs(b_normal) / b_norm
        u_normal = np.sum(plasma * n_hat, axis=1)
        velocity = plasma - magnetic * (u_normal / b_normal)[:, None]
    finite = (
        np.isfinite(plasma).all(axis=1)
        & np.isfinite(magnetic).all(axis=1)
        & np.isfinite(normals).all(axis=1)
        & (b_norm > 0.0)
    )
    ok = (
        finite
        & (fraction >= max(min_abs_b_normal_fraction, 0.0))
        & np.isfinite(velocity).all(axis=1)
    )
    velocity[~ok] = np.nan
    fraction = np.where(finite, fraction, np.nan)
    return velocity, ok, fraction


def shift_looks(
    energy_eV: ArrayLike,
    theta_deg: ArrayLike,
    phi_deg: ArrayLike,
    magnetic_field: ArrayLike,
    frame_velocity_km_s: ArrayLike,
    *,
    look_sign: float = 1.0,
) -> tuple[FloatArray, FloatArray, BoolArray]:
    """Pitch angle and energy of each look after subtracting the frame velocity.

    ``energy_eV``, ``theta_deg`` and ``phi_deg`` are ``(rows, looks)``;
    ``magnetic_field`` and ``frame_velocity_km_s`` are ``(rows, 3)`` in the look
    frame. Returns ``(pitch_deg, energy_eV, ok)`` with the input shape.
    """

    energy = np.asarray(energy_eV, dtype=float)
    theta = np.asarray(theta_deg, dtype=float)
    phi = np.asarray(phi_deg, dtype=float)
    if energy.ndim != 2 or theta.shape != energy.shape or phi.shape != energy.shape:
        raise ValueError("energy_eV, theta_deg and phi_deg must share one (rows, looks) shape")
    magnetic = _rows3(magnetic_field, "magnetic_field")
    frame = _rows3(frame_velocity_km_s, "frame_velocity_km_s")
    if magnetic.shape[0] != energy.shape[0] or frame.shape[0] != energy.shape[0]:
        raise ValueError("magnetic_field and frame_velocity_km_s must have one row per energy row")
    native = _native_module()
    if native is not None:
        raw = native.shift_look_velocity_batch(
            np.ascontiguousarray(energy),
            np.ascontiguousarray(theta),
            np.ascontiguousarray(phi),
            np.ascontiguousarray(magnetic),
            np.ascontiguousarray(frame),
            float(look_sign),
        )
        return (
            np.asarray(raw["pitch_deg"], dtype=float),
            np.asarray(raw["energy_eV"], dtype=float),
            np.asarray(raw["ok"]).astype(bool),
        )
    return _shift_looks_numpy(energy, theta, phi, magnetic, frame, look_sign)


def _shift_looks_numpy(
    energy: FloatArray,
    theta: FloatArray,
    phi: FloatArray,
    magnetic: FloatArray,
    frame: FloatArray,
    look_sign: float,
) -> tuple[FloatArray, FloatArray, BoolArray]:
    theta_rad = np.deg2rad(theta)
    phi_rad = np.deg2rad(phi)
    look = np.stack(
        (
            np.cos(phi_rad) * np.cos(theta_rad),
            np.sin(phi_rad) * np.cos(theta_rad),
            np.sin(theta_rad),
        ),
        axis=-1,
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        speed = ELECTRON_SPEED_KM_S_PER_SQRT_EV * np.sqrt(energy)
        sign = -1.0 if look_sign < 0 else 1.0
        velocity = look * (sign * speed)[..., None]
        shifted = velocity - frame[:, None, :]
        shifted_speed = np.linalg.norm(shifted, axis=-1)
        b_norm = np.linalg.norm(magnetic, axis=1)
        cos_pitch = np.sum(shifted * magnetic[:, None, :], axis=-1) / (
            shifted_speed * b_norm[:, None]
        )
        pitch = np.rad2deg(np.arccos(np.clip(cos_pitch, -1.0, 1.0)))
        new_energy = (shifted_speed / ELECTRON_SPEED_KM_S_PER_SQRT_EV) ** 2
    ok = (
        np.isfinite(energy)
        & (energy > 0.0)
        & np.isfinite(pitch)
        & np.isfinite(new_energy)
        & (new_energy > 0.0)
        & np.asarray(np.isfinite(frame).all(axis=1), dtype=bool)[:, None]
        & (b_norm > 0.0)[:, None]
    )
    pitch = np.where(ok, pitch, np.nan)
    new_energy = np.where(ok, new_energy, np.nan)
    return pitch, new_energy, ok


def lunar_arrival_times(
    omni_time_unix: ArrayLike,
    bsn_x_re: ArrayLike,
    speed_km_s: ArrayLike,
    moon_gse_x_km: ArrayLike,
) -> tuple[FloatArray, FloatArray]:
    """Radial OMNI-to-Moon time shift ``(Re * BSN_x - x_moon) / V_sw`` per sample."""

    times = np.asarray(omni_time_unix, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        correction = (
            EARTH_RADIUS_KM * np.asarray(bsn_x_re, dtype=float)
            - np.asarray(moon_gse_x_km, dtype=float)
        ) / np.abs(np.asarray(speed_km_s, dtype=float))
    correction = np.where(
        np.isfinite(correction) & (np.asarray(speed_km_s, dtype=float) > 0.0), correction, np.nan
    )
    return times + correction, correction


def frame_velocity(
    times_unix: ArrayLike,
    *,
    magnetic_field_me_nT: ArrayLike,
    position_me_km: ArrayLike,
    position_gse_km: ArrayLike,
    omni: OmniHroData | pd.DataFrame,
    frame_context: FrameContext,
    look_frame: str = "SELENE_M_SPACECRAFT",
    settings: DhtSettings | None = None,
) -> DhtFrameVelocity:
    """Boost velocity for each record time in the look frame.

    ``magnetic_field_me_nT`` and ``position_me_km`` are MOON_ME rows per
    record, ``position_gse_km`` the GSE spacecraft position used as the Moon's
    x for the arrival shift. ``omni`` is a loaded HRO 5-minute table with
    ``vx_gse``, ``vy_gse``, ``vz_gse``, ``speed`` and ``bsn_x`` columns. The
    SPICE kernels of ``frame_context`` must cover Earth, Moon, Sun and the
    spacecraft (``selene_spice_kernels``).
    """

    selected = settings or DhtSettings()
    times = np.asarray(times_unix, dtype=float).reshape(-1)
    magnetic = _rows3(magnetic_field_me_nT, "magnetic_field_me_nT")
    position = _rows3(position_me_km, "position_me_km")
    gse = _rows3(position_gse_km, "position_gse_km")
    if (
        magnetic.shape[0] != times.size
        or position.shape[0] != times.size
        or gse.shape[0] != times.size
    ):
        raise ValueError("geometry arrays must have one row per record time")
    rows = times.size
    status = np.full(rows, "ok", dtype="<U17")
    boost_look = np.full((rows, 3), np.nan)
    boost_me = np.full((rows, 3), np.nan)
    fraction = np.full(rows, np.nan)
    moon_speed = np.full(rows, np.nan)
    sc_speed = np.full(rows, np.nan)
    frame_name = normalize_frame(look_frame)
    omni_frame = omni if isinstance(omni, pd.DataFrame) else omni.to_dataframe()
    omni_time, omni_velocity, source_time, dt, correction = _match_omni(
        times, omni_frame, gse[:, 0], selected
    )
    geometry_ok = np.isfinite(magnetic).all(axis=1) & np.isfinite(position).all(axis=1)
    geometry_ok &= np.linalg.norm(magnetic, axis=1) > 0.0
    geometry_ok &= np.linalg.norm(position, axis=1) > 0.0
    status[~geometry_ok] = "geometry_missing"
    omni_ok = np.isfinite(omni_velocity).all(axis=1)
    status[geometry_ok & ~omni_ok] = "omni_missing"
    active = geometry_ok & omni_ok
    if rows and np.any(active):
        try:
            boost_me, boost_look, fraction, moon_speed, sc_speed, spice_ok = _boost_rows(
                times,
                omni_time,
                omni_velocity,
                magnetic,
                position,
                active,
                frame_context,
                frame_name,
                selected,
            )
        except Exception as exc:  # SPICE setup failed for the whole batch
            status[active] = "spice_failed"
            metadata = selected.metadata()
            metadata["error"] = f"{type(exc).__name__}: {exc}"
            return _frame_velocity_result(
                times,
                boost_look,
                boost_me,
                status,
                fraction,
                source_time,
                dt,
                correction,
                moon_speed,
                sc_speed,
                frame_name,
                metadata,
            )
        status[active & ~spice_ok] = "spice_failed"
        tangent = active & spice_ok & ~np.asarray(np.isfinite(boost_me).all(axis=1), dtype=bool)
        status[tangent] = "field_tangent"
    return _frame_velocity_result(
        times,
        boost_look,
        boost_me,
        status,
        fraction,
        source_time,
        dt,
        correction,
        moon_speed,
        sc_speed,
        frame_name,
        selected.metadata(),
    )


def _frame_velocity_result(
    times: FloatArray,
    boost_look: FloatArray,
    boost_me: FloatArray,
    status: NDArray[np.str_],
    fraction: FloatArray,
    source_time: FloatArray,
    dt: FloatArray,
    correction: FloatArray,
    moon_speed: FloatArray,
    sc_speed: FloatArray,
    frame_name: str,
    metadata: dict[str, Any],
) -> DhtFrameVelocity:
    ok = (status == "ok") & np.isfinite(boost_look).all(axis=1)
    status = np.where(ok | (status != "ok"), status, "spice_failed")
    boost_look = np.where(ok[:, None], boost_look, np.nan)
    return DhtFrameVelocity(
        times_unix=times,
        velocity_look_frame_km_s=boost_look,
        velocity_moon_me_km_s=boost_me,
        ok=ok,
        status=status.astype(str),
        b_normal_fraction=fraction,
        omni_source_time_unix=source_time,
        omni_dt_seconds=dt,
        arrival_correction_seconds=correction,
        moon_speed_km_s=moon_speed,
        spacecraft_speed_km_s=sc_speed,
        look_frame=frame_name,
        metadata=metadata,
    )


def _match_omni(
    times: FloatArray,
    omni: pd.DataFrame,
    moon_gse_x_km: FloatArray,
    settings: DhtSettings,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray]:
    rows = times.size
    missing = (
        np.full(rows, np.nan),
        np.full((rows, 3), np.nan),
        np.full(rows, np.nan),
        np.full(rows, np.nan),
        np.full(rows, np.nan),
    )
    required = {"vx_gse", "vy_gse", "vz_gse", "speed", "bsn_x"}
    if omni is None or len(omni) == 0 or not required <= set(omni.columns):
        return missing
    index = pd.DatetimeIndex(omni.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    omni_unix = (
        index.tz_convert(None).to_numpy(dtype="datetime64[ns]").astype("int64").astype(float) / 1e9
    )
    velocity = omni[["vx_gse", "vy_gse", "vz_gse"]].to_numpy(dtype=float)
    speed = omni["speed"].to_numpy(dtype=float)
    bsn_x = omni["bsn_x"].to_numpy(dtype=float)
    if settings.arrival_shift == "radial":
        finite_time = np.isfinite(times) & np.isfinite(moon_gse_x_km)
        if not np.any(finite_time):
            return missing
        order = np.argsort(times[finite_time])
        moon_x_at_omni = np.interp(
            omni_unix, times[finite_time][order], moon_gse_x_km[finite_time][order]
        )
        arrival, correction = lunar_arrival_times(omni_unix, bsn_x, speed, moon_x_at_omni)
    else:
        arrival = omni_unix.copy()
        correction = np.zeros(omni_unix.size)
    usable = np.isfinite(arrival) & np.isfinite(velocity).all(axis=1)
    if not np.any(usable):
        return missing
    arrival = arrival[usable]
    velocity = velocity[usable]
    correction = correction[usable]
    omni_unix = omni_unix[usable]
    order = np.argsort(arrival)
    arrival, velocity, correction, omni_unix = (
        arrival[order],
        velocity[order],
        correction[order],
        omni_unix[order],
    )
    position = np.searchsorted(arrival, times)
    left = np.clip(position - 1, 0, arrival.size - 1)
    right = np.clip(position, 0, arrival.size - 1)
    choose_right = np.abs(arrival[right] - times) < np.abs(arrival[left] - times)
    nearest = np.where(choose_right, right, left)
    dt = times - arrival[nearest]
    matched = np.isfinite(dt) & (np.abs(dt) <= settings.omni_tolerance_seconds)
    matched_velocity = np.where(matched[:, None], velocity[nearest], np.nan)
    if settings.restore_omni_aberration:
        matched_velocity = matched_velocity + np.asarray(OMNI_ABERRATION_CORRECTION_KM_S)
    return (
        np.where(matched, omni_unix[nearest], np.nan),
        matched_velocity,
        np.where(matched, omni_unix[nearest], np.nan),
        np.where(matched, dt, np.nan),
        np.where(matched, correction[nearest], np.nan),
    )


def _boost_rows(
    times: FloatArray,
    omni_time: FloatArray,
    omni_velocity_gse: FloatArray,
    magnetic_me: FloatArray,
    position_me: FloatArray,
    active: BoolArray,
    frame_context: FrameContext,
    look_frame: str,
    settings: DhtSettings,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray, BoolArray]:
    try:
        import spiceypy
    except ImportError as exc:
        raise RuntimeError("spiceypy is required for the dHT boost") from exc
    rows = times.size
    boost_me = np.full((rows, 3), np.nan)
    boost_look = np.full((rows, 3), np.nan)
    fraction = np.full(rows, np.nan)
    moon_speed = np.full(rows, np.nan)
    sc_speed = np.full(rows, np.nan)
    spice_ok = np.zeros(rows, dtype=bool)
    indices = np.flatnonzero(active)
    kernels = tuple(frame_context.spice_kernels)
    with spice_kernel_context(spiceypy, kernels):
        plasma_j2000 = np.full((rows, 3), np.nan)
        moon_v_j2000 = np.full((rows, 3), np.nan)
        sc_v_j2000 = np.full((rows, 3), np.nan)
        for index in indices:
            try:
                et_omni = spiceypy.str2et(_utc_iso(omni_time[index]))
                sun, _ = spiceypy.spkpos(
                    settings.sun_id, et_omni, "J2000", "NONE", settings.earth_id
                )
                basis = gse_basis_j2000(np.asarray(sun, dtype=float))[0]
                plasma_j2000[index] = basis @ omni_velocity_gse[index]
                et = spiceypy.str2et(_utc_iso(times[index]))
                moon_state, _ = spiceypy.spkezr(
                    settings.moon_id, et, "J2000", "NONE", settings.earth_id
                )
                sc_state, _ = spiceypy.spkezr(
                    settings.spacecraft_id, et, "J2000", "NONE", settings.moon_id
                )
                moon_v_j2000[index] = np.asarray(moon_state, dtype=float)[3:6]
                sc_v_j2000[index] = np.asarray(sc_state, dtype=float)[3:6]
                spice_ok[index] = True
            except Exception:
                reset = getattr(spiceypy, "reset", None)
                if reset is not None:
                    reset()
                spice_ok[index] = False
    if not np.any(spice_ok):
        return boost_me, boost_look, fraction, moon_speed, sc_speed, spice_ok
    rotated = {}
    for name, vectors in (("plasma", plasma_j2000), ("moon", moon_v_j2000), ("sc", sc_v_j2000)):
        rotated[name] = np.asarray(
            frame_context.transform_vectors(
                vectors, times=times, source_frame="J2000", target_frame="MOON_ME", missing="nan"
            ),
            dtype=float,
        )
    moon_me = rotated["moon"]
    sc_me = rotated["sc"]
    plasma_me = rotated["plasma"] - moon_me
    normal = _unit_rows(position_me)
    ht_me, ht_ok, fraction = dht_tangential_velocity(
        plasma_me, magnetic_me, normal, min_abs_b_normal_fraction=settings.min_abs_b_normal_fraction
    )
    boost_me = ht_me - sc_me
    boost_me[~(ht_ok & spice_ok)] = np.nan
    moon_speed = np.where(spice_ok, np.linalg.norm(moon_me, axis=1), np.nan)
    sc_speed = np.where(spice_ok, np.linalg.norm(sc_me, axis=1), np.nan)
    if look_frame == normalize_frame("MOON_ME"):
        boost_look = boost_me.copy()
    else:
        boost_look = np.asarray(
            frame_context.transform_vectors(
                np.where(np.isfinite(boost_me), boost_me, 0.0),
                times=times,
                source_frame="MOON_ME",
                target_frame=look_frame,
                missing="nan",
            ),
            dtype=float,
        )
        boost_look[~np.isfinite(boost_me).all(axis=1)] = np.nan
    spice_ok &= np.isfinite(moon_me).all(axis=1) & np.isfinite(sc_me).all(axis=1)
    spice_ok &= np.isfinite(rotated["plasma"]).all(axis=1)
    return boost_me, boost_look, fraction, moon_speed, sc_speed, spice_ok


@dataclass(frozen=True)
class DhtSpectrum:
    """Shifted-frame pitch spectrum with the boost diagnostics used to build it."""

    spectrum: SopranArray
    frame: DhtFrameVelocity


def dht_pitch_angle_spectrum(
    *,
    pace: PaceData,
    time: TimeRange,
    calibration: PaceCalibration,
    magnetic_field: SopranArray,
    position: SopranArray,
    position_gse: SopranArray,
    omni: OmniHroData | pd.DataFrame,
    frame_context: FrameContext,
    energy_edges_eV: ArrayLike,
    pitch_bins: int = 16,
    options: PitchAngleSpectrumOptions | None = None,
    settings: DhtSettings | None = None,
    files: tuple[Any, ...] = (),
) -> DhtSpectrum:
    """Counts of one sensor on fixed energy bands x pitch bins after the dHT shift.

    Records without a boost are dropped from the spectrum (their reasons stay
    in ``frame.status``). Energies after the shift fall into
    ``energy_edges_eV`` bands, so the output grid is the same for every record.
    ``exposure`` is the summed look response scaled by ``(E/E')^2`` so that
    ``counts / exposure`` approximates the differential energy flux in the
    shifted frame; ``exposure_unshifted`` keeps the plain sum.
    """

    options = options or PitchAngleSpectrumOptions(value="counts")
    if options.value != "counts":
        raise ValueError("dht_pitch_angle_spectrum builds counts; derive fluxes from exposure")
    selected = settings or DhtSettings()
    edges_energy = np.asarray(energy_edges_eV, dtype=float).reshape(-1)
    if (
        edges_energy.size < 2
        or not np.all(np.diff(edges_energy) > 0.0)
        or np.any(edges_energy <= 0.0)
    ):
        raise ValueError("energy_edges_eV must be increasing and positive")
    if pitch_bins < 2:
        raise ValueError("pitch_bins must be at least 2")
    edges_pitch = np.linspace(0.0, 180.0, int(pitch_bins) + 1)
    records = _sample_records(
        _selected_records(pace, time), cadence_seconds=options.cadence_seconds
    )
    times_unix = np.asarray([float(header["time"]) for _record, header in records], dtype=float)
    look_frame = normalize_frame(options.look_frame)
    magnetic_me = _vectors_at(magnetic_field, times_unix, "magnetic_field")
    position_me = _vectors_at(position, times_unix, "position")
    gse = _vectors_at(position_gse, times_unix, "position_gse")
    frame = frame_velocity(
        times_unix,
        magnetic_field_me_nT=magnetic_me,
        position_me_km=position_me,
        position_gse_km=gse,
        omni=omni,
        frame_context=frame_context,
        look_frame=look_frame,
        settings=selected,
    )
    magnetic_look = (
        _magnetic_vectors_at(
            magnetic_field,
            times_unix,
            look_frame=look_frame,
            magnetic_frame=options.magnetic_frame,
            frame_context=frame_context,
        )
        if times_unix.size
        else np.empty((0, 3))
    )
    n_bands = edges_energy.size - 1
    n_pitch = edges_pitch.size - 1
    counts_rows: list[FloatArray] = []
    exposure_rows: list[FloatArray] = []
    exposure_raw_rows: list[FloatArray] = []
    looks_rows: list[FloatArray] = []
    energy_rows: list[FloatArray] = []
    pitch_unshifted_rows: list[FloatArray] = []
    used_times: list[np.datetime64] = []
    modes: list[int] = []
    for row_index, (record, header) in enumerate(records):
        if not frame.ok[row_index]:
            continue
        b_look = magnetic_look[row_index]
        if not np.all(np.isfinite(b_look)) or np.linalg.norm(b_look) == 0.0:
            continue
        try:
            angular = _record_angular_data(
                record,
                header,
                pace.sensor,
                calibration,
                value="counts",
                count_correction=options.count_correction,
            )
        except _CountCorrectionTelemetryError:
            raise
        except ValueError:
            continue
        rows = angular.energy.shape[0]
        b_rows = np.broadcast_to(b_look, (rows, 3))
        v_rows = np.broadcast_to(frame.velocity_look_frame_km_s[row_index], (rows, 3))
        pitch_shift, energy_shift, ok = shift_looks(
            angular.energy, angular.theta, angular.phi, b_rows, v_rows, look_sign=selected.look_sign
        )
        pitch_native = pitch_angles_deg(angular.theta, angular.phi, b_look)
        valid = ok & (angular.detector_bins == 1) & np.isfinite(angular.values)
        valid &= np.isfinite(angular.exposure) & (angular.exposure > 0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            liouville = (angular.energy / energy_shift) ** 2
        cell = _bin_shifted(
            values=angular.values,
            exposure=angular.exposure,
            liouville=liouville,
            energy=energy_shift,
            pitch=pitch_shift,
            pitch_native=pitch_native,
            valid=valid,
            energy_edges=edges_energy,
            pitch_edges=edges_pitch,
            min_look_bins=options.min_look_bins,
        )
        counts_rows.append(cell["counts"])
        exposure_rows.append(cell["exposure"])
        exposure_raw_rows.append(cell["exposure_unshifted"])
        looks_rows.append(cell["looks"])
        energy_rows.append(cell["energy"])
        pitch_unshifted_rows.append(cell["pitch_unshifted"])
        used_times.append(_datetime64_from_unix(float(header["time"])))
        modes.append(int(header["mode"]) if "mode" in header else -1)
    array = _dht_spectrum_array(
        counts=np.stack(counts_rows) if counts_rows else np.empty((0, n_bands, n_pitch)),
        exposure=np.stack(exposure_rows) if exposure_rows else np.empty((0, n_bands, n_pitch)),
        exposure_unshifted=(
            np.stack(exposure_raw_rows) if exposure_raw_rows else np.empty((0, n_bands, n_pitch))
        ),
        looks=np.stack(looks_rows) if looks_rows else np.empty((0, n_bands, n_pitch)),
        energy=np.stack(energy_rows) if energy_rows else np.empty((0, n_bands, n_pitch)),
        pitch_unshifted=(
            np.stack(pitch_unshifted_rows)
            if pitch_unshifted_rows
            else np.empty((0, n_bands, n_pitch))
        ),
        times=np.asarray(used_times, dtype="datetime64[ns]"),
        modes=np.asarray(modes, dtype=np.int32),
        energy_edges=edges_energy,
        pitch_edges=edges_pitch,
        time=time,
        files=files or tuple(pace.source_files),
        options=options,
        frame=frame,
        sensor=pace.sensor,
    )
    return DhtSpectrum(spectrum=array, frame=frame)


def _bin_shifted(
    *,
    values: FloatArray,
    exposure: FloatArray,
    liouville: FloatArray,
    energy: FloatArray,
    pitch: FloatArray,
    pitch_native: FloatArray,
    valid: BoolArray,
    energy_edges: FloatArray,
    pitch_edges: FloatArray,
    min_look_bins: int,
) -> dict[str, FloatArray]:
    n_bands = energy_edges.size - 1
    n_pitch = pitch_edges.size - 1
    band = np.searchsorted(energy_edges, energy, side="right") - 1
    cell = np.searchsorted(pitch_edges, pitch, side="right") - 1
    cell = np.where(pitch == pitch_edges[-1], n_pitch - 1, cell)
    band = np.where(energy == energy_edges[-1], n_bands - 1, band)
    inside = valid & (band >= 0) & (band < n_bands) & (cell >= 0) & (cell < n_pitch)
    flat = band[inside] * n_pitch + cell[inside]
    size = n_bands * n_pitch
    looks = np.bincount(flat, minlength=size).astype(float)
    counts = np.bincount(flat, weights=values[inside], minlength=size)
    raw_exposure = np.bincount(flat, weights=exposure[inside], minlength=size)
    shifted_exposure = np.bincount(flat, weights=(exposure * liouville)[inside], minlength=size)
    energy_sum = np.bincount(flat, weights=energy[inside], minlength=size)
    pitch_sum = np.bincount(flat, weights=pitch_native[inside], minlength=size)
    enough = looks >= max(int(min_look_bins), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        energy_mean = np.where(enough, energy_sum / looks, np.nan)
        pitch_mean = np.where(enough, pitch_sum / looks, np.nan)
    out = {
        "counts": np.where(enough, counts, np.nan).reshape(n_bands, n_pitch),
        "exposure": np.where(enough, shifted_exposure, np.nan).reshape(n_bands, n_pitch),
        "exposure_unshifted": np.where(enough, raw_exposure, np.nan).reshape(n_bands, n_pitch),
        "looks": looks.reshape(n_bands, n_pitch),
        "energy": energy_mean.reshape(n_bands, n_pitch),
        "pitch_unshifted": pitch_mean.reshape(n_bands, n_pitch),
    }
    return out


def _dht_spectrum_array(
    *,
    counts: FloatArray,
    exposure: FloatArray,
    exposure_unshifted: FloatArray,
    looks: FloatArray,
    energy: FloatArray,
    pitch_unshifted: FloatArray,
    times: NDArray[np.datetime64],
    modes: NDArray[np.int32],
    energy_edges: FloatArray,
    pitch_edges: FloatArray,
    time: TimeRange,
    files: tuple[Any, ...],
    options: PitchAngleSpectrumOptions,
    frame: DhtFrameVelocity,
    sensor: int,
) -> SopranArray:
    import xarray as xr

    from sopran.core.schema import VariableSchema

    centers_energy = np.sqrt(energy_edges[:-1] * energy_edges[1:])
    centers_pitch = 0.5 * (pitch_edges[:-1] + pitch_edges[1:])
    coords: dict[str, Any] = {
        "time": times,
        "energy": np.arange(centers_energy.size),
        "pitch_angle": centers_pitch,
        "energy_eV": (
            ("time", "energy"),
            np.broadcast_to(centers_energy, (times.size, centers_energy.size)).copy(),
        ),
        "exposure": (("time", "energy", "pitch_angle"), exposure),
        "exposure_unshifted": (("time", "energy", "pitch_angle"), exposure_unshifted),
        "look_samples": (("time", "energy", "pitch_angle"), looks),
        "shifted_energy_mean_eV": (("time", "energy", "pitch_angle"), energy),
        "unshifted_pitch_mean_deg": (("time", "energy", "pitch_angle"), pitch_unshifted),
        "pace_data_mode": ("time", modes),
    }
    attrs: dict[str, Any] = {
        "units": "count",
        "value": "counts",
        "pitch_edges": pitch_edges.tolist(),
        "energy_edges_eV": energy_edges.tolist(),
        "look_frame": frame.look_frame,
        "count_correction": options.count_correction,
        "frame_policy": FRAME_POLICY,
        "dht": frame.metadata,
        "coverage": frame.coverage(),
        "exposure_scaling": "sum(exposure * (E/E')^2) over looks in the shifted cell",
        "sensor": sensor,
    }
    array = xr.DataArray(counts, dims=("time", "energy", "pitch_angle"), coords=coords, attrs=attrs)
    array.coords["exposure"].attrs["mode"] = "calibrated_dht"
    schema = VariableSchema(
        name="dht_pitch_angle_spectrum",
        dims=("time", "energy", "pitch_angle"),
        units="count",
        frame=frame.look_frame,
        description="Raw counts on energy bands x pitch bins after the dHT velocity shift",
    )
    return SopranArray(
        name="experimental.kaguya.dht_pitch_angle_spectrum",
        time=time,
        schema=schema,
        files=tuple(files),
        operations=(
            {
                "operation": "dht_pitch_angle_spectrum",
                "parameters": {**frame.metadata, "coverage": frame.coverage()},
            },
        ),
        xr=array,
    )


def _vectors_at(source: SopranArray, times_unix: FloatArray, name: str) -> FloatArray:
    array = source.to_xarray()
    values = np.asarray(array.values, dtype=float)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError(f"{name} must have shape (time, component=3)")
    source_unix = (
        np.asarray(array.coords["time"].values, dtype="datetime64[ns]")
        .astype("int64")
        .astype(float)
        / 1e9
    )
    if times_unix.size == 0:
        return np.empty((0, 3))
    return cast(
        FloatArray,
        interpolate_vectors(
            source_unix, values, times_unix, max_gap_seconds=MAX_GEOMETRY_GAP_SECONDS
        ).values,
    )


def _utc_iso(unix_time: float) -> str:
    return datetime.fromtimestamp(float(unix_time), tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _unit_rows(values: FloatArray) -> FloatArray:
    norm = np.linalg.norm(values, axis=1)
    return cast(
        FloatArray,
        np.divide(
            values, norm[:, None], out=np.full(values.shape, np.nan), where=norm[:, None] > 0.0
        ),
    )


def _rows3(values: ArrayLike, name: str) -> FloatArray:
    array = np.asarray(values, dtype=float)
    if array.ndim == 1 and array.size == 3:
        array = array.reshape(1, 3)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(f"{name} must have shape (rows, 3)")
    return array


def _native_module() -> Any | None:
    try:
        module = importlib.import_module("sopran._native")
    except ImportError:
        return None
    return module if hasattr(module, "shift_look_velocity_batch") else None


__all__ = [
    "DhtFrameVelocity",
    "DhtSettings",
    "DhtSpectrum",
    "ELECTRON_SPEED_KM_S_PER_SQRT_EV",
    "FRAME_POLICY",
    "STATUSES",
    "dht_pitch_angle_spectrum",
    "dht_tangential_velocity",
    "frame_velocity",
    "gse_basis_j2000",
    "lunar_arrival_times",
    "shift_looks",
]
