"""Satellite Observation Package for Retrieval, Analysis, and Navigation."""

from sopran.bodies import Moon
from sopran.core import GuidePage, InfoPage, PlotItem, PlotPlan, PlotStack, Store, TimeRange
from sopran.core import day, line, month, period
from sopran.maps import Region
from sopran.core import spectrogram, stack, year
from sopran.core.project import Project
from sopran.missions.kaguya import Kaguya

__version__ = "0.0.0"

__all__ = [
    "GuidePage",
    "InfoPage",
    "Kaguya",
    "Moon",
    "PlotItem",
    "PlotPlan",
    "PlotStack",
    "Project",
    "Region",
    "Store",
    "TimeRange",
    "__version__",
    "day",
    "line",
    "month",
    "period",
    "spectrogram",
    "stack",
    "year",
]
