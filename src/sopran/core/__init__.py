from sopran.core.alignment import (
    AlignmentResult,
    FeatureMatrix,
    SampleSpec,
    SampleTable,
    TimeBins,
    align,
    time_bins,
)
from sopran.core.data import SopranArray, rebin
from sopran.core.database import Database, ProductRef
from sopran.core.errors import (
    BackendError,
    ConfigError,
    DatasetNotFoundError,
    DecodeError,
    DownloadError,
    FrameTransformError,
    PipelineError,
    SchemaError,
    SopranError,
)
from sopran.core.events import EventCatalog
from sopran.core.loaders import load
from sopran.core.pages import GuidePage, InfoPage
from sopran.core.pipeline import Pipeline, PipelinePlan, PipelineResult, PipelineStage
from sopran.core.plotting import (
    PlotArtifact,
    PlotItem,
    PlotOverlay,
    PlotPlan,
    PlotResult,
    PlotStack,
    QuicklookResult,
    histogram,
    line,
    lines,
    spectrogram,
    stack,
)
from sopran.core.resampling import ResampleLikeMethod, resample_like
from sopran.core.schema import InstrumentSchema, VariableSchema, validate_schema
from sopran.core.store import Store
from sopran.core.time import TimeRange, day, month, period, year
from sopran.core.view import View, ViewContext, ViewSelection, view

__all__ = [
    "GuidePage",
    "InfoPage",
    "AlignmentResult",
    "BackendError",
    "ConfigError",
    "Database",
    "DatasetNotFoundError",
    "DecodeError",
    "DownloadError",
    "FrameTransformError",
    "FeatureMatrix",
    "EventCatalog",
    "InstrumentSchema",
    "Pipeline",
    "PipelineError",
    "PipelinePlan",
    "PipelineResult",
    "PipelineStage",
    "PlotArtifact",
    "PlotItem",
    "PlotOverlay",
    "PlotPlan",
    "PlotResult",
    "PlotStack",
    "QuicklookResult",
    "ResampleLikeMethod",
    "SampleSpec",
    "SampleTable",
    "SopranArray",
    "Store",
    "ProductRef",
    "SchemaError",
    "SopranError",
    "TimeRange",
    "TimeBins",
    "VariableSchema",
    "View",
    "ViewContext",
    "ViewSelection",
    "align",
    "day",
    "load",
    "line",
    "histogram",
    "lines",
    "month",
    "period",
    "rebin",
    "resample_like",
    "spectrogram",
    "stack",
    "time_bins",
    "validate_schema",
    "view",
    "year",
]
