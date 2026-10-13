from __future__ import annotations

import numpy as np
import pytest

from sopran.experimental.statistics import ridge


def _linear(rows: int = 60, seed: int = 3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = np.column_stack([np.linspace(0.0, 6.0, rows), rng.normal(size=rows)])
    y = 1.5 + 2.0 * x[:, 0] - 0.25 * x[:, 1] + 0.01 * rng.normal(size=rows)
    groups = np.arange(rows) // 3
    return x, y, groups


def test_ridge_recovers_a_linear_signal_with_and_without_the_native_kernel(monkeypatch) -> None:
    x, y, _ = _linear()
    native = ridge.ridge_fit_predict(x, y, alpha=1e-6)
    assert ridge.r2_score(y, native.prediction) > 0.999
    assert native.coefficients.size == 3
    monkeypatch.setattr(ridge, "_native", lambda: None)
    fallback = ridge.ridge_fit_predict(x, y, alpha=1e-6)
    np.testing.assert_allclose(fallback.prediction, native.prediction, atol=1e-8)
    np.testing.assert_allclose(fallback.coefficients, native.coefficients, atol=1e-8)
    with pytest.raises(ValueError):
        ridge.ridge_fit_predict(np.ones((4, 1)), [1.0, 2.0, 3.0], alpha=0.0)


def test_grouped_cv_keeps_groups_together_and_matches_fallback(monkeypatch) -> None:
    x, y, groups = _linear()
    native = ridge.grouped_cv_predictions(x, y, groups=groups, alpha=1e-6, folds=4, seed=7)
    assert np.all(np.isfinite(native))
    assert ridge.r2_score(y, native) > 0.99
    monkeypatch.setattr(ridge, "_native", lambda: None)
    fallback = ridge.grouped_cv_predictions(x, y, groups=groups, alpha=1e-6, folds=4, seed=7)
    assert ridge.r2_score(y, fallback) > 0.99
    ungrouped = ridge.grouped_cv_predictions(x, y, alpha=1e-6, folds=4, seed=7)
    assert np.all(np.isfinite(ungrouped))


def test_external_gain_scales_out_the_physical_component() -> None:
    rng = np.random.default_rng(0)
    rows = 80
    base = rng.normal(size=(rows, 1))
    environment = rng.normal(size=(rows, 1))
    log_target = 0.2 + 0.5 * base[:, 0] + 0.8 * environment[:, 0]
    gain = ridge.external_gain(base, np.column_stack([base, environment]), log_target, alpha=1e-6)
    assert gain.physical_r2 > gain.base_r2
    assert np.all(gain.external_gain > 0.0)
    assert np.all(gain.corrected >= 0.0)
    assert gain.mean_external_gain == pytest.approx(float(np.mean(gain.external_gain)))


def test_model_ladder_and_feature_drop_report_grouped_cv() -> None:
    pl = pytest.importorskip("polars")
    x, y, groups = _linear(rows=90)
    frame = pl.DataFrame(
        {"target": y, "a": x[:, 0], "b": x[:, 1], "track": groups, "id": np.arange(90)}
    )
    ladder = ridge.model_ladder(
        frame,
        targets=["target"],
        specs=[("a_only", ["a"]), ("a_b", ["a", "b"])],
        alpha=1e-6,
        folds=3,
        seed=1,
        group_column="track",
        id_columns=["id"],
    )
    assert ladder.metrics["model"].to_list() == ["a_only", "a_b"]
    assert ladder.metrics["cv_r2"][1] >= ladder.metrics["cv_r2"][0] - 1e-3
    assert ladder.coefficients.filter(pl.col("model") == "a_b").height == 2
    assert {"id", "cv_prediction", "cv_residual"} <= set(ladder.predictions.columns)
    drops = ridge.feature_drop_diagnostics(
        frame,
        target="target",
        feature_groups={"a": ["a"], "b": ["b"]},
        alpha=1e-6,
        folds=3,
        seed=1,
        group_column="track",
    )
    assert drops["dropped_group"].to_list()[0] == "a"
    assert drops["delta_cv_r2"][0] > drops["delta_cv_r2"][1]
    with pytest.raises(KeyError):
        ridge.model_ladder(frame, targets=["missing"], specs=[("a", ["a"])], alpha=1.0)
