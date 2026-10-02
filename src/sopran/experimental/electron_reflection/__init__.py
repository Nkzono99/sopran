"""Opt-in finite-bin and Halekas electron-reflectometry estimators."""

from sopran.experimental.electron_reflection.common import (
    ElectronReflectionCounts,
    mirror_boundary_sin2,
)
from sopran.experimental.electron_reflection.finite_bin import (
    AngularTransport,
    FiniteBinFit,
    FiniteBinFitSettings,
    FiniteBinLoss,
    FiniteBinModel,
    FiniteBinObservation,
    FiniteBinParameters,
    fit_finite_bin_distribution,
)
from sopran.experimental.electron_reflection.halekas import (
    HalekasDistributionFit,
    HalekasEdgeTransition,
    HalekasFitSettings,
    fit_halekas_distribution,
)

__all__ = [
    "AngularTransport",
    "ElectronReflectionCounts",
    "FiniteBinFit",
    "FiniteBinFitSettings",
    "FiniteBinLoss",
    "FiniteBinModel",
    "FiniteBinObservation",
    "FiniteBinParameters",
    "HalekasDistributionFit",
    "HalekasEdgeTransition",
    "HalekasFitSettings",
    "fit_finite_bin_distribution",
    "fit_halekas_distribution",
    "mirror_boundary_sin2",
]
