"""Satellite Observation Package for Retrieval, Analysis, and Navigation."""

from sopran.core import PlotItem, PlotPlan, PlotStack, Store, TimeRange, day, line, month, period
from sopran.core import spectrogram, stack, year
from sopran.core.project import Project
from sopran.missions.kaguya import Kaguya

__version__ = "0.0.0"

__all__ = [
    "Kaguya",
    "PlotItem",
    "PlotPlan",
    "PlotStack",
    "Project",
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
