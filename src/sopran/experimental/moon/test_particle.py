"""Test-particle electron orbits in ``B_external + B_SVM3D`` (magnetic only).

A pilot-grade forward model for electron reflectometry: no electric field,
a spatially uniform external field plus the SVM3D shell grid, Boris
integration in the native kernel. Use it to check the adiabatic reading of a
loss cone, not to fit observations.
"""

from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from sopran.experimental.moon.svm3d import SVM3DShellGrid

FloatArray = NDArray[np.float64]
#: ``sqrt(2 e / m_e)`` in km/s per sqrt(eV).
ELECTRON_SPEED_KM_S_PER_SQRT_EV = 593.0967822173509
ELECTRON_GYROFREQUENCY_RAD_S_PER_NT = 1.75882001076e2
STATUS_NAMES = {
    0: "invalid_input",
    1: "returned",
    2: "surface_hit",
    3: "escaped",
    4: "max_steps",
    5: "invalid_field",
}


def gyro_period_s(field_nT: ArrayLike) -> FloatArray:
    """Electron gyro period for ``|B|`` in nT."""

    magnitude = np.abs(np.asarray(field_nT, dtype=float))
    with np.errstate(divide="ignore"):
        return np.asarray(
            2.0 * np.pi / (ELECTRON_GYROFREQUENCY_RAD_S_PER_NT * magnitude), dtype=float
        )


@dataclass(frozen=True)
class TestParticleSettings:
    """Integration step, stop conditions and field composition."""

    __test__ = False
    dt_s: float
    max_steps: int
    stop_altitude_km: float = 6.1
    escape_altitude_km: float = 3000.0
    return_radius_km: float = 1.0
    min_return_steps: int = 10
    svm_scale: float = 1.0
    bounds: str = "clamp"

    def __post_init__(self) -> None:
        if not np.isfinite(self.dt_s) or self.dt_s <= 0.0:
            raise ValueError("dt_s must be finite and positive")
        if self.max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if self.escape_altitude_km <= self.stop_altitude_km:
            raise ValueError("escape_altitude_km must exceed stop_altitude_km")
        if self.return_radius_km <= 0.0:
            raise ValueError("return_radius_km must be positive")
        if self.bounds not in {"nan", "clamp"}:
            raise ValueError("bounds must be 'nan' or 'clamp'")

    @classmethod
    def for_field(
        cls,
        field_nT: float,
        *,
        steps_per_gyration: int = 120,
        gyrations: float = 200.0,
        **kwargs: Any,
    ) -> TestParticleSettings:
        """Step as a fraction of the gyro period at ``field_nT`` and a step budget in gyrations."""

        period = float(gyro_period_s(field_nT))
        return cls(
            dt_s=period / int(steps_per_gyration),
            max_steps=int(np.ceil(float(gyrations) * int(steps_per_gyration))),
            **kwargs,
        )

    def metadata(self) -> dict[str, Any]:
        return {"model": "boris_magnetic_only_shell_grid_v1", **asdict(self)}


@dataclass(frozen=True)
class TestParticleResult:
    __test__ = False

    arrays: dict[str, np.ndarray]
    settings: TestParticleSettings

    @property
    def status(self) -> NDArray[np.str_]:
        codes = self.arrays["status_code"]
        return np.asarray([STATUS_NAMES.get(int(code), "unknown") for code in codes], dtype=str)

    def counts(self) -> dict[str, int]:
        status = self.status
        return {name: int(np.count_nonzero(status == name)) for name in STATUS_NAMES.values()}

    def to_pandas(self) -> Any:
        import pandas as pd

        columns: dict[str, Any] = {"status": self.status}
        for name, values in self.arrays.items():
            if values.ndim == 1:
                columns[name] = values
            else:
                for axis, label in enumerate("xyz"):
                    columns[f"{name}_{label}"] = values[:, axis]
        return pd.DataFrame(columns)


def electron_velocity_me(
    energy_eV: ArrayLike,
    pitch_deg: ArrayLike,
    gyrophase_deg: ArrayLike,
    magnetic_field_nT: ArrayLike,
) -> FloatArray:
    """Velocity vectors (km/s) with the given pitch angle to ``B`` and gyrophase about it."""

    energy = np.asarray(energy_eV, dtype=float).reshape(-1)
    pitch = np.deg2rad(np.asarray(pitch_deg, dtype=float).reshape(-1))
    phase = np.deg2rad(np.asarray(gyrophase_deg, dtype=float).reshape(-1))
    field = np.asarray(magnetic_field_nT, dtype=float)
    if field.ndim == 1:
        field = np.broadcast_to(field, (energy.size, 3))
    if field.shape != (energy.size, 3) or pitch.size != energy.size or phase.size != energy.size:
        raise ValueError("energy, pitch, gyrophase and field rows must align")
    norm = np.linalg.norm(field, axis=1)
    if np.any(~np.isfinite(norm)) or np.any(norm == 0.0):
        raise ValueError("magnetic_field_nT must be finite and non-zero")
    b_hat = field / norm[:, None]
    seed = np.where(np.abs(b_hat[:, [2]]) < 0.9, [[0.0, 0.0, 1.0]], [[1.0, 0.0, 0.0]])
    e1 = np.cross(b_hat, seed)
    e1 /= np.linalg.norm(e1, axis=1)[:, None]
    e2 = np.cross(b_hat, e1)
    speed = ELECTRON_SPEED_KM_S_PER_SQRT_EV * np.sqrt(energy)
    parallel = speed * np.cos(pitch)
    perpendicular = speed * np.sin(pitch)
    return np.asarray(
        b_hat * parallel[:, None]
        + e1 * (perpendicular * np.cos(phase))[:, None]
        + e2 * (perpendicular * np.sin(phase))[:, None],
        dtype=float,
    )


def trace_test_particles(
    grid: SVM3DShellGrid,
    r0_me_km: ArrayLike,
    v0_me_km_s: ArrayLike,
    b_external_nT: ArrayLike,
    *,
    settings: TestParticleSettings,
    return_center_me_km: ArrayLike | None = None,
) -> TestParticleResult:
    """Integrate one orbit per row until it hits the stop shell, escapes, or returns.

    ``returned`` means the orbit re-entered a sphere of ``return_radius_km``
    around ``return_center_me_km`` (default: the start point) after first
    leaving it. ``spacecraft_shell_*`` records the first upward crossing of
    the start radius, which is the quantity to compare with a reflected
    electron seen at the spacecraft.
    """

    r0 = _rows3(r0_me_km, "r0_me_km")
    v0 = _rows3(v0_me_km_s, "v0_me_km_s")
    b_external = _rows3(b_external_nT, "b_external_nT")
    if v0.shape != r0.shape or b_external.shape != r0.shape:
        raise ValueError("r0_me_km, v0_me_km_s and b_external_nT must share one (rows, 3) shape")
    center = (
        None if return_center_me_km is None else _rows3(return_center_me_km, "return_center_me_km")
    )
    if center is not None and center.shape != r0.shape:
        raise ValueError("return_center_me_km must match r0_me_km rows")
    try:
        native = importlib.import_module("sopran._native")
    except ImportError as exc:
        raise RuntimeError(
            "The SOPRAN native extension is required for test-particle tracing"
        ) from exc
    if not hasattr(native, "trace_test_particles_shell_grid"):
        raise RuntimeError(
            "The installed SOPRAN native extension does not provide test-particle tracing"
        )
    raw = native.trace_test_particles_shell_grid(
        np.ascontiguousarray(r0),
        np.ascontiguousarray(v0),
        np.ascontiguousarray(b_external),
        None if center is None else np.ascontiguousarray(center),
        np.ascontiguousarray(grid.longitude_deg),
        np.ascontiguousarray(grid.latitude_deg),
        np.ascontiguousarray(grid.altitude_km),
        np.ascontiguousarray(grid.field_me_nT),
        float(settings.dt_s),
        int(settings.max_steps),
        float(settings.stop_altitude_km),
        float(settings.escape_altitude_km),
        float(settings.return_radius_km),
        int(settings.min_return_steps),
        float(settings.svm_scale),
        settings.bounds,
    )
    arrays = {name: np.asarray(values) for name, values in raw.items()}
    arrays["spacecraft_shell_crossed"] = arrays["spacecraft_shell_crossed"].astype(bool)
    return TestParticleResult(arrays=arrays, settings=settings)


def _rows3(values: ArrayLike, name: str) -> FloatArray:
    array = np.asarray(values, dtype=float)
    if array.ndim == 1 and array.size == 3:
        array = array.reshape(1, 3)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(f"{name} must have shape (rows, 3)")
    return array


__all__ = [
    "ELECTRON_SPEED_KM_S_PER_SQRT_EV",
    "STATUS_NAMES",
    "TestParticleResult",
    "TestParticleSettings",
    "electron_velocity_me",
    "gyro_period_s",
    "trace_test_particles",
]
