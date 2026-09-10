from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import sopran as spn


def test_corrected_coordinates_and_field_meaning() -> None:
    table = spn.moon.magnetic_anomalies()
    rows = table.set_index("feature_id")
    assert len(table) == 15
    # The uncorrected paper placed Descartes at 52 E, 15 S and Abel at 90 E, 30 S.
    np.testing.assert_allclose(rows.loc["descartes", ["lon_deg", "lat_deg"]], [16.5, -10.5])
    np.testing.assert_allclose(rows.loc["abel", ["lon_deg", "lat_deg"]], [88, -32])
    assert rows.loc["gerasimovich", "peak_field_30km_nt"] == 28
    assert rows.loc["descartes", "reference_doi"] == "10.1029/2011JE003852"
    assert rows.loc["abel", "swirl"] == "not_recognized"
    assert rows.loc["marginis", "note"]
    assert table.observation_radius_deg.isna().all()
    assert not table.attrs["complete_global_inventory"]
    assert "not surface" in table.attrs["field_semantics"]


def test_oliveira_analysis_domains_do_not_invent_peak_fields() -> None:
    table = spn.Moon().magnetic_anomalies("oliveira2017")
    rows = table.set_index("feature_id")
    assert len(table) == 15
    assert table.peak_field_30km_nt.isna().all()
    assert table.swirl.isna().all()
    assert set(table.position_kind) == {"analysis_center"}
    assert rows.loc["serenitatis", "observation_radius_deg"] == 4.5
    assert rows.loc["serenitatis", "dipole_radius_deg"] == 3
    assert rows.loc["sylvester", "lat_deg"] == 80


def test_all_preserves_source_disagreements_and_normalizes_search() -> None:
    table = spn.moon.magnetic_anomalies("all")
    assert len(table) == 30
    assert table.feature_id.nunique() == 23
    for name in ("reiner gamma", "REINER-γ", "reiner_gamma"):
        selected = spn.moon.magnetic_anomalies("all", name=name)
        assert selected.lon_deg.tolist() == [302.5, 302.7]
        assert selected.lat_deg.tolist() == [7.5, 7.6]
    assert spn.moon.magnetic_anomalies(name=".*").empty
    table.loc[0, "lat_deg"] = 0
    assert spn.moon.magnetic_anomalies().loc[0, "lat_deg"] == -32


def test_near_wraps_longitude_sorts_and_filters_reference_points() -> None:
    east = spn.moon.magnetic_anomalies("all", near=(302.5, 7.5), radius_deg=1)
    west = spn.moon.magnetic_anomalies("all", near=(-57.5, 7.5), radius_deg=1)
    pd.testing.assert_frame_equal(east, west)
    assert east.feature_id.tolist() == ["reiner_gamma", "reiner_gamma"]
    assert east.distance_deg.iloc[0] == 0
    assert east.distance_deg.is_monotonic_increasing
    np.testing.assert_allclose(east.distance_km, np.deg2rad(east.distance_deg) * 1737.4)
    assert len(spn.moon.magnetic_anomalies(near=(302.5, 7.5), radius_deg=0)) == 1


def test_distances_at_seam_poles_and_antipode() -> None:
    # Same equator, across 0 degrees: Smythii at 87.5 E is 88.5 degrees from 359 E.
    smythii = spn.moon.magnetic_anomalies("oliveira2017", name="smythii", near=(359, 0))
    assert smythii.distance_deg.iloc[0] == pytest.approx(88.5)
    pole = spn.moon.magnetic_anomalies("oliveira2017", near=(0, 90))
    assert pole.feature_id.iloc[0] == "sylvester"
    assert pole.distance_deg.iloc[0] == pytest.approx(10)
    antipode = spn.moon.magnetic_anomalies(name="reiner", near=(122.5, -7.5))
    assert antipode.distance_deg.iloc[0] == pytest.approx(180)
    empty = spn.moon.magnetic_anomalies(name="missing", near=(0, 0), radius_deg=1)
    assert empty.empty and "distance_km" in empty and empty.attrs["body"] == "moon"


@pytest.mark.parametrize(
    "name, near, radius_deg",
    [("sylvester", (0, 90), 10), ("smythii", (87.5, 90), 90)],
)
def test_radius_includes_exact_geometric_boundary(name, near, radius_deg) -> None:
    on_boundary = spn.moon.magnetic_anomalies(
        "oliveira2017", name=name, near=near, radius_deg=radius_deg
    )
    assert len(on_boundary) == 1
    assert on_boundary.distance_deg.iloc[0] == pytest.approx(radius_deg)
    outside = spn.moon.magnetic_anomalies(
        "oliveira2017", name=name, near=near, radius_deg=radius_deg - 1e-6
    )
    assert outside.empty


@pytest.mark.parametrize(
    "parameters",
    [
        {"catalog": "unknown"},
        {"radius_deg": 1},
        {"near": (0, 91)},
        {"near": (np.nan, 0)},
        {"near": (0, np.inf)},
        {"near": (0, 0), "radius_deg": -1},
        {"near": (0, 0), "radius_deg": np.nan},
        {"near": (0, 0), "radius_deg": 181},
    ],
)
def test_invalid_spatial_queries(parameters) -> None:
    with pytest.raises(ValueError):
        spn.moon.magnetic_anomalies(**parameters)
