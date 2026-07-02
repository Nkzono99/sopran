from __future__ import annotations

import pytest

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


def test_region_constructor_normalizes_longitudes_to_domain() -> None:
    region = spn.Region(lon=(-10, 10), lat=(-5, 5), body="moon", lon_domain="0_360")

    assert region.lon == (350.0, 10.0)
    assert region.crosses_lon_boundary is True
    assert region.lon_span == 20.0
    assert region.contains_lon(355)
    assert region.contains_lon(-5)
    assert region.to_metadata()["lon"] == [350.0, 10.0]


def test_region_records_longitude_direction_metadata() -> None:
    default_region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")
    west_positive = spn.Region(
        lon=(120, 160),
        lat=(-45, -10),
        body="moon",
        lon_direction="west_positive",
    )

    assert default_region.lon_direction == "east_positive"
    assert default_region.to_metadata()["lon_direction"] == "east_positive"
    assert west_positive.lon_direction == "west_positive"
    assert west_positive.to_metadata()["lon_direction"] == "west_positive"

    with pytest.raises(ValueError, match="lon_direction"):
        spn.Region(
            lon=(120, 160),
            lat=(-45, -10),
            body="moon",
            lon_direction="north_positive",
        )


def test_region_records_latitude_type_metadata() -> None:
    default_region = spn.Region(lon=(120, 160), lat=(-45, -10), body="moon")
    planetographic = spn.Region(
        lon=(120, 160),
        lat=(-45, -10),
        body="moon",
        lat_type="planetographic",
    )

    assert default_region.lat_type == "planetocentric"
    assert default_region.to_metadata()["lat_type"] == "planetocentric"
    assert planetographic.lat_type == "planetographic"
    assert planetographic.to_metadata()["lat_type"] == "planetographic"

    with pytest.raises(ValueError, match="lat_type"):
        spn.Region(
            lon=(120, 160),
            lat=(-45, -10),
            body="moon",
            lat_type="geodetic",
        )
