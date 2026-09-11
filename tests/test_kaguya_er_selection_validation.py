from __future__ import annotations

import numpy as np
import pandas as pd

from sopran.missions.kaguya.er_selection_validation import (
    validate_effective_field_selection,
)


def test_selection_validation_separates_three_pipeline_stages() -> None:
    rng = np.random.default_rng(42)
    rows = 900
    day_index = np.arange(rows) // 15
    total_counts = np.exp(rng.normal(9.0, 2.0, rows))
    input_supported = total_counts > 4_000.0
    longitude = rng.uniform(-180.0, 180.0, rows)
    latitude = rng.uniform(-80.0, 80.0, rows)
    edge_probability = 1.0 / (1.0 + np.exp(-(0.4 * np.sin(np.radians(longitude)) - 1.2)))
    edge_supported = input_supported & (rng.random(rows) < edge_probability)
    quality_probability = 1.0 / (
        1.0 + np.exp(-(0.7 * (np.log(total_counts) - 9.0)))
    )
    accepted = edge_supported & (rng.random(rows) < quality_probability)
    reason = np.where(
        input_supported,
        np.where(edge_supported, "mirror_edge_supported", "no_edge_evidence"),
        "insufficient_total_counts",
    )
    grade = np.where(accepted, "good", np.where(edge_supported, "poor", "reject"))
    frame = pd.DataFrame(
        {
            "time": pd.Timestamp("2008-01-01", tz="UTC")
            + pd.to_timedelta(np.arange(rows) * 600, unit="s"),
            "source_day": [
                f"2008-{1 + value // 28:02d}-{1 + value % 28:02d}"
                for value in day_index
            ],
            "reason": reason,
            "edge_supported": edge_supported,
            "quality_grade": grade,
            "total_counts": total_counts,
            "n_cells": rng.integers(80, 256, rows),
            "n_energy_bins": rng.integers(10, 33, rows),
            "altitude": rng.uniform(40.0, 120.0, rows),
            "sza": rng.uniform(0.0, 180.0, rows),
            "b_sc_nT": rng.uniform(2.0, 10.0, rows),
            "radial_magnetic_field": rng.uniform(-5.0, 5.0, rows),
            "longitude": longitude,
            "latitude": latitude,
        }
    )

    result = validate_effective_field_selection(frame, folds=3)

    assert result.summary["status"] == "complete"
    assert set(result.performance["outcome"]) == {
        "input_supported",
        "edge_supported_given_input",
        "quality_accepted_given_edge",
    }
    assert set(result.performance["model"]) == {
        "observation",
        "environment",
        "combined",
    }
    input_observation = result.performance.loc[
        result.performance["outcome"].eq("input_supported")
        & result.performance["model"].eq("observation")
    ].iloc[0]
    assert input_observation["roc_auc"] > 0.95
    assert not result.coefficients.empty
    assert len(result.calibration) == 90
