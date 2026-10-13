"""Standardized ridge regression with grouped cross-validation.

Features are standardized with the training rows and the intercept is not
penalized. ``grouped_cv_predictions`` keeps all rows of a group (for example
an orbit track) in the same fold, so the cross-validated R2 measures
prediction across tracks rather than interpolation inside one. The native
kernel is used when available; the numpy path gives the same model.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class RidgeFit:
    prediction: FloatArray
    coefficients: FloatArray
    means: FloatArray
    scales: FloatArray

    @property
    def intercept(self) -> float:
        return float(self.coefficients[0])

    @property
    def standardized_coefficients(self) -> FloatArray:
        return self.coefficients[1:]


@dataclass(frozen=True)
class ExternalGain:
    """Empirical gain ``exp(pred_physical - pred_base)`` and the corrected quantity."""

    base_prediction: FloatArray
    physical_prediction: FloatArray
    external_gain: FloatArray
    corrected: FloatArray
    base_r2: float
    physical_r2: float
    mean_external_gain: float


def ridge_fit_predict(x: ArrayLike, y: ArrayLike, *, alpha: float) -> RidgeFit:
    features, target = _matrix_and_target(x, y)
    native = _native()
    if native is not None:
        raw = native.ridge_fit_predict(features, target, float(alpha))
        return RidgeFit(
            prediction=np.asarray(raw["prediction"], dtype=float),
            coefficients=np.asarray(raw["coefficients"], dtype=float),
            means=np.asarray(raw["means"], dtype=float),
            scales=np.asarray(raw["scales"], dtype=float),
        )
    coefficients, means, scales = _fit(features, target, alpha)
    return RidgeFit(
        prediction=_predict(features, coefficients, means, scales),
        coefficients=coefficients,
        means=means,
        scales=scales,
    )


def grouped_cv_predictions(
    x: ArrayLike,
    y: ArrayLike,
    *,
    groups: ArrayLike | None = None,
    alpha: float,
    folds: int = 5,
    seed: int = 0,
) -> FloatArray:
    """Out-of-fold predictions; rows sharing a group value never split across folds."""

    features, target = _matrix_and_target(x, y)
    codes = _group_codes(groups, target.size)
    native = _native()
    if native is not None:
        return np.asarray(
            native.grouped_ridge_cv_predictions(
                features, target, codes, float(alpha), int(max(2, folds)), int(seed)
            ),
            dtype=float,
        )
    rng = np.random.default_rng(seed)
    folds = max(2, int(folds))
    rows = target.size
    if codes is None:
        order = np.arange(rows)
        rng.shuffle(order)
        splits = [order[fold::folds] for fold in range(folds)]
    else:
        unique = np.unique(codes)
        rng.shuffle(unique)
        splits = [np.flatnonzero(np.isin(codes, unique[fold::folds])) for fold in range(folds)]
    out = np.full(rows, np.nan)
    for test in splits:
        if test.size == 0:
            continue
        train = np.setdiff1d(np.arange(rows), test)
        coefficients, means, scales = _fit(features[train], target[train], alpha)
        out[test] = _predict(features[test], coefficients, means, scales)
    return out


def external_gain(
    base_x: ArrayLike,
    physical_x: ArrayLike,
    log_target: ArrayLike,
    *,
    alpha: float,
    eps: float = 0.25,
) -> ExternalGain:
    """Fit base and physical ridge models to a log target; gain is their ratio.

    ``corrected = max(exp(log_target - log_gain) - eps, 0)`` removes the part
    of the target that the physical features explain beyond the base model.
    """

    base, target = _matrix_and_target(base_x, log_target)
    physical, _ = _matrix_and_target(physical_x, log_target)
    native = _native()
    if native is not None:
        raw = native.ridge_external_gain(base, physical, target, float(alpha), float(eps))
        return ExternalGain(
            base_prediction=np.asarray(raw["base_prediction"], dtype=float),
            physical_prediction=np.asarray(raw["physical_prediction"], dtype=float),
            external_gain=np.asarray(raw["external_gain"], dtype=float),
            corrected=np.asarray(raw["corrected"], dtype=float),
            base_r2=float(raw["base_r2"]),
            physical_r2=float(raw["physical_r2"]),
            mean_external_gain=float(raw["mean_external_gain"]),
        )
    base_fit = ridge_fit_predict(base, target, alpha=alpha)
    physical_fit = ridge_fit_predict(physical, target, alpha=alpha)
    log_gain = physical_fit.prediction - base_fit.prediction
    gain = np.exp(log_gain)
    corrected = np.maximum(np.exp(target - log_gain) - eps, 0.0)
    return ExternalGain(
        base_prediction=base_fit.prediction,
        physical_prediction=physical_fit.prediction,
        external_gain=gain,
        corrected=corrected,
        base_r2=r2_score(target, base_fit.prediction),
        physical_r2=r2_score(target, physical_fit.prediction),
        mean_external_gain=float(np.mean(gain)),
    )


def r2_score(y: ArrayLike, prediction: ArrayLike) -> float:
    target = np.asarray(y, dtype=float)
    predicted = np.asarray(prediction, dtype=float)
    finite = np.isfinite(target) & np.isfinite(predicted)
    if np.count_nonzero(finite) < 2:
        return float("nan")
    ss_tot = float(np.sum((target[finite] - np.mean(target[finite])) ** 2))
    ss_res = float(np.sum((target[finite] - predicted[finite]) ** 2))
    return float("nan") if ss_tot <= 0.0 else 1.0 - ss_res / ss_tot


def rmse(y: ArrayLike, prediction: ArrayLike) -> float:
    residual = np.asarray(y, dtype=float) - np.asarray(prediction, dtype=float)
    residual = residual[np.isfinite(residual)]
    return float(np.sqrt(np.mean(residual**2))) if residual.size else float("nan")


@dataclass(frozen=True)
class ModelLadder:
    metrics: pl.DataFrame
    coefficients: pl.DataFrame
    predictions: pl.DataFrame


def model_ladder(
    frame: pl.DataFrame,
    *,
    targets: Sequence[str],
    specs: Sequence[tuple[str, Sequence[str]]],
    alpha: float,
    folds: int = 5,
    seed: int = 0,
    group_column: str | None = None,
    id_columns: Sequence[str] = (),
    min_rows_margin: int = 5,
) -> ModelLadder:
    """Fit nested feature sets per target and report training and grouped-CV R2.

    Each spec is ``(model_name, feature_columns)``. Rows with a non-finite
    target or feature are dropped per model, so ``n_rows`` differs between
    models with different features.
    """

    metric_rows: list[dict[str, Any]] = []
    coefficient_rows: list[dict[str, Any]] = []
    prediction_frames: list[pl.DataFrame] = []
    for target in targets:
        for model_name, columns in specs:
            columns = list(columns)
            subset = _finite_subset(frame, target, columns)
            if subset.height <= len(columns) + int(min_rows_margin):
                continue
            x = np.column_stack([subset[column].cast(pl.Float64).to_numpy() for column in columns])
            y = subset[target].cast(pl.Float64).to_numpy()
            groups = (
                subset[group_column].to_numpy()
                if group_column and group_column in subset.columns
                else None
            )
            fit = ridge_fit_predict(x, y, alpha=alpha)
            cv = grouped_cv_predictions(x, y, groups=groups, alpha=alpha, folds=folds, seed=seed)
            metric_rows.append(
                {
                    "target": target,
                    "model": model_name,
                    "features": ",".join(columns),
                    "n_rows": int(subset.height),
                    "n_groups": int(np.unique(groups).size)
                    if groups is not None
                    else int(subset.height),
                    "alpha": float(alpha),
                    "train_r2": r2_score(y, fit.prediction),
                    "cv_r2": r2_score(y, cv),
                    "train_rmse": rmse(y, fit.prediction),
                    "cv_rmse": rmse(y, cv),
                }
            )
            for column, value, mean, scale in zip(
                columns, fit.standardized_coefficients, fit.means, fit.scales, strict=True
            ):
                coefficient_rows.append(
                    {
                        "target": target,
                        "model": model_name,
                        "feature": column,
                        "standardized_coefficient": float(value),
                        "feature_mean": float(mean),
                        "feature_sd": float(scale),
                    }
                )
            keep = [column for column in id_columns if column in subset.columns]
            prediction_frames.append(
                subset.select(keep).with_columns(
                    pl.lit(target).alias("target"),
                    pl.lit(model_name).alias("model"),
                    pl.Series("observed", y),
                    pl.Series("cv_prediction", cv),
                    pl.Series("cv_residual", y - cv),
                )
            )
    predictions = (
        pl.concat(prediction_frames, how="diagonal") if prediction_frames else pl.DataFrame()
    )
    return ModelLadder(
        metrics=pl.DataFrame(metric_rows),
        coefficients=pl.DataFrame(coefficient_rows),
        predictions=predictions,
    )


def feature_drop_diagnostics(
    frame: pl.DataFrame,
    *,
    target: str,
    feature_groups: Mapping[str, Sequence[str]],
    alpha: float,
    folds: int = 5,
    seed: int = 0,
    group_column: str | None = None,
    min_rows_margin: int = 5,
) -> pl.DataFrame:
    """Loss of grouped-CV R2 when each feature group is removed from the full model."""

    active = {name: list(columns) for name, columns in feature_groups.items() if columns}
    full_columns = [column for columns in active.values() for column in columns]
    subset = _finite_subset(frame, target, full_columns)
    if not active or subset.height <= len(full_columns) + int(min_rows_margin):
        return pl.DataFrame()
    y = subset[target].cast(pl.Float64).to_numpy()
    groups = (
        subset[group_column].to_numpy() if group_column and group_column in subset.columns else None
    )

    def cv_r2(columns: Sequence[str]) -> float:
        x = np.column_stack([subset[column].cast(pl.Float64).to_numpy() for column in columns])
        return r2_score(
            y, grouped_cv_predictions(x, y, groups=groups, alpha=alpha, folds=folds, seed=seed)
        )

    full_r2 = cv_r2(full_columns)
    rows = []
    for dropped, columns in active.items():
        kept = [column for name, cols in active.items() if name != dropped for column in cols]
        if not kept:
            continue
        drop_r2 = cv_r2(kept)
        rows.append(
            {
                "target": target,
                "dropped_group": dropped,
                "n_rows": int(subset.height),
                "full_cv_r2": full_r2,
                "without_group_cv_r2": drop_r2,
                "delta_cv_r2": full_r2 - drop_r2,
                "features_dropped": ",".join(columns),
            }
        )
    return pl.DataFrame(rows).sort("delta_cv_r2", descending=True) if rows else pl.DataFrame()


def _finite_subset(frame: pl.DataFrame, target: str, columns: Sequence[str]) -> pl.DataFrame:
    needed = [target, *columns]
    missing = [column for column in needed if column not in frame.columns]
    if missing:
        raise KeyError(f"missing columns: {missing}")
    condition = pl.all_horizontal(
        [pl.col(column).cast(pl.Float64).is_finite() for column in needed]
    )
    return frame.filter(condition)


def _fit(
    features: FloatArray, target: FloatArray, alpha: float
) -> tuple[FloatArray, FloatArray, FloatArray]:
    if not np.isfinite(alpha) or alpha < 0.0:
        raise ValueError("alpha must be finite and non-negative")
    if not np.all(np.isfinite(features)) or not np.all(np.isfinite(target)):
        raise ValueError("features and target must be finite")
    means = features.mean(axis=0)
    scales = features.std(axis=0)
    scales = np.where((scales > 0.0) & np.isfinite(scales), scales, 1.0)
    design = np.column_stack([np.ones(features.shape[0]), (features - means) / scales])
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    normal = design.T @ design + penalty
    try:
        coefficients = np.linalg.solve(normal, design.T @ target)
    except np.linalg.LinAlgError as exc:
        raise ValueError("ridge normal equations are singular") from exc
    return coefficients, means, scales


def _predict(
    features: FloatArray, coefficients: FloatArray, means: FloatArray, scales: FloatArray
) -> FloatArray:
    design = np.column_stack([np.ones(features.shape[0]), (features - means) / scales])
    return np.asarray(design @ coefficients, dtype=float)


def _matrix_and_target(x: ArrayLike, y: ArrayLike) -> tuple[FloatArray, FloatArray]:
    features = np.ascontiguousarray(np.asarray(x, dtype=float))
    if features.ndim == 1:
        features = features[:, None]
    if features.ndim != 2:
        raise ValueError("features must be (rows, columns)")
    target = np.ascontiguousarray(np.asarray(y, dtype=float).reshape(-1))
    if target.size != features.shape[0]:
        raise ValueError("target must have one value per feature row")
    return features, target


def _group_codes(groups: ArrayLike | None, rows: int) -> NDArray[np.int64] | None:
    if groups is None:
        return None
    values = np.asarray(groups).reshape(-1)
    if values.size != rows:
        raise ValueError("groups must have one value per row")
    _, inverse = np.unique(values, return_inverse=True)
    return np.ascontiguousarray(inverse, dtype=np.int64)


def _native() -> Any | None:
    try:
        module = importlib.import_module("sopran._native")
    except ImportError:
        return None
    return module if hasattr(module, "ridge_fit_predict") else None


__all__ = [
    "ExternalGain",
    "ModelLadder",
    "RidgeFit",
    "external_gain",
    "feature_drop_diagnostics",
    "grouped_cv_predictions",
    "model_ladder",
    "r2_score",
    "ridge_fit_predict",
    "rmse",
]
