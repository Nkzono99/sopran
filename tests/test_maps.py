from __future__ import annotations

import sopran as spn


def test_region_contains_longitude_across_zero_boundary() -> None:
    region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon")

    assert region.crosses_lon_boundary is True
    assert region.lon_span == 20.0
    assert region.contains_lon(355)
    assert region.contains_lon(-5)
    assert region.contains(5, 0)
    assert not region.contains(20, 0)
    assert not region.contains(355, 8)


def test_region_contains_longitude_after_domain_conversion() -> None:
    region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon").to_lon_domain(
        "-180_180"
    )

    assert region.lon == (-10.0, 10.0)
    assert region.crosses_lon_boundary is False
    assert region.lon_span == 20.0
    assert region.contains_lon(355)
    assert region.contains_lon(-5)
    assert not region.contains_lon(20)


def test_region_accepts_minus180_180_domain_alias() -> None:
    region = spn.Region(lon=(350, 10), lat=(-5, 5), body="moon").to_lon_domain(
        "minus180_180"
    )

    assert region.lon_domain == "-180_180"
    assert region.lon == (-10.0, 10.0)
    assert region.contains_lon(355)
    assert region.to_metadata()["lon_domain"] == "-180_180"
