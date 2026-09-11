from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
import pandas as pd

MOON_MEAN_RADIUS_KM = 1737.4
BoundsMode = Literal["nan", "clamp", "raise"]


@dataclass(frozen=True)
class SVM3DTraceSettings:
    """Numerical settings for a coarse-grained native field-line trace."""

    step_km: float = 1.0
    max_steps: int = 1000
    stop_altitude_km: float = 6.05

    def validate(self) -> None:
        if not np.isfinite(self.step_km) or self.step_km <= 0.0:
            raise ValueError("step_km must be finite and positive")
        if self.max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if not np.isfinite(self.stop_altitude_km) or self.stop_altitude_km < 0.0:
            raise ValueError("stop_altitude_km must be finite and non-negative")


@dataclass(frozen=True)
class SVM3DTraceResult:
    """Batch trace arrays returned from one signed field-line direction."""

    connection_sign: np.ndarray
    arrays: dict[str, np.ndarray]
    settings: SVM3DTraceSettings

    @property
    def valid(self) -> np.ndarray:
        return self.arrays["valid"]

    @property
    def target_crossed(self) -> np.ndarray:
        return self.arrays["target_crossed"]

    def to_pandas(self, *, prefix: str = "svm3d") -> pd.DataFrame:
        columns = {
            f"{prefix}_{name}": values
            for name, values in self.arrays.items()
        }
        columns[f"{prefix}_connection_sign"] = self.connection_sign
        return pd.DataFrame(columns)


@dataclass(frozen=True)
class SVM3DShellGrid:
    """Vector SVM field sampled on regular longitude, latitude, and altitude shells."""

    longitude_deg: np.ndarray
    latitude_deg: np.ndarray
    altitude_km: np.ndarray
    field_me_nT: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    def __post_init__(self) -> None:
        longitude = np.asarray(self.longitude_deg, dtype=np.float64)
        latitude = np.asarray(self.latitude_deg, dtype=np.float64)
        altitude = np.asarray(self.altitude_km, dtype=np.float64)
        values = np.asarray(self.field_me_nT, dtype=np.float64)
        expected = (altitude.size, latitude.size, longitude.size, 3)
        if longitude.ndim != 1 or latitude.ndim != 1 or altitude.ndim != 1:
            raise ValueError("SVM3D shell coordinates must be one-dimensional")
        if min(longitude.size, latitude.size, altitude.size) < 2:
            raise ValueError("SVM3D shell coordinates need at least two values")
        if values.shape != expected:
            raise ValueError(f"field_me_nT shape must be {expected}, got {values.shape}")
        for name, coordinate in (
            ("longitude_deg", longitude),
            ("latitude_deg", latitude),
            ("altitude_km", altitude),
        ):
            if not np.all(np.isfinite(coordinate)) or not np.all(np.diff(coordinate) > 0.0):
                raise ValueError(f"{name} must be finite and strictly increasing")
        if not np.allclose(np.diff(longitude), np.diff(longitude)[0]):
            raise ValueError("longitude_deg must be uniformly spaced")
        if not np.allclose(np.diff(latitude), np.diff(latitude)[0]):
            raise ValueError("latitude_deg must be uniformly spaced")
        object.__setattr__(self, "longitude_deg", longitude)
        object.__setattr__(self, "latitude_deg", latitude)
        object.__setattr__(self, "altitude_km", altitude)
        object.__setattr__(self, "field_me_nT", values)
        object.__setattr__(self, "path", None if self.path is None else Path(self.path))

    @classmethod
    def load(cls, path: Path | str) -> SVM3DShellGrid:
        source = Path(path)
        with np.load(source, allow_pickle=False) as payload:
            metadata = (
                json.loads(str(payload["metadata_json"]))
                if "metadata_json" in payload.files
                else {}
            )
            return cls(
                longitude_deg=payload["lon_deg"],
                latitude_deg=payload["lat_deg"],
                altitude_km=payload["alt_km"],
                field_me_nT=payload["field_me_nT"],
                metadata=metadata,
                path=source,
            )

    @classmethod
    def build(
        cls,
        source_path: Path | str,
        *,
        altitudes_km: Any = (6.1, 10.0, 20.0, 30.0, 50.0, 75.0, 100.0, 150.0, 200.0),
        longitude_step_deg: float = 0.5,
        latitude_step_deg: float = 0.5,
        min_direct_altitude_km: float = 6.05,
        adaptive_longitude: bool = True,
    ) -> SVM3DShellGrid:
        """Build regular shells, reducing redundant direct evaluations near the poles."""

        if longitude_step_deg <= 0.0 or latitude_step_deg <= 0.0:
            raise ValueError("shell coordinate steps must be positive")
        altitude = np.unique(np.asarray(altitudes_km, dtype=np.float64).reshape(-1))
        if altitude.size < 2 or not np.all(np.isfinite(altitude)):
            raise ValueError("altitudes_km must contain at least two finite values")
        longitude_count = int(round(360.0 / longitude_step_deg))
        latitude_intervals = int(round(180.0 / latitude_step_deg))
        if not np.isclose(longitude_count * longitude_step_deg, 360.0) or not np.isclose(
            latitude_intervals * latitude_step_deg,
            180.0,
        ):
            raise ValueError("shell coordinate steps must divide 360 and 180 degrees")
        longitude = np.arange(longitude_count, dtype=np.float64) * longitude_step_deg
        latitude = -90.0 + np.arange(latitude_intervals + 1, dtype=np.float64) * latitude_step_deg
        values = np.empty(
            (altitude.size, latitude.size, longitude.size, 3),
            dtype=np.float64,
        )
        direct_longitudes = _adaptive_longitude_rows(
            latitude,
            angular_step_deg=min(longitude_step_deg, latitude_step_deg),
            adaptive=adaptive_longitude,
        )
        direct_longitude = np.concatenate(direct_longitudes)
        direct_latitude = np.concatenate(
            [np.full(row.size, latitude[index]) for index, row in enumerate(direct_longitudes)]
        )
        for index, shell_altitude in enumerate(altitude):
            positions = lon_lat_alt_to_cartesian(
                direct_longitude,
                direct_latitude,
                np.full(direct_longitude.size, shell_altitude),
            )
            direct_values = evaluate_tsunakawa_svm3d(
                source_path,
                positions,
                min_altitude_km=min_direct_altitude_km,
            )
            offset = 0
            for latitude_index, row_longitude in enumerate(direct_longitudes):
                row_values = direct_values[offset : offset + row_longitude.size]
                values[index, latitude_index] = _periodic_vector_interpolation(
                    row_longitude,
                    row_values,
                    longitude,
                )
                offset += row_longitude.size
        source = Path(source_path)
        return cls(
            longitude_deg=longitude,
            latitude_deg=latitude,
            altitude_km=altitude,
            field_me_nT=values,
            metadata={
                "schema_version": 1,
                "kind": "svm3d_shell_grid",
                "created_utc": datetime.now(UTC).isoformat(),
                "source_path": str(source.resolve()),
                "source_size_bytes": source.stat().st_size,
                "longitude_step_deg": longitude_step_deg,
                "latitude_step_deg": latitude_step_deg,
                "altitudes_km": altitude.tolist(),
                "minimum_direct_altitude_km": min_direct_altitude_km,
                "backend": "sopran-native-direct-svm",
                "adaptive_longitude": adaptive_longitude,
                "direct_nodes_per_shell": int(direct_longitude.size),
            },
        )

    def save(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            target,
            lon_deg=self.longitude_deg,
            lat_deg=self.latitude_deg,
            alt_km=self.altitude_km,
            field_me_nT=self.field_me_nT,
            metadata_json=json.dumps(self.metadata, ensure_ascii=False, sort_keys=True),
        )
        return target

    def finite_fraction_by_altitude(self) -> np.ndarray:
        return np.asarray(
            np.mean(np.all(np.isfinite(self.field_me_nT), axis=3), axis=(1, 2)),
            dtype=np.float64,
        )

    def interpolate(
        self,
        longitude_deg: Any,
        latitude_deg: Any,
        altitude_km: Any,
        *,
        bounds: BoundsMode = "nan",
    ) -> np.ndarray:
        """Trilinearly interpolate Cartesian MOON_ME field components."""

        if bounds not in {"nan", "clamp", "raise"}:
            raise ValueError("bounds must be 'nan', 'clamp', or 'raise'")
        longitude, latitude, altitude = np.broadcast_arrays(
            np.asarray(longitude_deg, dtype=np.float64),
            np.asarray(latitude_deg, dtype=np.float64),
            np.asarray(altitude_km, dtype=np.float64),
        )
        original_shape = longitude.shape
        lon = longitude.reshape(-1)
        lat = latitude.reshape(-1).copy()
        alt = altitude.reshape(-1).copy()
        finite = np.isfinite(lon) & np.isfinite(lat) & np.isfinite(alt)
        outside = (
            ~finite
            | (lat < self.latitude_deg[0])
            | (lat > self.latitude_deg[-1])
            | (alt < self.altitude_km[0])
            | (alt > self.altitude_km[-1])
        )
        if bounds == "raise" and np.any(outside):
            raise ValueError("requested positions are outside the SVM3D shell grid")
        if bounds == "clamp":
            lat = np.clip(lat, self.latitude_deg[0], self.latitude_deg[-1])
            alt = np.clip(alt, self.altitude_km[0], self.altitude_km[-1])
            inside = finite
        else:
            inside = ~outside
        output = np.full((lon.size, 3), np.nan, dtype=np.float64)
        if not np.any(inside):
            return output.reshape(original_shape + (3,))

        selected_lon = lon[inside]
        selected_lat = lat[inside]
        selected_alt = alt[inside]
        lon_step = float(self.longitude_deg[1] - self.longitude_deg[0])
        period = lon_step * self.longitude_deg.size
        lon_position = np.mod(selected_lon - self.longitude_deg[0], period) / lon_step
        lon0 = np.floor(lon_position).astype(np.int64) % self.longitude_deg.size
        lon1 = (lon0 + 1) % self.longitude_deg.size
        lon_fraction = lon_position - np.floor(lon_position)
        lat0, lat1, lat_fraction = _brackets(self.latitude_deg, selected_lat)
        alt0, alt1, alt_fraction = _brackets(self.altitude_km, selected_alt)

        c000 = self.field_me_nT[alt0, lat0, lon0]
        c001 = self.field_me_nT[alt0, lat0, lon1]
        c010 = self.field_me_nT[alt0, lat1, lon0]
        c011 = self.field_me_nT[alt0, lat1, lon1]
        c100 = self.field_me_nT[alt1, lat0, lon0]
        c101 = self.field_me_nT[alt1, lat0, lon1]
        c110 = self.field_me_nT[alt1, lat1, lon0]
        c111 = self.field_me_nT[alt1, lat1, lon1]
        lon_weight = lon_fraction[:, None]
        lat_weight = lat_fraction[:, None]
        alt_weight = alt_fraction[:, None]
        lower = _lerp(
            _lerp(c000, c001, lon_weight),
            _lerp(c010, c011, lon_weight),
            lat_weight,
        )
        upper = _lerp(
            _lerp(c100, c101, lon_weight),
            _lerp(c110, c111, lon_weight),
            lat_weight,
        )
        output[inside] = _lerp(lower, upper, alt_weight)
        return output.reshape(original_shape + (3,))

    def field_at(self, positions_km: Any, *, bounds: BoundsMode = "nan") -> np.ndarray:
        positions = _vector_rows(positions_km, "positions_km")
        longitude, latitude, altitude = cartesian_to_lon_lat_alt(positions)
        return self.interpolate(longitude, latitude, altitude, bounds=bounds)

    def residual_external_field(
        self,
        positions_km: Any,
        measured_field_nT: Any,
    ) -> np.ndarray:
        """Return the uniform residual that reproduces LMAG at the spacecraft."""

        positions = _vector_rows(positions_km, "positions_km")
        measured = _vector_rows(measured_field_nT, "measured_field_nT")
        if positions.shape != measured.shape:
            raise ValueError("positions_km and measured_field_nT must have the same shape")
        return cast(np.ndarray, measured - self.field_at(positions))

    def trace(
        self,
        positions_km: Any,
        external_field_nT: Any,
        connection_sign: Any,
        *,
        target_field_nT: Any | None = None,
        settings: SVM3DTraceSettings | None = None,
    ) -> SVM3DTraceResult:
        """Trace a signed batch through ``B_external + B_SVM3D`` using native RK4."""

        positions = np.ascontiguousarray(_vector_rows(positions_km, "positions_km"))
        external = np.ascontiguousarray(_vector_rows(external_field_nT, "external_field_nT"))
        if positions.shape != external.shape:
            raise ValueError("positions_km and external_field_nT must have the same shape")
        signs = np.ascontiguousarray(connection_sign, dtype=np.int32).reshape(-1)
        if signs.size != positions.shape[0] or not np.all(np.isin(signs, (-1, 1))):
            raise ValueError("connection_sign must contain one -1 or +1 value per row")
        targets = (
            np.full(positions.shape[0], np.nan, dtype=np.float64)
            if target_field_nT is None
            else np.ascontiguousarray(target_field_nT, dtype=np.float64).reshape(-1)
        )
        if targets.size != positions.shape[0]:
            raise ValueError("target_field_nT must match positions_km rows")
        selected = settings or SVM3DTraceSettings(
            stop_altitude_km=float(self.altitude_km[0])
        )
        selected.validate()
        finite_fraction = self.finite_fraction_by_altitude()
        if not np.all(finite_fraction == 1.0):
            incomplete = ", ".join(
                f"{altitude:g} km={fraction:.3%}"
                for altitude, fraction in zip(
                    self.altitude_km[finite_fraction < 1.0],
                    finite_fraction[finite_fraction < 1.0],
                    strict=True,
                )
            )
            raise ValueError(f"SVM3D tracing requires complete shells; incomplete: {incomplete}")
        native = _native_module()
        raw = cast(
            dict[str, Any],
            native.trace_svm3d_shell_grid(
                positions,
                external,
                signs,
                targets,
                np.ascontiguousarray(self.longitude_deg),
                np.ascontiguousarray(self.latitude_deg),
                np.ascontiguousarray(self.altitude_km),
                np.ascontiguousarray(self.field_me_nT),
                selected.step_km,
                selected.max_steps,
                selected.stop_altitude_km,
            ),
        )
        arrays = {name: np.asarray(values) for name, values in raw.items()}
        arrays["valid"] = arrays["valid"].astype(bool)
        arrays["target_crossed"] = arrays["target_crossed"].astype(bool)
        return SVM3DTraceResult(signs, arrays, selected)

    def accuracy_report(
        self,
        source_path: Path | str,
        *,
        samples: int = 64,
        seed: int = 0,
        min_altitude_km: float | None = None,
        max_altitude_km: float | None = None,
    ) -> dict[str, Any]:
        """Compare shell interpolation with the source SVM integral at fixed random points."""

        if samples <= 0:
            raise ValueError("samples must be positive")
        lower = float(self.altitude_km[0] if min_altitude_km is None else min_altitude_km)
        upper = float(self.altitude_km[-1] if max_altitude_km is None else max_altitude_km)
        if lower < self.altitude_km[0] or upper > self.altitude_km[-1] or lower >= upper:
            raise ValueError("accuracy altitude range must lie within the shell grid")
        rng = np.random.default_rng(seed)
        longitude = rng.uniform(-180.0, 180.0, samples)
        latitude = np.degrees(np.arcsin(rng.uniform(-1.0, 1.0, samples)))
        altitude = rng.uniform(lower, upper, samples)
        positions = lon_lat_alt_to_cartesian(longitude, latitude, altitude)
        interpolated = self.interpolate(longitude, latitude, altitude)
        direct = evaluate_tsunakawa_svm3d(
            source_path,
            positions,
            min_altitude_km=float(self.altitude_km[0]),
        )
        finite = np.all(np.isfinite(interpolated), axis=1) & np.all(np.isfinite(direct), axis=1)
        difference = np.linalg.norm(interpolated[finite] - direct[finite], axis=1)
        reference = np.linalg.norm(direct[finite], axis=1)
        relative = difference / np.maximum(reference, 1.0e-12)
        source = Path(source_path)
        return {
            "samples": samples,
            "finite_samples": int(np.count_nonzero(finite)),
            "seed": seed,
            "altitude_range_km": [lower, upper],
            "median_vector_error_nT": _percentile(difference, 50.0),
            "p95_vector_error_nT": _percentile(difference, 95.0),
            "maximum_vector_error_nT": _percentile(difference, 100.0),
            "median_relative_error": _percentile(relative, 50.0),
            "p95_relative_error": _percentile(relative, 95.0),
            "median_direct_field_nT": _percentile(reference, 50.0),
            "source": str(source.resolve()),
            "source_size_bytes": source.stat().st_size,
        }

    def provenance(self) -> dict[str, Any]:
        return {
            "path": None if self.path is None else str(self.path.resolve()),
            "sha256": None if self.path is None else _sha256(self.path),
            "shape": list(self.field_me_nT.shape),
            "longitude_step_deg": float(self.longitude_deg[1] - self.longitude_deg[0]),
            "latitude_step_deg": float(self.latitude_deg[1] - self.latitude_deg[0]),
            "altitudes_km": self.altitude_km.tolist(),
            "finite_fraction_by_altitude": self.finite_fraction_by_altitude().tolist(),
            "metadata": self.metadata,
        }


def evaluate_tsunakawa_svm3d(
    path: Path | str,
    positions_km: Any,
    *,
    min_altitude_km: float = 6.05,
) -> np.ndarray:
    """Evaluate the Tsunakawa surface integral in one native batch."""

    positions = np.ascontiguousarray(_vector_rows(positions_km, "positions_km"))
    native = _native_module()
    return np.asarray(
        native.evaluate_tsunakawa_svm3d(str(Path(path)), positions, min_altitude_km),
        dtype=np.float64,
    )


def cartesian_to_lon_lat_alt(positions_km: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    positions = _vector_rows(positions_km, "positions_km")
    radius = np.linalg.norm(positions, axis=1)
    longitude = np.degrees(np.arctan2(positions[:, 1], positions[:, 0]))
    latitude = np.degrees(
        np.arcsin(
            np.divide(
                positions[:, 2],
                radius,
                out=np.full(radius.shape, np.nan),
                where=radius > 0.0,
            )
        )
    )
    return longitude, latitude, radius - MOON_MEAN_RADIUS_KM


def lon_lat_alt_to_cartesian(
    longitude_deg: Any,
    latitude_deg: Any,
    altitude_km: Any,
) -> np.ndarray:
    longitude, latitude, altitude = np.broadcast_arrays(
        np.asarray(longitude_deg, dtype=np.float64),
        np.asarray(latitude_deg, dtype=np.float64),
        np.asarray(altitude_km, dtype=np.float64),
    )
    lon = np.radians(longitude.reshape(-1))
    lat = np.radians(latitude.reshape(-1))
    radius = MOON_MEAN_RADIUS_KM + altitude.reshape(-1)
    return np.column_stack(
        (
            radius * np.cos(lat) * np.cos(lon),
            radius * np.cos(lat) * np.sin(lon),
            radius * np.sin(lat),
        )
    )


def _brackets(
    coordinate: np.ndarray,
    values: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    upper = np.searchsorted(coordinate, values, side="right")
    upper = np.clip(upper, 1, coordinate.size - 1)
    lower = upper - 1
    fraction = (values - coordinate[lower]) / (coordinate[upper] - coordinate[lower])
    return lower, upper, fraction


def _lerp(left: np.ndarray, right: np.ndarray, fraction: np.ndarray) -> np.ndarray:
    return cast(np.ndarray, left + fraction * (right - left))


def _adaptive_longitude_rows(
    latitude_deg: np.ndarray,
    *,
    angular_step_deg: float,
    adaptive: bool,
) -> list[np.ndarray]:
    regular_count = int(round(360.0 / angular_step_deg))
    rows: list[np.ndarray] = []
    for latitude in latitude_deg:
        cosine = abs(float(np.cos(np.radians(latitude))))
        if cosine < 1.0e-12:
            count = 1
        elif adaptive:
            count = max(8, int(np.ceil(regular_count * cosine)))
        else:
            count = regular_count
        rows.append(np.arange(count, dtype=np.float64) * (360.0 / count))
    return rows


def _periodic_vector_interpolation(
    source_longitude_deg: np.ndarray,
    source_values: np.ndarray,
    target_longitude_deg: np.ndarray,
) -> np.ndarray:
    if source_longitude_deg.size == 1:
        return np.broadcast_to(source_values[0], (target_longitude_deg.size, 3))
    longitude = np.concatenate((source_longitude_deg, [360.0]))
    values = np.vstack((source_values, source_values[0]))
    return np.column_stack(
        [
            np.interp(target_longitude_deg, longitude, values[:, axis])
            for axis in range(3)
        ]
    )


def _vector_rows(values: Any, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 1 and array.size == 3:
        array = array.reshape(1, 3)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(f"{name} must have shape (rows, 3)")
    return array


def _native_module() -> Any:
    failures: list[BaseException] = []
    for name in ("sopran._native", "sopran_native"):
        try:
            module = importlib.import_module(name)
        except (ImportError, ModuleNotFoundError) as exc:
            failures.append(exc)
            continue
        if hasattr(module, "trace_svm3d_shell_grid"):
            return module
    message = "The installed SOPRAN native extension does not provide the SVM3D backend"
    if failures:
        raise RuntimeError(message) from failures[-1]
    raise RuntimeError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentile(values: np.ndarray, percentile: float) -> float:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    return float(np.percentile(finite, percentile)) if finite.size else float("nan")


__all__ = [
    "MOON_MEAN_RADIUS_KM",
    "SVM3DShellGrid",
    "SVM3DTraceResult",
    "SVM3DTraceSettings",
    "cartesian_to_lon_lat_alt",
    "evaluate_tsunakawa_svm3d",
    "lon_lat_alt_to_cartesian",
]
