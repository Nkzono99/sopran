from __future__ import annotations

import pandas as pd
import pytest

from sopran.missions.kaguya.er_profile_validation import _profile_summary


def test_profile_summary_reports_interval_width_and_source_reproduction() -> None:
    frame = pd.DataFrame(
        {
            "refit_mirror_ratio": [2.0, 4.0],
            "refit_mirror_ratio_ci95_low": [1.5, 2.0],
            "refit_mirror_ratio_ci95_high": [2.5, 6.0],
            "source_mirror_ratio": [2.0, 4.0],
            "refit_quality_grade": ["good", "review"],
            "source_quality_grade": ["good", "review"],
            "refit_selected_model": ["mirror_only", "electrostatic"],
            "source_selected_model": ["mirror_only", "electrostatic"],
            "refit_profile_truncated": [False, True],
        }
    )

    summary = _profile_summary(
        frame,
        source_rows=2,
        expected_days=1,
        state_days={"2008-01-01": {"status": "complete"}},
        failures={},
    )

    assert summary["complete"] is True
    assert summary["profile_interval_fraction"] == 1.0
    assert summary["profile_truncated_fraction"] == 0.5
    assert summary["profile_relative_width"]["median"] == pytest.approx(0.75)
    assert summary["source_refit_relative_change"]["median"] == 0.0
