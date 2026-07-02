"""Satellite Observation Package for Retrieval, Analysis, and Navigation."""

from sopran.bodies import Moon
from sopran.core import AlignmentResult
from sopran.core import BackendError, ConfigError, DecodeError, DownloadError
from sopran.core import Database, DatasetNotFoundError, GuidePage, InfoPage
from sopran.core import FrameTransformError, PipelineError, SchemaError
from sopran.core import InstrumentSchema, VariableSchema
from sopran.core import PlotArtifact, PlotItem, PlotPlan, ProductRef
from sopran.core import PlotStack, SampleSpec, SampleTable, SopranError, Store, TimeRange
from sopran.core import QuicklookResult
from sopran.core import TimeBins, align, day, line, load, month, period
from sopran.core import spectrogram, stack, year
from sopran.core import time_bins
from sopran.core import validate_schema
from sopran.core.project import Project
from sopran.maps import Region
from sopran.missions.artemis import Artemis
from sopran.missions.kaguya import Kaguya

__version__ = "0.0.0"


def __getattr__(name: str):
    if name in {"builtin_schemas", "schema_reference_markdown"}:
        from importlib import import_module

        return getattr(import_module("sopran.schema_docs"), name)
    raise AttributeError(f"module 'sopran' has no attribute {name!r}")

__all__ = [
    "GuidePage",
    "InfoPage",
    "AlignmentResult",
    "Artemis",
    "BackendError",
    "ConfigError",
    "Database",
    "DatasetNotFoundError",
    "DecodeError",
    "DownloadError",
    "FrameTransformError",
    "InstrumentSchema",
    "Kaguya",
    "Moon",
    "PlotArtifact",
    "PlotItem",
    "PlotPlan",
    "PlotStack",
    "Project",
    "PipelineError",
    "ProductRef",
    "QuicklookResult",
    "Region",
    "SampleSpec",
    "SampleTable",
    "SchemaError",
    "SopranError",
    "Store",
    "TimeRange",
    "TimeBins",
    "VariableSchema",
    "__version__",
    "align",
    "builtin_schemas",
    "day",
    "line",
    "load",
    "month",
    "period",
    "schema_reference_markdown",
    "spectrogram",
    "stack",
    "time_bins",
    "validate_schema",
    "year",
]
