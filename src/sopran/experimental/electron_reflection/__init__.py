"""Opt-in finite-bin and Halekas electron-reflectometry estimators."""

from sopran.experimental.electron_reflection.common import (
    ElectronReflectionCounts,
    mirror_boundary_sin2,
)
from sopran.experimental.electron_reflection.finite_bin import (
    AngularTransport,
    CountSelection,
    FiniteBinFit,
    FiniteBinFitSettings,
    FiniteBinLoss,
    FiniteBinModel,
    FiniteBinObservation,
    FiniteBinParameters,
    FiniteBinProfile,
    fit_finite_bin_distribution,
    profile_mirror_ratio,
)
from sopran.experimental.electron_reflection.halekas import (
    HalekasDistributionFit,
    HalekasEdgeTransition,
    HalekasFitSettings,
    fit_halekas_distribution,
)

__all__ = [
    "AngularTransport",
    "CountSelection",
    "ElectronReflectionCounts",
    "FiniteBinFit",
    "FiniteBinFitSettings",
    "FiniteBinLoss",
    "FiniteBinModel",
    "FiniteBinObservation",
    "FiniteBinParameters",
    "FiniteBinProfile",
    "HalekasDistributionFit",
    "HalekasEdgeTransition",
    "HalekasFitSettings",
    "fit_finite_bin_distribution",
    "fit_halekas_distribution",
    "mirror_boundary_sin2",
    "profile_mirror_ratio",
]
