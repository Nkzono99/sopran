"""Satellite Observation Package for Retrieval, Analysis, and Navigation."""

from typing import TYPE_CHECKING, Any

from sopran.bodies import Moon
from sopran.core import (
    AlignmentResult,
    BackendError,
    ConfigError,
    Database,
    DatasetNotFoundError,
    DecodeError,
    DownloadError,
    EventCatalog,
    FeatureMatrix,
    FrameTransformError,
    GuidePage,
    InfoPage,
    InstrumentSchema,
    PipelineError,
    PlotArtifact,
    PlotItem,
    PlotOverlay,
    PlotPlan,
    PlotResult,
    PlotStack,
    ProductRef,
    QuicklookResult,
    ResampleLikeMethod,
    SampleSpec,
    SampleTable,
    SchemaError,
    SopranArray,
    SopranError,
    Store,
    TimeBins,
    TimeRange,
    VariableSchema,
    View,
    ViewContext,
    ViewSelection,
    align,
    day,
    histogram,
    line,
    lines,
    load,
    month,
    period,
    resample_like,
    spectrogram,
    stack,
    time_bins,
    validate_schema,
    view,
    year,
)
from sopran.core.project import Project
from sopran.frames import FrameContext, FrameTransformPlan, normalize_frame
from sopran.maps import RasterLayer, RasterSpec, Region
from sopran.missions.artemis import Artemis
from sopran.missions.kaguya import Kaguya

from . import config as config

if TYPE_CHECKING:
    artemis: Artemis
    kaguya: Kaguya
    moon: Moon

__version__ = "0.0.0"


def __getattr__(name: str) -> Any:
    if name in {"builtin_schemas", "schema_reference_markdown"}:
        from importlib import import_module

        return getattr(import_module("sopran.schema_docs"), name)
    if name in {"kaguya", "artemis", "moon"}:
        return getattr(Project.default().view(), name)
    raise AttributeError(f"module 'sopran' has no attribute {name!r}")

__all__ = [
    "GuidePage",
    "InfoPage",
    "AlignmentResult",
    "Artemis",
    "BackendError",
    "ConfigError",
    "config",
    "Database",
    "DatasetNotFoundError",
    "DecodeError",
    "DownloadError",
    "EventCatalog",
    "FrameTransformError",
    "FrameContext",
    "FrameTransformPlan",
    "FeatureMatrix",
    "InstrumentSchema",
    "Kaguya",
    "artemis",
    "kaguya",
    "moon",
    "Moon",
    "PlotArtifact",
    "PlotItem",
    "PlotOverlay",
    "PlotPlan",
    "PlotResult",
    "PlotStack",
    "Project",
    "PipelineError",
    "ProductRef",
    "QuicklookResult",
    "RasterLayer",
    "RasterSpec",
    "Region",
    "ResampleLikeMethod",
    "SampleSpec",
    "SampleTable",
    "SchemaError",
    "SopranArray",
    "SopranError",
    "Store",
    "TimeRange",
    "TimeBins",
    "VariableSchema",
    "View",
    "ViewContext",
    "ViewSelection",
    "__version__",
    "align",
    "builtin_schemas",
    "day",
    "histogram",
    "line",
    "lines",
    "load",
    "month",
    "normalize_frame",
    "period",
    "resample_like",
    "schema_reference_markdown",
    "spectrogram",
    "stack",
    "time_bins",
    "validate_schema",
    "view",
    "year",
]
