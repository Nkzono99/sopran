from __future__ import annotations

from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from sopran.core.errors import FrameTransformError

_FRAME_ALIASES = {
    "GSE": "GSE",
    "GSM": "GSM",
    "MOON_ME": "MOON_ME",
    "MOONME": "MOON_ME",
    "SSE": "SSE",
}
_KNOWN_BACKENDS = ("spiceypy", "astropy", "spacepy")


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
            "spice_kernels": [path.as_posix() for path in self.spice_kernels],
            "available_backends": _backend_versions(),
        }

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
            spice_kernels=self.spice_kernels,
            status="applied" if source == target else "planned",
        )

    def transform_array(
        self,
        array: Any,
        target_frame: str,
        *,
        source_frame: str | None = None,
        backend: str | None = None,
    ):
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
            raise FrameTransformError(
                "Frame transform is not implemented yet: "
                f"{plan.source_frame} -> {plan.target_frame} "
                f"(backend={plan.backend})"
            )
        return _identity_transform(array, plan)


def normalize_frame(frame: str) -> str:
    normalized = str(frame).strip().replace("-", "_").replace(" ", "_").upper()
    return _FRAME_ALIASES.get(normalized, normalized)


def _identity_transform(array: Any, plan: FrameTransformPlan):
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


def _array_frame(array: Any) -> str | None:
    try:
        attrs = getattr(array.to_xarray(), "attrs", {})
    except ValueError:
        return None
    frame = attrs.get("frame")
    return normalize_frame(str(frame)) if frame else None


def _backend_versions() -> dict[str, str | None]:
    return {name: _package_version(name) for name in _KNOWN_BACKENDS}


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


__all__ = [
    "FrameContext",
    "FrameTransformPlan",
    "normalize_frame",
]
