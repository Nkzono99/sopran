"""Satellite Observation Package for Retrieval, Analysis, and Navigation."""

from sopran.bodies import Moon
from sopran.core import Database, DatasetNotFoundError, GuidePage, InfoPage
from sopran.core import PlotItem, PlotPlan, ProductRef
from sopran.core import PlotStack, SopranError, Store, TimeRange
from sopran.core import day, line, load, month, period
from sopran.core import spectrogram, stack, year
from sopran.core.project import Project
from sopran.maps import Region
from sopran.missions.artemis import Artemis
from sopran.missions.kaguya import Kaguya

__version__ = "0.0.0"

__all__ = [
    "GuidePage",
    "InfoPage",
    "Artemis",
    "Database",
    "DatasetNotFoundError",
    "Kaguya",
    "Moon",
    "PlotItem",
    "PlotPlan",
    "PlotStack",
    "Project",
    "ProductRef",
    "Region",
    "SopranError",
    "Store",
    "TimeRange",
    "__version__",
    "day",
    "line",
    "load",
    "month",
    "period",
    "spectrogram",
    "stack",
    "year",
]
