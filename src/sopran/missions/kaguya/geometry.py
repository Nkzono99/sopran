from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np

from sopran.core.data import SopranArray
from sopran.core.errors import BackendError
from sopran.core.schema import VariableSchema
from sopran.core.time import TimeRange, spice_utc_string
from sopran.missions.kaguya.schema import (
    KAGUYA_LMAG_CONNECTION_SCHEMA,
    KAGUYA_ORBIT_SCHEMA,
)

MOON_MEAN_RADIUS_KM = 1737.4
ConnectionDirection = Literal["plus", "minus", "both"]


def lmag_position(data: Any) -> SopranArray:
    schema = KAGUYA_ORBIT_SCHEMA.variable("position")
    array = data.to_xarray()["position_moon_me"].rename(schema.name)
    array.attrs.update(
        {
            "units": schema.units,
            "frame": schema.frame,
            "description": schema.description,
        }
    )
    return SopranArray(
        name=schema.name,
        time=_require_time(data),
        schema=schema,
        files=data.files,
        xr=array,
    )


def lmag_position_gse(data: Any) -> SopranArray:
    schema = KAGUYA_ORBIT_SCHEMA.variable("position_gse")
    array = data.to_xarray()["position_gse"].rename(schema.name)
    array.attrs.update(
        {
            "units": schema.units,
            "frame": schema.frame,
            "description": schema.description,
        }
    )
    return SopranArray(
        name=schema.name,
        time=_require_time(data),
        schema=schema,
        files=data.files,
        xr=array,
    )


def lmag_radial_distance(data: Any) -> SopranArray:
    schema = KAGUYA_ORBIT_SCHEMA.variable("radial_distance")
    dataset = data.to_xarray()
    position = dataset["position_moon_me"].values.astype(float)
    radius = np.linalg.norm(position, axis=1)
    array = _data_array(
        radius,
        time=dataset.coords["time"].values,
        name=schema.name,
        attrs={
            "units": schema.units,
            "frame": schema.frame,
            "description": schema.description,
        },
    )
    return SopranArray(
        name=schema.name,
        time=_require_time(data),
        schema=schema,
        files=data.files,
        xr=array,
    )


def lmag_altitude(
    data: Any,
    *,
    radius_km: float = MOON_MEAN_RADIUS_KM,
) -> SopranArray:
    schema = KAGUYA_ORBIT_SCHEMA.variable("altitude")
    dataset = data.to_xarray()
    position = dataset["position_moon_me"].values.astype(float)
    altitude = np.linalg.norm(position, axis=1) - float(radius_km)
    array = _data_array(
        altitude,
        time=dataset.coords["time"].values,
        name=schema.name,
        attrs={
            "units": schema.units,
            "frame": schema.frame,
            "description": schema.description,
            "radius_km": float(radius_km),
        },
    )
    return SopranArray(
        name=schema.name,
        time=_require_time(data),
        schema=schema,
        files=data.files,
        xr=array,
    )


def lmag_subpoint(data: Any) -> SopranArray:
    schema = KAGUYA_ORBIT_SCHEMA.variable("subpoint")
    dataset = data.to_xarray()
    position = dataset["position_moon_me"].values.astype(float)
    lon, lat = _lon_lat(position)
    values = np.column_stack((lon, lat))
    array = _data_array(
        values,
        time=dataset.coords["time"].values,
        name=schema.name,
        component=("lon", "lat"),
        attrs={
            "units": schema.units,
            "frame": schema.frame,
            "description": schema.description,
        },
    )
    return SopranArray(
        name=schema.name,
        time=_require_time(data),
        schema=schema,
        files=data.files,
        xr=array,
    )


def lmag_sza(
    data: Any,
    *,
    sun_vector: Any | None = None,
    sun_frame: str = "MOON_ME",
    context: Any | None = None,
    backend: str | None = None,
    spice_kernels: tuple[str | Path, ...] = (),
) -> SopranArray:
    schema = KAGUYA_ORBIT_SCHEMA.variable("sza")
    dataset = data.to_xarray()
    position = dataset["position_moon_me"].values.astype(float)
    times = dataset.coords["time"].values
    if sun_vector is None:
        sun_vectors = spice_sun_vectors_moon_me(
            times,
            context=context,
            backend=backend,
            spice_kernels=spice_kernels,
        )
        sun_source = "spice"
        sun_frame = "MOON_ME"
        sun_vector_shape = list(sun_vectors.shape)
    else:
        sun_vectors = _sun_vectors_moon_me(
            sun_vector,
            sun_frame=sun_frame,
            context=context,
            backend=backend,
            times=times,
            count=position.shape[0],
        )
        sun_source = "explicit"
        sun_vector_shape = list(np.asarray(sun_vector, dtype=float).shape)
    position_norm = np.linalg.norm(position, axis=1)
    normal = np.divide(
        position,
        position_norm[:, None],
        out=np.full_like(position, np.nan, dtype=float),
        where=position_norm[:, None] != 0,
    )
    sun_norm = np.linalg.norm(sun_vectors, axis=1)
    sun_direction = np.divide(
        sun_vectors,
        sun_norm[:, None],
        out=np.full_like(sun_vectors, np.nan, dtype=float),
        where=sun_norm[:, None] != 0,
    )
    cos_sza = np.sum(normal * sun_direction, axis=1)
    sza = np.degrees(np.arccos(np.clip(cos_sza, -1.0, 1.0)))
    array = _data_array(
        sza,
        time=times,
        name=schema.name,
        attrs={
            "units": schema.units,
            "frame": schema.frame,
            "description": schema.description,
            "sun_frame": sun_frame,
            "sun_source": sun_source,
            "sun_vector_shape": sun_vector_shape,
        },
    )
    return SopranArray(
        name=schema.name,
        time=_require_time(data),
        schema=schema,
        files=data.files,
        xr=array,
    )


def lmag_magnetic_connection(
    data: Any,
    *,
    radius_km: float = MOON_MEAN_RADIUS_KM,
    direction: ConnectionDirection = "both",
) -> KaguyaMagneticConnectionData:
    _validate_direction(direction)
    dataset = data.to_xarray()
    position = dataset["position_moon_me"].values.astype(float)
    magnetic_field = dataset["magnetic_field_moon_me"].values.astype(float)
    times = dataset.coords["time"].values
    rows = []
    for time_value, r_vector, b_vector in zip(
        times,
        position,
        magnetic_field,
        strict=True,
    ):
        plus = _intersection(r_vector, b_vector, radius_km=radius_km, sign=1.0)
        minus = _intersection(r_vector, b_vector, radius_km=radius_km, sign=-1.0)
        altitude = float(np.linalg.norm(r_vector) - radius_km)
        rows.append(
            _connection_row(
                time_value,
                plus=plus,
                minus=minus,
                altitude=altitude,
                direction=direction,
            )
        )
    return KaguyaMagneticConnectionData(
        rows=tuple(rows),
        time=_require_time(data),
        files=data.files,
        radius_km=float(radius_km),
        direction=direction,
    )


@dataclass(frozen=True)
class KaguyaMagneticConnectionData:
    rows: tuple[dict[str, Any], ...]
    time: TimeRange
    files: tuple[Path, ...] = ()
    radius_km: float = MOON_MEAN_RADIUS_KM
    direction: ConnectionDirection = "both"

    def to_polars(self) -> Any:
        import polars as pl

        if not self.rows:
            return pl.DataFrame({column: [] for column in _connection_columns(self.direction)})
        return pl.DataFrame(list(self.rows))

    def to_pandas(self) -> Any:
        return self.to_polars().to_pandas()

    def to_xarray(self) -> Any:
        import pandas as pd
        import xarray as xr

        frame = self.to_pandas()
        time_values = (
            pd.to_datetime(frame["time"], utc=True)
            .dt.tz_convert(None)
            .to_numpy(dtype="datetime64[ns]")
        )
        data_vars = {
            column: (("time",), frame[column].to_numpy())
            for column in frame.columns
            if column != "time"
        }
        return xr.Dataset(
            data_vars=data_vars,
            coords={"time": time_values},
            attrs={
                "mission": "kaguya",
                "instrument": "lmag",
                "product": "magnetic_connection",
                "radius_km": self.radius_km,
                "direction": self.direction,
                "field_model": "straight_local_field_line",
                "surface": "sphere",
            },
        )

    def resample_like(
        self,
        target: Any,
        *,
        method: str = "nearest",
        tolerance: str | None = None,
        time: str = "time",
    ) -> KaguyaMagneticConnectionData:
        from sopran.core.resampling import resample_like

        dataset = resample_like(
            self.to_xarray(),
            target,
            method=method,  # type: ignore[arg-type]
            tolerance=tolerance,
            time=time,
        )
        frame = dataset.to_dataframe().reset_index()
        return KaguyaMagneticConnectionData.from_pandas(
            frame,
            time_range=_target_time_range(target, fallback=self.time, time=time),
            files=self.files,
            radius_km=self.radius_km,
            direction=self.direction,
        )

    def plot(
        self,
        *,
        kind: Literal["footpoint", "altitude", "distance", "incidence"] = "footpoint",
    ) -> Any:
        import matplotlib.pyplot as plt

        frame = self.to_pandas()
        if kind == "footpoint":
            fig, ax = plt.subplots()
            if {"footpoint_plus_lon", "footpoint_plus_lat"} <= set(frame.columns):
                ax.scatter(
                    frame["footpoint_plus_lon"],
                    frame["footpoint_plus_lat"],
                    label="plus",
                )
            if {"footpoint_minus_lon", "footpoint_minus_lat"} <= set(frame.columns):
                ax.scatter(
                    frame["footpoint_minus_lon"],
                    frame["footpoint_minus_lat"],
                    label="minus",
                )
            ax.set_xlabel("lon [deg]")
            ax.set_ylabel("lat [deg]")
            if ax.get_legend_handles_labels()[0]:
                ax.legend()
            return fig
        if kind == "altitude":
            fig, ax = plt.subplots()
            ax.plot(frame["time"], frame["altitude_km"])
            ax.set_xlabel("time")
            ax.set_ylabel("altitude [km]")
            return fig
        if kind == "distance":
            fig, ax = plt.subplots()
            _plot_connection_columns(
                ax,
                frame,
                plus_column="distance_plus_km",
                minus_column="distance_minus_km",
            )
            ax.set_xlabel("time")
            ax.set_ylabel("distance [km]")
            return fig
        if kind == "incidence":
            fig, ax = plt.subplots()
            _plot_connection_columns(
                ax,
                frame,
                plus_column="incidence_angle_plus_deg",
                minus_column="incidence_angle_minus_deg",
            )
            ax.set_xlabel("time")
            ax.set_ylabel("incidence angle [deg]")
            return fig
        raise ValueError("kind must be 'footpoint', 'altitude', 'distance', or 'incidence'")

    @classmethod
    def from_polars(
        cls,
        frame: Any,
        *,
        time_range: TimeRange,
        files: tuple[Path, ...] = (),
        radius_km: float = MOON_MEAN_RADIUS_KM,
        direction: ConnectionDirection = "both",
    ) -> KaguyaMagneticConnectionData:
        return cls.from_pandas(
            frame.to_pandas(),
            time_range=time_range,
            files=files,
            radius_km=radius_km,
            direction=direction,
        )

    @classmethod
    def from_pandas(
        cls,
        frame: Any,
        *,
        time_range: TimeRange,
        files: tuple[Path, ...] = (),
        radius_km: float = MOON_MEAN_RADIUS_KM,
        direction: ConnectionDirection = "both",
    ) -> KaguyaMagneticConnectionData:
        frame = _with_connected_any(frame)
        rows = tuple(
            {
                str(key): _none_if_nan(value)
                for key, value in row.items()
            }
            for row in frame.to_dict(orient="records")
        )
        return cls(
            rows=rows,
            time=time_range,
            files=files,
            radius_km=radius_km,
            direction=direction,
        )


def _with_connected_any(frame: Any) -> Any:
    if "connected_any" in frame.columns:
        return frame
    frame = frame.copy()
    connected = None
    for column in ("connected_plus", "connected_minus"):
        if column not in frame.columns:
            continue
        values = frame[column].fillna(False).astype(bool)
        connected = values if connected is None else (connected | values)
    if connected is None:
        connected = [False] * len(frame)
    insert_at = 1 if "time" in frame.columns else len(frame.columns)
    frame.insert(insert_at, "connected_any", connected)
    return frame


@dataclass(frozen=True)
class _Intersection:
    connected: bool
    lon: float | None
    lat: float | None
    distance_km: float | None
    incidence_angle_deg: float | None


def array_from_polars(
    frame: Any,
    *,
    schema: VariableSchema,
    time_range: TimeRange,
    files: tuple[Path, ...] = (),
) -> SopranArray:
    import xarray as xr

    pandas = frame.to_pandas()
    time_values = pandas["time"].to_numpy(dtype="datetime64[ns]")
    if schema.dims == ("time",):
        array = xr.DataArray(
            pandas[schema.name].to_numpy(),
            dims=("time",),
            coords={"time": time_values},
            name=schema.name,
            attrs=_schema_attrs(schema),
        )
    elif schema.dims == ("time", "component"):
        components = _components_for(schema.name)
        pivoted = pandas.pivot(index="time", columns="component", values=schema.name)
        pivoted = pivoted.reindex(columns=components)
        time_values = pivoted.index.to_numpy(dtype="datetime64[ns]")
        values = pivoted.to_numpy()
        array = xr.DataArray(
            values,
            dims=("time", "component"),
            coords={"time": time_values, "component": list(components)},
            name=schema.name,
            attrs=_schema_attrs(schema),
        )
    else:
        raise ValueError(f"Unsupported cached geometry dims: {schema.dims}")
    return SopranArray(
        name=schema.name,
        time=time_range,
        schema=schema,
        files=files,
        xr=array,
    )


def connection_variant_id(
    *,
    radius_km: float,
    direction: ConnectionDirection,
) -> str:
    return f"sphere_r{_number_token(radius_km)}_moon_me_{direction}_v1"


def orbit_variant_id(
    name: str,
    *,
    radius_km: float = MOON_MEAN_RADIUS_KM,
    sun_vector: Any | None = None,
    sun_frame: str = "MOON_ME",
    context: Any | None = None,
    backend: str | None = None,
    spice_kernels: tuple[str | Path, ...] = (),
) -> str:
    if name == "position":
        return "lmag_moon_me_v1"
    if name == "position_gse":
        return "lmag_gse_v1"
    if name == "radial_distance":
        return "lmag_radial_distance_moon_me_v1"
    if name == "subpoint":
        return "sphere_lonlat_moon_me_v1"
    if name == "altitude":
        return f"sphere_r{_number_token(radius_km)}_moon_me_v1"
    if name == "sza":
        if sun_vector is None:
            return (
                "sphere_sza_spice_"
                f"{_path_tuple_token(spice_kernels)}_"
                f"{_transform_token(context=context, backend=backend)}_moon_me_v1"
            )
        return (
            f"sphere_sza_sun_{_frame_token(sun_frame)}_"
            f"{_array_token(sun_vector)}_"
            f"{_transform_token(context=context, backend=backend)}_moon_me_v1"
        )
    raise ValueError(f"Unknown orbit product: {name}")


def variant_metadata(
    *,
    radius_km: float = MOON_MEAN_RADIUS_KM,
    direction: ConnectionDirection | None = None,
    sun_vector: Any | None = None,
    sun_frame: str | None = None,
    context: Any | None = None,
    backend: str | None = None,
    spice_kernels: tuple[str | Path, ...] = (),
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source": "kaguya.lmag.public",
        "frame": "MOON_ME",
        "surface": "sphere",
        "radius_km": float(radius_km),
    }
    if direction is not None:
        metadata["direction"] = direction
        metadata["field_model"] = "straight_local_field_line"
    if sun_vector is not None:
        metadata["sun_source"] = "explicit"
        metadata["sun_frame"] = sun_frame or "MOON_ME"
        metadata["sun_vector_shape"] = list(np.asarray(sun_vector, dtype=float).shape)
        metadata["sun_vector_hash"] = _array_token(sun_vector)
        metadata["sun_transform"] = _transform_metadata(context=context, backend=backend)
    elif sun_frame is not None:
        metadata["sun_source"] = "spice"
        metadata["sun_frame"] = "MOON_ME"
        metadata["spice_kernels"] = [Path(path).as_posix() for path in spice_kernels]
        metadata["sun_transform"] = _transform_metadata(context=context, backend=backend)
    return metadata


def _connection_row(
    time_value: Any,
    *,
    plus: _Intersection,
    minus: _Intersection,
    altitude: float,
    direction: ConnectionDirection,
) -> dict[str, Any]:
    connected_any = False
    if direction in {"plus", "both"}:
        connected_any = connected_any or plus.connected
    if direction in {"minus", "both"}:
        connected_any = connected_any or minus.connected
    row: dict[str, Any] = {"time": _time_iso(time_value), "connected_any": connected_any}
    if direction in {"plus", "both"}:
        row.update(
            {
                "connected_plus": plus.connected,
                "footpoint_plus_lon": plus.lon,
                "footpoint_plus_lat": plus.lat,
                "distance_plus_km": plus.distance_km,
                "incidence_angle_plus_deg": plus.incidence_angle_deg,
            }
        )
    if direction in {"minus", "both"}:
        row.update(
            {
                "connected_minus": minus.connected,
                "footpoint_minus_lon": minus.lon,
                "footpoint_minus_lat": minus.lat,
                "distance_minus_km": minus.distance_km,
                "incidence_angle_minus_deg": minus.incidence_angle_deg,
            }
        )
    row["altitude_km"] = altitude
    return row


def _connection_columns(direction: ConnectionDirection) -> tuple[str, ...]:
    columns = ["time", "connected_any"]
    if direction in {"plus", "both"}:
        columns.extend(
            (
                "connected_plus",
                "footpoint_plus_lon",
                "footpoint_plus_lat",
                "distance_plus_km",
                "incidence_angle_plus_deg",
            )
        )
    if direction in {"minus", "both"}:
        columns.extend(
            (
                "connected_minus",
                "footpoint_minus_lon",
                "footpoint_minus_lat",
                "distance_minus_km",
                "incidence_angle_minus_deg",
            )
        )
    columns.append("altitude_km")
    return tuple(columns)


def _plot_connection_columns(
    axis: Any,
    frame: Any,
    *,
    plus_column: str,
    minus_column: str,
) -> None:
    if plus_column in frame.columns:
        axis.plot(frame["time"], frame[plus_column], label="plus")
    if minus_column in frame.columns:
        axis.plot(frame["time"], frame[minus_column], label="minus")
    if axis.get_legend_handles_labels()[0]:
        axis.legend()


def _intersection(
    r_vector: np.ndarray,
    b_vector: np.ndarray,
    *,
    radius_km: float,
    sign: float,
) -> _Intersection:
    if not np.all(np.isfinite(r_vector)) or not np.all(np.isfinite(b_vector)):
        return _missing_intersection()
    norm_b = float(np.linalg.norm(b_vector))
    if norm_b == 0:
        return _missing_intersection()
    direction = sign * b_vector / norm_b
    b_term = 2.0 * float(np.dot(r_vector, direction))
    c_term = float(np.dot(r_vector, r_vector) - radius_km**2)
    discriminant = b_term**2 - 4.0 * c_term
    if discriminant < 0:
        return _missing_intersection()
    roots = [
        (-b_term - np.sqrt(discriminant)) / 2.0,
        (-b_term + np.sqrt(discriminant)) / 2.0,
    ]
    candidates = [float(root) for root in roots if root >= 0]
    if not candidates:
        return _missing_intersection()
    distance = min(candidates)
    footpoint = r_vector + distance * direction
    lon, lat = _lon_lat(footpoint.reshape(1, 3))
    normal = footpoint / np.linalg.norm(footpoint)
    angle = np.degrees(np.arccos(np.clip(abs(float(np.dot(direction, normal))), 0, 1)))
    return _Intersection(
        connected=True,
        lon=float(lon[0]),
        lat=float(lat[0]),
        distance_km=distance,
        incidence_angle_deg=float(angle),
    )


def _missing_intersection() -> _Intersection:
    return _Intersection(
        connected=False,
        lon=None,
        lat=None,
        distance_km=None,
        incidence_angle_deg=None,
    )


def _lon_lat(position: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    radius = np.linalg.norm(position, axis=1)
    lon = np.degrees(np.arctan2(position[:, 1], position[:, 0]))
    lat = np.degrees(
        np.arcsin(
            np.divide(
                position[:, 2],
                radius,
                out=np.full_like(radius, np.nan, dtype=float),
                where=radius != 0,
            )
        )
    )
    lon = np.where(radius == 0, np.nan, lon)
    return lon, lat


def _sun_vectors_moon_me(
    sun_vector: Any,
    *,
    sun_frame: str,
    context: Any | None,
    backend: str | None,
    times: Any,
    count: int,
) -> np.ndarray:
    from sopran.frames import FrameContext, normalize_frame

    vectors = np.asarray(sun_vector, dtype=float)
    if vectors.shape == (3,):
        vectors = np.broadcast_to(vectors[None, :], (count, 3)).astype(float).copy()
    elif vectors.shape == (count, 3):
        vectors = vectors.astype(float, copy=True)
    else:
        raise ValueError("sun_vector must have shape (3,) or (time, 3)")
    source_frame = normalize_frame(sun_frame)
    if source_frame == "MOON_ME":
        return vectors
    frame_context = context if context is not None else FrameContext()
    return np.asarray(
        frame_context.transform_vectors(
            vectors,
            times=times,
            source_frame=source_frame,
            target_frame="MOON_ME",
            backend=backend,
        ),
        dtype=float,
    )


def spice_sun_vectors_moon_me(
    times: Any,
    *,
    context: Any | None = None,
    backend: str | None = None,
    spice_kernels: tuple[str | Path, ...] = (),
) -> np.ndarray:
    if backend not in {None, "spiceypy"}:
        raise BackendError(f"KAGUYA orbit sza SPICE backend does not support {backend!r}")
    try:
        import spiceypy
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise BackendError(
            "spiceypy is required for KAGUYA orbit sza when sun_vector is omitted. "
            'Install SPICE support and provide kernels, or pass sun_vector=... explicitly.'
        ) from exc

    kernel_paths = _spice_kernel_paths(spice_kernels, context=context)
    time_values = np.asarray(times).reshape(-1)
    vectors = np.full((time_values.size, 3), np.nan, dtype=float)
    try:
        for kernel in kernel_paths:
            spiceypy.furnsh(str(kernel))
        for index, time_value in enumerate(time_values):
            et = float(spiceypy.utc2et(_time_to_utc_string(time_value)))
            position, _light_time = spiceypy.spkpos(
                "SUN",
                et,
                "MOON_ME",
                "LT+S",
                "MOON",
            )
            vectors[index] = _normalize_vector(np.asarray(position, dtype=float))
    except Exception as exc:
        raise BackendError(
            "SPICE-backed KAGUYA orbit sza failed. Provide compatible leapsecond, "
            "planetary ephemeris, and Moon body-fixed frame kernels, or pass "
            "sun_vector=... explicitly."
        ) from exc
    return vectors


def _data_array(
    values: np.ndarray,
    *,
    time: Any,
    name: str,
    component: tuple[str, ...] | None = None,
    attrs: dict[str, Any] | None = None,
) -> Any:
    import xarray as xr

    if component is None:
        return xr.DataArray(
            values,
            dims=("time",),
            coords={"time": time},
            name=name,
            attrs=attrs or {},
        )
    return xr.DataArray(
        values,
        dims=("time", "component"),
        coords={"time": time, "component": list(component)},
        name=name,
        attrs=attrs or {},
    )


def _components_for(name: str) -> tuple[str, ...]:
    if name in {"position", "position_gse"}:
        return ("x", "y", "z")
    if name == "subpoint":
        return ("lon", "lat")
    raise ValueError(f"No component labels for {name}")


def _schema_attrs(schema: VariableSchema) -> dict[str, Any]:
    attrs: dict[str, Any] = {"description": schema.description}
    if schema.units is not None:
        attrs["units"] = schema.units
    if schema.frame is not None:
        attrs["frame"] = schema.frame
    return attrs


def _validate_direction(direction: str) -> None:
    if direction not in {"plus", "minus", "both"}:
        raise ValueError("direction must be 'plus', 'minus', or 'both'")


def _number_token(value: float) -> str:
    return f"{value:g}".replace(".", "_")


def _frame_token(value: str) -> str:
    return "".join(
        character.lower() if character.isalnum() else "_"
        for character in str(value).strip()
    ).strip("_")


def _array_token(value: Any) -> str:
    array = np.asarray(value, dtype=float)
    digest = sha256()
    digest.update(str(array.shape).encode("ascii"))
    digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()[:12]


def _path_tuple_token(paths: tuple[str | Path, ...]) -> str:
    encoded = json.dumps([Path(path).as_posix() for path in paths], sort_keys=True).encode(
        "utf-8"
    )
    return sha256(encoded).hexdigest()[:12]


def _transform_token(*, context: Any | None, backend: str | None) -> str:
    payload = _transform_metadata(context=context, backend=backend)
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return sha256(encoded).hexdigest()[:12]


def _transform_metadata(*, context: Any | None, backend: str | None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"backend": backend}
    if context is None:
        metadata["context"] = None
        return metadata
    context_metadata = getattr(context, "metadata", None)
    if callable(context_metadata):
        metadata["context"] = context_metadata()
    else:
        metadata["context"] = {
            "type": f"{type(context).__module__}.{type(context).__qualname__}"
        }
    return metadata


def _none_if_nan(value: Any) -> Any:
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.datetime64):
        return value
    if isinstance(value, datetime):
        return value
    return value


def _spice_kernel_paths(
    spice_kernels: tuple[str | Path, ...],
    *,
    context: Any | None,
) -> tuple[Path, ...]:
    if spice_kernels:
        return tuple(Path(path) for path in spice_kernels)
    context_kernels = getattr(context, "_spice_kernels", ())
    return tuple(Path(path) for path in context_kernels)


def _normalize_vector(vector: np.ndarray) -> np.ndarray:
    if vector.shape != (3,):
        raise ValueError("SPICE Sun vector must have shape (3,)")
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm == 0.0:
        raise ValueError("SPICE Sun vector must be finite and non-zero")
    return vector / norm


def _time_to_utc_string(value: Any) -> str:
    return spice_utc_string(value)


def _target_time_range(target: Any, *, fallback: TimeRange, time: str = "time") -> TimeRange:
    target_time = getattr(target, "time", None)
    if isinstance(target_time, TimeRange):
        return target_time
    try:
        values = _target_time_values(target, time=time)
    except (TypeError, ValueError):
        return fallback
    try:
        import pandas as pd

        normalized = (
            pd.DatetimeIndex(pd.to_datetime(values, utc=True))
            .tz_convert(None)
            .astype("datetime64[ns]")
        )
    except Exception:
        return fallback
    if len(normalized) == 0:
        return fallback
    start = pd.Timestamp(normalized.min()).tz_localize("UTC").to_pydatetime()
    stop = pd.Timestamp(normalized.max()).tz_localize("UTC").to_pydatetime()
    return TimeRange(start, max(stop, start) + timedelta(microseconds=1))


def _target_time_values(target: Any, *, time: str) -> Any:
    if hasattr(target, "coords"):
        coords = getattr(target, "coords", {})
        if time not in coords:
            raise ValueError(f"target has no {time!r} coordinate")
        return coords[time].values
    if _is_polars_frame(target):
        if time not in _polars_columns(target):
            raise ValueError(f"target has no {time!r} column")
        return _polars_select_series(target, time).to_list()
    if hasattr(target, "columns"):
        if time not in target.columns:
            raise ValueError(f"target has no {time!r} column")
        return target[time]
    if hasattr(target, "to_xarray"):
        array = target.to_xarray()
        if time not in array.coords:
            raise ValueError(f"target has no {time!r} coordinate")
        return array.coords[time].values
    raise TypeError("target must expose a time coordinate or time column")


def _is_polars_frame(value: Any) -> bool:
    return value.__class__.__module__.startswith("polars") and value.__class__.__name__ in {
        "DataFrame",
        "LazyFrame",
    }


def _polars_columns(value: Any) -> list[str]:
    collect_schema = getattr(value, "collect_schema", None)
    if callable(collect_schema):
        return [str(name) for name in collect_schema().names()]
    return [str(name) for name in value.columns]


def _polars_select_series(value: Any, column: str) -> Any:
    selected = value.select(column)
    collect = getattr(selected, "collect", None)
    if callable(collect):
        selected = collect()
    return selected.to_series()


def _time_iso(value: Any) -> str:
    timestamp = np.datetime64(value, "ns")
    seconds = timestamp.astype("datetime64[s]").astype("datetime64[ns]")
    micros = timestamp.astype("datetime64[us]").astype("datetime64[ns]")
    if timestamp == seconds:
        unit: Literal["s", "us", "ns"] = "s"
    elif timestamp == micros:
        unit = "us"
    else:
        unit = "ns"
    return f"{np.datetime_as_string(timestamp, unit=unit)}Z"


def _require_time(data: Any) -> TimeRange:
    if data.time is None:
        raise ValueError("KAGUYA LMAG geometry requires a TimeRange")
    return cast(TimeRange, data.time)


def connection_schema() -> Any:
    return KAGUYA_LMAG_CONNECTION_SCHEMA
