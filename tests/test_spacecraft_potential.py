"""Spectral edges, adoption rules and gap filling of the spacecraft-potential proxies."""

from __future__ import annotations

import numpy as np
import pytest

from sopran.experimental.kaguya import spacecraft_potential as sp

pl = pytest.importorskip("polars")

ENERGY = 8.0 * 1.4 ** np.arange(14)


def _step(level_low: float, level_high: float, edge_eV: float) -> np.ndarray:
    return np.where(edge_eV > ENERGY, level_low, level_high)


def test_rising_and_falling_edges_are_classified() -> None:
    counts = np.vstack(
        [_step(2.0, 400.0, 40.0), _step(400.0, 2.0, 40.0), np.full(ENERGY.size, 100.0)]
    )
    features = sp.cutoff_features(ENERGY, counts)
    assert features["fit_success"].tolist() == [True, True, False]
    assert features["edge_direction"].tolist() == ["rising", "falling", "none"]
    assert 20.0 < features["cutoff_energy_eV"][0] < 80.0
    assert features["signal_units"][0] == "counts"
    with_flux = sp.cutoff_features(ENERGY, counts, eflux=counts * 1e5)
    assert with_flux["signal_units"][0] == "energy_flux"


def test_proxy_rules_use_the_sign_convention_of_each_edge() -> None:
    counts = np.vstack([_step(2.0, 400.0, 40.0), _step(400.0, 2.0, 40.0)])
    features = sp.cutoff_features(ENERGY, counts)
    table = sp.cutoff_table([100.0, 200.0], features, sensor="esa1", sza_deg=[150.0, 30.0])
    proxies = sp.proxy_table(table)
    assert proxies.height == 2
    rising = proxies.filter(pl.col("source") == "esa1_rising")
    falling = proxies.filter(pl.col("source") == "esa1_falling_photoelectron")
    assert rising["vsc_proxy_V"][0] < 0.0 and rising["valid_regime"][0] == "nightside"
    assert falling["vsc_proxy_V"][0] > 0.0 and falling["valid_regime"][0] == "dayside"
    assert rising["sza_deg"][0] == 150.0
    assert sp.proxy_table(table, use_dayside_photoelectron=False)["use_for_estimate"].to_list() == [
        True,
        False,
    ]


def test_ion_peak_is_a_diagnostic_by_default() -> None:
    energy = 5.0 * 1.4 ** np.arange(16)
    counts = 50.0 * np.exp(-(((np.log(energy) - np.log(40.0)) / 0.8) ** 2)) + 0.5
    features = sp.ion_peak_features(energy, counts[None, :])
    assert features["fit_success"].tolist() == [True]
    assert abs(features["peak_energy_eV"][0] - 40.0) < 15.0
    proxies = sp.ion_proxy_table([10.0], features, sensor="iea")
    assert proxies["use_for_estimate"].to_list() == [False]
    assert proxies["vsc_proxy_V"][0] == pytest.approx(-features["peak_energy_eV"][0])


def test_regimes_follow_sza_thresholds() -> None:
    assert sp.potential_regime([10.0, 100.0, 150.0, np.nan]).tolist() == [
        "dayside",
        "terminator",
        "nightside",
        "unknown",
    ]


def _proxies(rows: list[tuple[float, float, str, str, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "time_unix": [row[0] for row in rows],
            "sza_deg": [row[4] for row in rows],
            "sensor": ["ESA1"] * len(rows),
            "source": [row[2] for row in rows],
            "kind": ["x"] * len(rows),
            "vsc_proxy_V": [row[1] for row in rows],
            "vsc_proxy_sigma_V": [5.0] * len(rows),
            "vsc_proxy_quality": [1.5] * len(rows),
            "use_for_estimate": [True] * len(rows),
            "valid_regime": [row[3] for row in rows],
        }
    )


def test_estimate_prefers_direct_then_smoothed_then_prior_then_global() -> None:
    proxies = _proxies(
        [
            (1000.0, -30.0, "esa1_rising", "nightside", 150.0),
            (1500.0, -34.0, "esa1_rising", "nightside", 150.0),
            (2000.0, -32.0, "esa1_rising", "nightside", 150.0),
            (5000.0, 12.0, "esa1_falling_photoelectron", "dayside", 30.0),
        ]
    )
    events = pl.DataFrame(
        {
            "time_unix": [1010.0, 2600.0, 40000.0, 5005.0, 90000.0],
            "sza_deg": [150.0, 150.0, 150.0, 30.0, 100.0],
        }
    )
    settings = sp.PotentialEstimateSettings(
        direct_tolerance_seconds=30.0, gapfill_max_gap_seconds=1200.0
    )
    out = sp.estimate_potential(events, proxies, settings=settings).sort("time_unix")
    assert out["vsc_method"].to_list() == [
        "direct_proxy",
        "time_smoothed_proxy",
        "direct_proxy",
        "condition_prior",
        "global_prior",
    ]
    assert out["vsc_est_V"].to_list() == pytest.approx([-30.0, -33.0, 12.0, -32.0, 0.0])
    assert out["vsc_direct_proxy_source"][0] == "esa1_rising"
    assert out["vsc_sigma_V"][4] == pytest.approx(60.0)


def test_estimate_without_proxies_falls_back_to_the_global_prior() -> None:
    events = pl.DataFrame({"time_unix": [1.0], "sza_deg": [20.0]})
    out = sp.estimate_potential(events, sp._empty_proxies())
    assert out["vsc_method"].to_list() == ["global_prior"]
    with pytest.raises(ValueError, match="time_unix"):
        sp.estimate_potential(pl.DataFrame({"t": [1.0]}), sp._empty_proxies())


def test_energy_spectra_sums_looks() -> None:
    xr = pytest.importorskip("xarray")
    times = np.array(["2008-04-01T00:00:00", "2008-04-01T00:00:02"], dtype="datetime64[ns]")
    counts = np.ones((2, 4, 3))
    dataset = xr.Dataset(
        {"counts": (("time", "energy", "look"), counts)},
        coords={"time": times, "energy": [10.0, 20.0, 40.0, 80.0], "look": [0, 1, 2]},
    )
    unix, energy, summed, flux = sp.energy_spectra(dataset)
    assert unix[0] == pytest.approx(1207008000.0)
    assert energy.shape == (2, 4) and summed.shape == (2, 4)
    assert np.all(summed == 3.0) and flux is None
