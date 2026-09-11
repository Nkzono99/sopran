from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sopran.missions.kaguya.er_validation import (
    _straight_local_footpoints,
    validate_effective_field_archive,
    wilson_interval,
)


def test_wilson_interval_handles_limits_and_invalid_counts() -> None:
    empty_low, empty_high = wilson_interval(0, 0)
    assert np.isnan(empty_low)
    assert np.isnan(empty_high)
    low, high = wilson_interval(38, 40)
    assert low == pytest.approx(0.8349612263)
    assert high == pytest.approx(0.9861793326)
    with pytest.raises(ValueError, match="0 <= successes <= total"):
        wilson_interval(2, 1)


def test_straight_local_footpoints_select_the_surfaceward_branch() -> None:
    frame = pd.DataFrame(
        {
            "position_x": [1837.4, 1837.4],
            "position_y": [0.0, 0.0],
            "position_z": [0.0, 0.0],
            "magnetic_field_x": [5.0, 0.0],
            "magnetic_field_y": [0.0, 5.0],
            "magnetic_field_z": [0.0, 0.0],
        }
    )

    result = _straight_local_footpoints(frame)

    assert result["straight_local_connected"].tolist() == [True, False]
    assert result.loc[0, "straight_footpoint_longitude"] == pytest.approx(0.0)
    assert result.loc[0, "straight_footpoint_latitude"] == pytest.approx(0.0)
    assert result.loc[0, "straight_footpoint_distance_km"] == pytest.approx(100.0)
    assert result.loc[0, "straight_footpoint_separation_deg"] == pytest.approx(0.0)


def test_validate_effective_field_archive_checks_a_minimal_variant(
    tmp_path: Path,
) -> None:
    variant = tmp_path / "variant"
    shard = variant / "shards" / "date=2008-01-01" / "part-000.parquet"
    shard.parent.mkdir(parents=True)
    radius = 1837.4
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2008-01-01T00:05:00Z", "2008-01-01T00:15:00Z"], utc=True),
            "source_day": ["2008-01-01", "2008-01-01"],
            "success": [True, True],
            "reason": ["mirror_edge_supported", "no_edge_evidence"],
            "selected_model": ["mirror_only", "no_edge"],
            "edge_supported": [True, False],
            "quality_grade": ["good", "reject"],
            "mirror_ratio": [2.0, np.nan],
            "effective_field": [10.0, np.nan],
            "b_sc_nT": [5.0, 6.0],
            "magnetic_field_x": [5.0, 6.0],
            "magnetic_field_y": [0.0, 0.0],
            "magnetic_field_z": [0.0, 0.0],
            "position_x": [radius, radius],
            "position_y": [0.0, 0.0],
            "position_z": [0.0, 0.0],
            "radial_distance": [radius, radius],
            "altitude": [100.0, 100.0],
            "longitude": [0.0, 0.0],
            "latitude": [0.0, 0.0],
            "sza": [60.0, 120.0],
            "total_counts": [200, 50],
            "energy_ratio_step_supported": [False, False],
            "exposure_mode": ["calibrated", "calibrated"],
            "sampling_cadence_seconds": [600.0, 600.0],
        }
    )
    frame.to_parquet(shard, index=False)
    checksum = "sha256:" + hashlib.sha256(shard.read_bytes()).hexdigest()
    relative_shard = "shards/date=2008-01-01/part-000.parquet"
    pd.DataFrame(
        {
            "path": [relative_shard],
            "status": ["complete"],
            "row_count": [2],
            "checksum": [checksum],
        }
    ).to_parquet(variant / "catalog.parquet", index=False)
    (variant / "build-state.json").write_text(
        json.dumps(
            {
                "requested_time": {
                    "start": "2008-01-01T00:00:00Z",
                    "stop": "2008-01-03T00:00:00Z",
                },
                "days": {
                    "2008-01-01": {"status": "complete", "row_count": 2},
                    "2008-01-02": {
                        "status": "missing",
                        "message": "PACE ESA1 file is unavailable",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (variant / "dataset.json").write_text(
        json.dumps(
            {
                "dataset_id": "kaguya.er.effective_field",
                "parameters": {
                    "sampling_cadence_seconds": 600.0,
                    "pitch_bins": 16,
                    "effective_field_fit": {"profile_likelihood": False},
                },
                "variant": {"id": "test"},
            }
        ),
        encoding="utf-8",
    )

    result = validate_effective_field_archive(variant)

    assert result.passed
    assert result.summary["days"] == {
        "requested": 2,
        "complete": 1,
        "missing": 1,
        "no_data": 0,
        "failed": 0,
        "terminal_fraction": 1.0,
        "complete_fraction": 0.5,
        "missing_categories": {"pace": 1},
    }
    assert result.summary["selection"]["accepted"] == 1
    assert result.summary["effective_field_nT"]["median"] == pytest.approx(10.0)
