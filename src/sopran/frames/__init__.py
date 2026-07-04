from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast

from sopran.core.errors import FrameTransformError

_FRAME_ALIASES = {
    "GSE": "GSE",
    "GSM": "GSM",
    "MOON_ME": "MOON_ME",
    "MOONME": "MOON_ME",
    "SSE": "SSE",
}
_KNOWN_BACKENDS = ("spiceypy", "astropy", "spacepy")
_IMPLEMENTED_BACKENDS = ("identity", "spiceypy")
_PLANNED_BACKENDS = ("astropy", "spacepy")


@dataclass(frozen=True)
class FrameTransformPlan:
    source_frame: str
    target_frame: str
    backend: str
    time_scale: str
    spice_kernels: tuple[Path, ...] = ()
    status: str = "planned"

    def metadata(self) -> dict[str, Any]:
        return {
            "source_frame": self.source_frame,
            "target_frame": self.target_frame,
            "backend": self.backend,
            "time_scale": self.time_scale,
            "spice_kernels": [path.as_posix() for path in self.spice_kernels],
            "status": self.status,
            "backend_available": _backend_available(self.backend),
        }


@dataclass(frozen=True)
class FrameContext:
    """Coordinate-frame context for SOPRAN products.

    This is intentionally a thin adapter boundary. Kernel-backed and
    model-backed transforms are delegated to established libraries in later
    implementations; the current implementation records provenance and supports
    identity transforms.
    """

    spice_kernels: tuple[str | Path, ...] = ()
    time_scale: str = "utc"
    default_backend: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "spice_kernels",
            tuple(Path(path) for path in self.spice_kernels),
        )
        object.__setattr__(self, "time_scale", self.time_scale.lower())

    def metadata(self) -> dict[str, Any]:
        return {
            "time_scale": self.time_scale,
            "spice_kernels": [path.as_posix() for path in self._spice_kernels],
            "available_backends": _backend_versions(),
            "implemented_backends": _implemented_backend_versions(),
            "planned_backends": _planned_backend_versions(),
        }

    @property
    def _spice_kernels(self) -> tuple[Path, ...]:
        return cast(tuple[Path, ...], self.spice_kernels)

    def plan(
        self,
        source_frame: str,
        target_frame: str,
        *,
        backend: str | None = None,
    ) -> FrameTransformPlan:
        source = normalize_frame(source_frame)
        target = normalize_frame(target_frame)
        selected_backend = "identity" if source == target else backend or self.default_backend
        if selected_backend is None:
            selected_backend = _default_backend_for(source, target)
        return FrameTransformPlan(
            source_frame=source,
            target_frame=target,
            backend=selected_backend,
            time_scale=self.time_scale,
            spice_kernels=self._spice_kernels,
            status=_transform_plan_status(source, target, selected_backend),
        )

    def transform_array(
        self,
        array: Any,
        target_frame: str,
        *,
        source_frame: str | None = None,
        backend: str | None = None,
    ) -> Any:
        from sopran.core.data import SopranArray

        if not isinstance(array, SopranArray):
            raise TypeError("FrameContext.transform_array() expects a SopranArray")
        source = source_frame or array.schema.frame or _array_frame(array)
        if source is None:
            raise FrameTransformError(
                f"Source frame is required to transform {array.name} to {target_frame}"
            )
        plan = self.plan(source, target_frame, backend=backend)
        if plan.source_frame != plan.target_frame:
            return _vector_array_transform(array, self, plan, backend=backend)
        return _identity_transform(array, plan)

    def transform_vectors(
        self,
        vectors: Any,
        *,
        times: Any,
        source_frame: str,
        target_frame: str,
        backend: str | None = None,
    ) -> Any:
        """Transform one or more 3-D vectors between coordinate frames.

        Non-identity transforms are delegated to SPICE through spiceypy. SPICE
        kernels must already be supplied through ``FrameContext(spice_kernels=...)``.
        """

        import numpy as np

        source = normalize_frame(source_frame)
        target = normalize_frame(target_frame)
        arr = np.asarray(vectors, dtype=float)
        if arr.shape == (3,):
            input_was_vector = True
            flat = arr.reshape(1, 3)
        elif arr.ndim >= 2 and arr.shape[-1] == 3:
            input_was_vector = False
            flat = arr.reshape(-1, 3)
        else:
            raise ValueError("vectors must have shape (3,), (n, 3), or (..., 3)")

        if source == target:
            out = flat.copy().reshape(arr.shape)
            return out.reshape(3) if input_was_vector else out

        plan = self.plan(source, target, backend=backend)
        if plan.backend != "spiceypy":
            raise FrameTransformError(
                f"Frame transform requires a vector backend for {source} -> {target}; "
                f"selected backend is {plan.backend!r}"
            )

        time_values = _vector_transform_times(times, flat.shape[0])
        transformed = _transform_vectors_spice(flat, time_values, plan)
        out = transformed.reshape(arr.shape)
        return out.reshape(3) if input_was_vector else out


def normalize_frame(frame: str) -> str:
    normalized = str(frame).strip().replace("-", "_").replace(" ", "_").upper()
    return _FRAME_ALIASES.get(normalized, normalized)


def _identity_transform(array: Any, plan: FrameTransformPlan) -> Any:
    from sopran.core.data import SopranArray

    xr_array = array.to_xarray()
    transformed = xr_array.copy(deep=False) if hasattr(xr_array, "copy") else xr_array
    attrs = dict(getattr(transformed, "attrs", {}))
    attrs["frame"] = plan.target_frame
    attrs["frame_transform"] = plan.metadata()
    if hasattr(transformed, "attrs"):
        transformed.attrs = attrs
    return SopranArray(
        name=array.name,
        time=array.time,
        schema=replace(array.schema, frame=plan.target_frame),
        files=array.files,
        operations=(
            *array.operations,
            {
                "operation": "frame_transform",
                "parameters": plan.metadata(),
            },
        ),
        xr=transformed,
    )


def _vector_array_transform(
    array: Any,
    context: FrameContext,
    plan: FrameTransformPlan,
    *,
    backend: str | None,
) -> Any:
    from sopran.core.data import SopranArray

    if not isinstance(array, SopranArray):
        raise TypeError("FrameContext.transform_array() expects a SopranArray")
    xr_array = array.to_xarray()
    dims = tuple(getattr(xr_array, "dims", ()))
    if not dims or dims[-1] != "component":
        raise FrameTransformError(
            f"Frame transform is implemented only for vector arrays with a component axis: "
            f"{plan.source_frame} -> {plan.target_frame}"
        )
    values = getattr(xr_array, "values", None)
    value_shape = tuple(getattr(values, "shape", ()))
    if values is None or not value_shape or value_shape[-1] != 3:
        raise FrameTransformError(
            "Frame transform expects three vector components: "
            f"{plan.source_frame} -> {plan.target_frame}"
        )
    if "time" not in getattr(xr_array, "coords", {}):
        raise FrameTransformError(
            f"Frame transform requires time coordinates: {plan.source_frame} -> {plan.target_frame}"
        )
    transformed_values = context.transform_vectors(
        values,
        times=xr_array.coords["time"].values,
        source_frame=plan.source_frame,
        target_frame=plan.target_frame,
        backend=backend,
    )
    transformed = xr_array.copy(data=transformed_values)
    attrs = dict(getattr(transformed, "attrs", {}))
    attrs["frame"] = plan.target_frame
    attrs["frame_transform"] = plan.metadata()
    transformed.attrs = attrs
    return SopranArray(
        name=array.name,
        time=array.time,
        schema=replace(array.schema, frame=plan.target_frame),
        files=array.files,
        operations=(
            *array.operations,
            {
                "operation": "frame_transform",
                "parameters": plan.metadata(),
            },
        ),
        xr=transformed,
    )


def _array_frame(array: Any) -> str | None:
    try:
        attrs = getattr(array.to_xarray(), "attrs", {})
    except ValueError:
        return None
    frame = attrs.get("frame")
    return normalize_frame(str(frame)) if frame else None


def _backend_versions() -> dict[str, str | None]:
    return {name: _package_version(name) for name in _KNOWN_BACKENDS}


def _implemented_backend_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {"identity": "built-in"}
    versions.update({name: _package_version(name) for name in _IMPLEMENTED_BACKENDS[1:]})
    return versions


def _planned_backend_versions() -> dict[str, str | None]:
    return {name: _package_version(name) for name in _PLANNED_BACKENDS}


def _transform_plan_status(source_frame: str, target_frame: str, backend: str) -> str:
    if source_frame == target_frame:
        return "applied"
    if backend in _IMPLEMENTED_BACKENDS:
        return "implemented"
    if backend in _PLANNED_BACKENDS:
        return "planned"
    return "unavailable"


def _backend_available(backend: str) -> bool:
    if backend == "identity":
        return True
    if backend in _KNOWN_BACKENDS:
        return _package_version(backend) is not None
    return False


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _default_backend_for(source_frame: str, target_frame: str) -> str:
    geospace_frames = {"GSE", "GSM", "SM"}
    if source_frame in geospace_frames and target_frame in geospace_frames:
        return "spacepy"
    return "spiceypy"


def _vector_transform_times(times: Any, count: int) -> tuple[Any, ...]:
    if isinstance(times, str) or not hasattr(times, "__len__"):
        return tuple(times for _ in range(count))
    values = tuple(times)
    if len(values) == 1 and count != 1:
        return tuple(values[0] for _ in range(count))
    if len(values) != count:
        raise ValueError(f"times length {len(values)} does not match vector count {count}")
    return values


def _transform_vectors_spice(vectors: Any, times: tuple[Any, ...], plan: FrameTransformPlan) -> Any:
    import numpy as np

    try:
        import spiceypy
    except ImportError as exc:
        raise FrameTransformError(
            f"SPICE frame transform is unavailable for {plan.source_frame} -> {plan.target_frame}; "
            "install spiceypy and provide required kernels."
        ) from exc

    try:
        for kernel in plan.spice_kernels:
            spiceypy.furnsh(str(kernel))
        out = np.empty_like(vectors, dtype=float)
        for index, (vector, time_value) in enumerate(zip(vectors, times, strict=True)):
            et = spiceypy.utc2et(_time_to_utc_string(time_value))
            matrix = np.asarray(spiceypy.pxform(plan.source_frame, plan.target_frame, et))
            out[index, :] = matrix @ np.asarray(vector, dtype=float)
        return out
    except Exception as exc:
        raise FrameTransformError(
            f"SPICE frame transform failed for {plan.source_frame} -> {plan.target_frame}. "
            "Provide compatible SPICE kernels including time and frame kernels."
        ) from exc


def _time_to_utc_string(value: Any) -> str:
    import numpy as np

    if isinstance(value, np.datetime64):
        return np.datetime_as_string(value.astype("datetime64[ns]"), unit="ns") + " UTC"
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).replace(tzinfo=None).isoformat() + " UTC"
    if isinstance(value, (int, float, np.integer, np.floating)):
        timestamp = datetime.fromtimestamp(float(value), tz=UTC)
        return timestamp.replace(tzinfo=None).isoformat() + " UTC"
    text = str(value)
    return text if text.upper().endswith("UTC") else f"{text} UTC"


__all__ = [
    "FrameContext",
    "FrameTransformPlan",
    "normalize_frame",
]
