from __future__ import annotations

import json

import pandas as pd

import sopran as spn
from sopran.experimental.electron_reflection import EffectiveFieldFitSettings
from sopran.experimental.kaguya.er_catalog import (
    KAGUYA_ESA1_ARCHIVE_TIME,
    _cadence_seconds,
    _catalog_variant_id,
    _reconcile_completed_day_state,
)
from sopran.missions.kaguya.spice import _selene_ck_specs


def test_er_catalog_cadence_and_variant_are_explicit() -> None:
    settings = EffectiveFieldFitSettings(profile_likelihood=False)

    assert _cadence_seconds("10min") == 600.0
    assert _cadence_seconds(None) is None
    assert _catalog_variant_id(
        settings=settings,
        cadence_seconds=600.0,
        pitch_bins=16,
        include_sza=True,
    ).startswith("robust_counts_v3_esa1_esa2_600s_p16_")


def test_er_catalog_archive_and_selene_ck_coverage() -> None:
    assert KAGUYA_ESA1_ARCHIVE_TIME.start_iso == "2007-11-07T00:00:00Z"
    assert KAGUYA_ESA1_ARCHIVE_TIME.stop_iso == "2009-06-11T00:00:00Z"

    specs = _selene_ck_specs(spn.period("2008-08-31", "2008-09-02"))

    assert [spec.relative_path[-1] for spec in specs] == [
        "SEL_M_200808_S_V03.BC",
        "SEL_M_200809_S_V03.BC",
    ]


def test_er_catalog_reconciles_committed_shard_with_stale_state(tmp_path) -> None:
    shard_path = "shards/date=2008-01-01/part-000.parquet"
    target = tmp_path / shard_path
    target.parent.mkdir(parents=True)
    pd.DataFrame(
        {"quality_grade": ["good", "review", "reject", "reject"]}
    ).to_parquet(target)
    state_path = tmp_path / "build-state.json"
    state = {
        "days": {
            "2008-01-01": {
                "status": "failed",
                "started_at": "2008-01-02T00:00:00Z",
                "message": "stale concurrent writer",
            }
        }
    }

    _reconcile_completed_day_state(
        state,
        state_path,
        root=tmp_path,
        label="2008-01-01",
        shard_path=shard_path,
        shard={"path": shard_path, "row_count": 4, "status": "complete"},
        prior=state["days"]["2008-01-01"],
    )

    written = json.loads(state_path.read_text(encoding="utf-8"))
    repaired = written["days"]["2008-01-01"]
    assert repaired["status"] == "complete"
    assert repaired["row_count"] == 4
    assert repaired["quality_counts"] == {"good": 1, "reject": 2, "review": 1}
    assert "message" not in repaired
