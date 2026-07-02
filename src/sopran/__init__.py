"""Satellite Observation Package for Retrieval, Analysis, and Navigation."""

from sopran.core import Store
from sopran.missions.kaguya import Kaguya

__version__ = "0.0.0"

__all__ = ["Kaguya", "Store", "__version__"]
