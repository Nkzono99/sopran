from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize  # type: ignore[import-untyped]
from scipy.special import expit  # type: ignore[import-untyped]
from scipy.stats import rankdata  # type: ignore[import-untyped]

MIN_ROWS = 100
MIN_CLASS_ROWS = 10


@dataclass(frozen=True)
class EffectiveFieldSelectionValidation:
    """Cross-validated descriptive models for the ER selection pipeline."""

    performance: pd.DataFrame
    coefficients: pd.DataFrame
    calibration: pd.DataFrame
    summary: dict[str, Any]


def validate_effective_field_selection(
    frame: pd.DataFrame,
    *,
    folds: int = 5,
    ridge: float = 1.0,
) -> EffectiveFieldSelectionValidation:
    """Separate input support, edge evidence, and quality-selection effects."""

    if folds < 2:
        raise ValueError("folds must be at least two")
    if not np.isfinite(ridge) or ridge < 0.0:
        raise ValueError("ridge must be finite and non-negative")
    required = {
        "time",
        "source_day",
        "reason",
        "edge_supported",
        "quality_grade",
        "total_counts",
        "n_cells",
        "n_energy_bins",
        "altitude",
        "sza",
        "b_sc_nT",
        "radial_magnetic_field",
        "longitude",
        "latitude",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        return _empty_result("missing_columns", missing_columns=missing)
    if len(frame) < MIN_ROWS:
        return _empty_result("insufficient_rows", rows=len(frame))

    features = _feature_arrays(frame)
    models = {
        "observation": ("log_total_counts", "n_cells", "n_energy_bins"),
        "environment": (
            "altitude_km",
            "cos_sza",
            "log_b_sc",
            "absolute_radial_field_fraction",
            "sin_latitude",
            "sin2_latitude",
            "sin_longitude",
            "cos_longitude",
            "sin_2longitude",
            "cos_2longitude",
            "mission_time",
        ),
    }
    models["combined"] = models["observation"] + models["environment"]
    input_supported = ~frame["reason"].astype(str).isin(
        ("insufficient_energy_support", "insufficient_total_counts")
    ).to_numpy()
    edge_supported = frame["edge_supported"].fillna(False).to_numpy(dtype=bool)
    accepted = frame["quality_grade"].astype(str).isin(("good", "review")).to_numpy()
    outcomes = {
        "input_supported": (np.ones(len(frame), dtype=bool), input_supported),
        "edge_supported_given_input": (input_supported, edge_supported),
        "quality_accepted_given_edge": (edge_supported, accepted),
    }
    day_fold = _contiguous_day_folds(frame["source_day"].astype(str), folds=folds)

    performance_rows: list[dict[str, Any]] = []
    coefficient_rows: list[dict[str, Any]] = []
    calibration_rows: list[dict[str, Any]] = []
    skipped: dict[str, str] = {}
    for outcome_name, (cohort, outcome) in outcomes.items():
        common_feature_names = models["combined"]
        finite = cohort.copy()
        for name in common_feature_names:
            finite &= np.isfinite(features[name])
        selected = np.flatnonzero(finite)
        y = outcome[selected].astype(float)
        class_rows = min(np.count_nonzero(y), np.count_nonzero(1.0 - y))
        if selected.size < MIN_ROWS or class_rows < MIN_CLASS_ROWS:
            skipped[outcome_name] = "insufficient_class_support"
            continue
        selected_folds = day_fold[selected]
        for model_name, feature_names in models.items():
            matrix = np.column_stack([features[name][selected] for name in feature_names])
            predicted = np.full(y.shape, np.nan, dtype=float)
            for fold in sorted(np.unique(selected_folds)):
                test = selected_folds == fold
                train = ~test
                if (
                    np.count_nonzero(test) == 0
                    or np.count_nonzero(train) == 0
                    or np.unique(y[train]).size < 2
                ):
                    continue
                standardized, test_standardized, _center, _scale = _standardize_train_test(
                    matrix[train],
                    matrix[test],
                )
                beta = _fit_logistic(standardized, y[train], ridge=ridge)
                predicted[test] = expit(_with_intercept(test_standardized) @ beta)
            valid = np.isfinite(predicted)
            metrics = _prediction_metrics(y[valid], predicted[valid])
            performance_rows.append(
                {
                    "outcome": outcome_name,
                    "model": model_name,
                    "cohort_rows": int(selected.size),
                    "evaluated_rows": int(np.count_nonzero(valid)),
                    "folds": int(np.unique(selected_folds).size),
                    **metrics,
                }
            )
            calibration_rows.extend(
                _calibration_records(
                    y[valid],
                    predicted[valid],
                    outcome=outcome_name,
                    model=model_name,
                )
            )
            standardized, _unused, center, scale = _standardize_train_test(matrix, matrix[:0])
            beta = _fit_logistic(standardized, y, ridge=ridge)
            for index, name in enumerate(feature_names, start=1):
                coefficient_rows.append(
                    {
                        "outcome": outcome_name,
                        "model": model_name,
                        "feature": name,
                        "coefficient_per_sd": float(beta[index]),
                        "odds_ratio_per_sd": float(np.exp(np.clip(beta[index], -50.0, 50.0))),
                        "raw_center": float(center[index - 1]),
                        "raw_scale": float(scale[index - 1]),
                    }
                )

    performance = pd.DataFrame(performance_rows)
    coefficients = pd.DataFrame(coefficient_rows)
    calibration = pd.DataFrame(calibration_rows)
    return EffectiveFieldSelectionValidation(
        performance=performance,
        coefficients=coefficients,
        calibration=calibration,
        summary={
            "status": "complete" if not performance.empty else "insufficient_data",
            "description": (
                "Descriptive ridge-logistic models with contiguous-day blocked "
                "cross-validation; coefficients are associations, not causal effects."
            ),
            "folds": folds,
            "ridge": ridge,
            "outcomes": performance.to_dict("records"),
            "skipped": skipped,
        },
    )


def _feature_arrays(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    longitude = np.radians(frame["longitude"].to_numpy(dtype=float))
    latitude = np.radians(frame["latitude"].to_numpy(dtype=float))
    sza = np.radians(frame["sza"].to_numpy(dtype=float))
    b_sc = frame["b_sc_nT"].to_numpy(dtype=float)
    radial = frame["radial_magnetic_field"].to_numpy(dtype=float)
    time = pd.to_datetime(frame["time"], utc=True).astype("int64").to_numpy(dtype=float)
    finite_time = time[np.isfinite(time)]
    time_origin = float(np.min(finite_time)) if finite_time.size else 0.0
    year_ns = 365.25 * 86400.0 * 1.0e9
    return {
        "log_total_counts": np.log1p(np.maximum(frame["total_counts"].to_numpy(dtype=float), 0.0)),
        "n_cells": frame["n_cells"].to_numpy(dtype=float),
        "n_energy_bins": frame["n_energy_bins"].to_numpy(dtype=float),
        "altitude_km": frame["altitude"].to_numpy(dtype=float),
        "cos_sza": np.cos(sza),
        "log_b_sc": np.log(np.where(b_sc > 0.0, b_sc, np.nan)),
        "absolute_radial_field_fraction": np.abs(radial) / np.where(b_sc > 0.0, b_sc, np.nan),
        "sin_latitude": np.sin(latitude),
        "sin2_latitude": np.sin(latitude) ** 2,
        "sin_longitude": np.sin(longitude),
        "cos_longitude": np.cos(longitude),
        "sin_2longitude": np.sin(2.0 * longitude),
        "cos_2longitude": np.cos(2.0 * longitude),
        "mission_time": (time - time_origin) / year_ns,
    }


def _contiguous_day_folds(days: pd.Series, *, folds: int) -> np.ndarray:
    unique = np.asarray(sorted(days.unique()), dtype=object)
    fold_by_day = {
        str(label): min(folds - 1, index * folds // max(1, unique.size))
        for index, label in enumerate(unique)
    }
    return days.map(fold_by_day).to_numpy(dtype=int)


def _standardize_train_test(
    train: np.ndarray,
    test: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    center = np.mean(train, axis=0)
    scale = np.std(train, axis=0)
    scale = np.where(scale > 1.0e-12, scale, 1.0)
    return (train - center) / scale, (test - center) / scale, center, scale


def _with_intercept(matrix: np.ndarray) -> np.ndarray:
    return np.column_stack((np.ones(matrix.shape[0]), matrix))


def _fit_logistic(matrix: np.ndarray, outcome: np.ndarray, *, ridge: float) -> np.ndarray:
    design = _with_intercept(matrix)

    def objective(beta: np.ndarray) -> tuple[float, np.ndarray]:
        linear = design @ beta
        penalty = 0.5 * ridge * float(np.dot(beta[1:], beta[1:]))
        loss = float(np.sum(np.logaddexp(0.0, linear) - outcome * linear)) + penalty
        gradient = design.T @ (expit(linear) - outcome)
        gradient[1:] += ridge * beta[1:]
        return loss, gradient

    prevalence = float(np.clip(np.mean(outcome), 1.0e-6, 1.0 - 1.0e-6))
    initial = np.zeros(design.shape[1], dtype=float)
    initial[0] = math.log(prevalence / (1.0 - prevalence))
    result = minimize(
        objective,
        initial,
        method="L-BFGS-B",
        jac=True,
        options={"maxiter": 500, "ftol": 1.0e-10},
    )
    if not result.success or not np.all(np.isfinite(result.x)):
        raise RuntimeError(f"selection logistic fit failed: {result.message}")
    return np.asarray(result.x, dtype=float)


def _prediction_metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    clipped = np.clip(predicted, 1.0e-12, 1.0 - 1.0e-12)
    prevalence = float(np.mean(observed))
    baseline = np.full(observed.shape, prevalence)
    return {
        "prevalence": prevalence,
        "log_loss": float(
            -np.mean(
                observed * np.log(clipped)
                + (1.0 - observed) * np.log1p(-clipped)
            )
        ),
        "baseline_log_loss": float(
            -np.mean(observed * np.log(baseline) + (1.0 - observed) * np.log1p(-baseline))
        ),
        "brier_score": float(np.mean((predicted - observed) ** 2)),
        "roc_auc": _roc_auc(observed, predicted),
        "average_precision": _average_precision(observed, predicted),
    }


def _roc_auc(observed: np.ndarray, predicted: np.ndarray) -> float:
    positive = observed == 1.0
    positive_count = int(np.count_nonzero(positive))
    negative_count = int(observed.size - positive_count)
    if not positive_count or not negative_count:
        return float("nan")
    ranks = rankdata(predicted)
    return float(
        (np.sum(ranks[positive]) - positive_count * (positive_count + 1) / 2.0)
        / (positive_count * negative_count)
    )


def _average_precision(observed: np.ndarray, predicted: np.ndarray) -> float:
    order = np.argsort(-predicted, kind="stable")
    sorted_observed = observed[order]
    positives = int(np.count_nonzero(sorted_observed))
    if not positives:
        return float("nan")
    precision = np.cumsum(sorted_observed) / np.arange(1, sorted_observed.size + 1)
    return float(np.sum(precision * sorted_observed) / positives)


def _calibration_records(
    observed: np.ndarray,
    predicted: np.ndarray,
    *,
    outcome: str,
    model: str,
) -> list[dict[str, Any]]:
    order = np.argsort(predicted, kind="stable")
    groups = np.array_split(order, 10)
    return [
        {
            "outcome": outcome,
            "model": model,
            "decile": index,
            "rows": int(group.size),
            "mean_predicted": float(np.mean(predicted[group])),
            "observed_fraction": float(np.mean(observed[group])),
        }
        for index, group in enumerate(groups, start=1)
        if group.size
    ]


def _empty_result(status: str, **details: Any) -> EffectiveFieldSelectionValidation:
    return EffectiveFieldSelectionValidation(
        performance=pd.DataFrame(),
        coefficients=pd.DataFrame(),
        calibration=pd.DataFrame(),
        summary={"status": status, **details},
    )


__all__ = [
    "EffectiveFieldSelectionValidation",
    "validate_effective_field_selection",
]
