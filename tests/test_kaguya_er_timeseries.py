from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import sopran as spn
from sopran.core.data import SopranArray
from sopran.core.schema import VariableSchema
from sopran.experimental.kaguya import er_timeseries

xr = pytest.importorskip("xarray")


def _spectrum(name: str) -> SopranArray:
    times = np.arange(
        np.datetime64("2008-01-01T00:00:00", "ns"),
        np.datetime64("2008-01-01T00:00:16", "ns"),
        np.timedelta64(2, "s"),
    )
    energy = np.asarray([30.0, 60.0, 120.0, 240.0])
    pitch = np.linspace(11.25, 168.75, 8)
    values = np.full((times.size, energy.size, pitch.size), 10.0)
    array = xr.DataArray(
        values,
        dims=("time", "energy", "pitch_angle"),
        coords={
            "time": times,
            "energy_eV": (
                ("time", "energy"),
                np.broadcast_to(energy, (times.size, energy.size)),
            ),
            "pitch_angle": pitch,
            "exposure": (("time", "energy", "pitch_angle"), np.ones_like(values)),
            "pace_data_mode": ("time", np.full(times.size, 0x14)),
        },
        attrs={
            "value": "counts",
            "units": "count",
            "count_correction": "event_trash",
            "pitch_edges": np.linspace(0.0, 180.0, 9).tolist(),
        },
    )
    array.coords["exposure"].attrs["mode"] = "calibrated"
    return SopranArray(
        name=name,
        time=spn.period("2008-01-01", "2008-01-01T00:00:16"),
        schema=VariableSchema(
            name=name,
            dims=("time", "energy", "pitch_angle"),
            units="count",
        ),
        xr=array,
    )


def _vector(name: str, values: np.ndarray) -> SopranArray:
    times = np.arange(
        np.datetime64("2008-01-01T00:00:00", "ns"),
        np.datetime64("2008-01-01T00:00:16", "ns"),
        np.timedelta64(2, "s"),
    )
    array = xr.DataArray(
        np.broadcast_to(values, (times.size, 3)),
        dims=("time", "component"),
        coords={"time": times, "component": ["x", "y", "z"]},
    )
    return SopranArray(
        name=name,
        time=spn.period("2008-01-01", "2008-01-01T00:00:16"),
        schema=VariableSchema(name=name, dims=("time", "component")),
        xr=array,
    )


def test_fit_timeseries_integrates_complete_16_second_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    spectra = {"ESA-S1": _spectrum("s1"), "ESA-S2": _spectrum("s2")}
    magnetic = _vector("magnetic_field", np.asarray([8.0, 0.0, 0.0]))
    position = _vector("position", np.asarray([1_738.0, 0.0, 0.0]))
    lmag_data = SimpleNamespace(magnetic_field=magnetic)
    mission = SimpleNamespace(
        store=spn.Store(tmp_path / "store"),
        lmag=SimpleNamespace(load=lambda *args, **kwargs: lmag_data),
    )
    instrument = SimpleNamespace(
        mission=mission,
        pitch_angle_spectra=lambda *args, **kwargs: spectra,
    )
    endpoint = SimpleNamespace(instrument=instrument)
    monkeypatch.setattr(er_timeseries, "lmag_position", lambda data: position)

    seen: list[dict[str, object]] = []

    def fake_fit(observations, *, settings):
        del settings
        seen.append(dict(observations))
        return SimpleNamespace(
            effective_field_nT=40.0,
            delta_u_eff_eV=-15.0,
            representative_b_sc_nT=8.0,
            success=True,
            edge_supported=True,
            to_record=lambda: {
                "success": True,
                "reason": "ok",
                "selected_model": "electrostatic",
                "edge_supported": True,
                "mirror_ratio": 5.0,
                "effective_field_nT": 40.0,
                "delta_u_eff_eV": -15.0,
            },
        )

    monkeypatch.setattr(er_timeseries, "fit_global_joint_effective_field", fake_fit)
    progress: list[tuple[int, int]] = []

    result = er_timeseries.fit_effective_field_timeseries(
        endpoint,
        spn.period("2008-01-01", "2008-01-01T00:00:16"),
        workers=1,
        cache="refresh",
        download="never",
        progress=lambda completed, total: progress.append((completed, total)),
    )

    frame = result.to_pandas()
    assert len(frame) == 1
    assert frame.loc[0, "records_integrated"] == 8
    assert frame.loc[0, "fit_status"] == "complete"
    assert frame.loc[0, "effective_field"] == pytest.approx(40.0)
    assert progress == [(1, 1)]
    assert len(seen) == 1
    assert len(seen[0]) == 16
    assert {item.sensor_group for item in seen[0].values()} == {"ESA-S1", "ESA-S2"}
    for observation in seen[0].values():
        assert observation.metadata["integrated_records"] == 1
        np.testing.assert_allclose(observation.counts, 10.0)
        np.testing.assert_allclose(observation.exposure, 1.0)
    record = mission.store.dataset(
        "experimental.kaguya.er.global_joint_effective_field",
        layer="features",
        variant_id=result.variant_id,
    )
    assert record.manifest()["producer"] == "sopran.experimental.kaguya.er.global_joint_timeseries"

    monkeypatch.setattr(
        er_timeseries,
        "fit_global_joint_effective_field",
        lambda *args, **kwargs: pytest.fail("covering Store result should skip fitting"),
    )
    cached = er_timeseries.fit_effective_field_timeseries(
        endpoint,
        spn.period("2008-01-01", "2008-01-01T00:00:16"),
        workers=1,
        cache="use",
        download="never",
    )
    assert cached.to_pandas()["effective_field"].tolist() == pytest.approx([40.0])

    monkeypatch.setattr(er_timeseries, "fit_global_joint_effective_field", fake_fit)
    lmag_data.magnetic_field = _vector(
        "magnetic_field", np.asarray([9.0, 0.0, 0.0])
    )
    changed_geometry = er_timeseries.fit_effective_field_timeseries(
        endpoint,
        spn.period("2008-01-01", "2008-01-01T00:00:16"),
        workers=1,
        cache="use",
        download="never",
    )
    assert changed_geometry.variant_id != result.variant_id
    assert len(seen) == 2


def test_window_skip_reason_rejects_mode_change() -> None:
    spectrum = _spectrum("s1").to_xarray()
    spectrum.coords["pace_data_mode"].values[-1] = 0x24
    reason = er_timeseries._window_skip_reason(
        np.arange(8),
        arrays={"ESA-S1": spectrum},
    )

    assert reason == "ESA-S1_pace_data_mode_changed"


def test_window_groups_include_missing_utc_windows() -> None:
    times = np.asarray(
        ["2008-01-01T00:00:00", "2008-01-01T00:00:34"],
        dtype="datetime64[ns]",
    )

    groups = er_timeseries._window_groups(
        times,
        16.0,
        time=spn.period("2008-01-01", "2008-01-01T00:00:48"),
    )

    assert [indices.size for _, indices in groups] == [1, 0, 1]


def test_window_groups_use_centers_for_partial_time_ranges() -> None:
    times = np.asarray(["2008-01-01T00:00:00"], dtype="datetime64[ns]")

    groups = er_timeseries._window_groups(
        times,
        16.0,
        time=spn.period("2008-01-01T00:00:09", "2008-01-01T00:00:31"),
    )

    assert len(groups) == 1
    assert groups[0][1].size == 0


def test_input_fingerprint_includes_counts_and_exposure_mode() -> None:
    first = _spectrum("s1").to_xarray()
    changed_counts = first.copy(deep=True)
    changed_counts.values[0, 0, 0] = 99.0
    changed_mode = first.copy(deep=True)
    changed_mode.coords["exposure"].attrs["mode"] = "relative"
    kwargs = {
        "files": (),
        "magnetic": np.ones((8, 3)),
        "position": np.ones((8, 3)),
        "frame_context": None,
    }

    baseline = er_timeseries._input_fingerprint(arrays={"ESA-S1": first}, **kwargs)

    assert baseline != er_timeseries._input_fingerprint(
        arrays={"ESA-S1": changed_counts}, **kwargs
    )
    assert baseline != er_timeseries._input_fingerprint(
        arrays={"ESA-S1": changed_mode}, **kwargs
    )


def test_sparse_window_is_left_for_likelihood_support_validation() -> None:
    spectrum = _spectrum("s1").to_xarray().isel(time=[0, 2, 4, 6])
    reason = er_timeseries._window_skip_reason(
        np.arange(4),
        arrays={"ESA-S1": spectrum},
    )

    assert reason is None


def test_affected_side_change_is_left_for_record_likelihood() -> None:
    spectrum = _spectrum("s1").to_xarray()

    reason = er_timeseries._window_skip_reason(
        np.arange(8),
        arrays={"ESA-S1": spectrum},
    )

    assert reason is None


def test_fit_timeseries_retains_windows_when_archive_has_no_records(tmp_path) -> None:
    spectra = {
        "ESA-S1": SopranArray(
            name="s1",
            time=spn.period("2008-01-01", "2008-01-01T00:00:32"),
            schema=_spectrum("s1").schema,
            xr=_spectrum("s1").to_xarray().isel(time=slice(0, 0)),
        ),
        "ESA-S2": SopranArray(
            name="s2",
            time=spn.period("2008-01-01", "2008-01-01T00:00:32"),
            schema=_spectrum("s2").schema,
            xr=_spectrum("s2").to_xarray().isel(time=slice(0, 0)),
        ),
    }
    mission = SimpleNamespace(
        store=spn.Store(tmp_path / "store"),
        lmag=SimpleNamespace(
            load=lambda *args, **kwargs: pytest.fail("LMAG is not needed without records")
        ),
    )
    endpoint = SimpleNamespace(
        instrument=SimpleNamespace(
            mission=mission,
            pitch_angle_spectra=lambda *args, **kwargs: spectra,
        )
    )

    result = er_timeseries.fit_effective_field_timeseries(
        endpoint,
        spn.period("2008-01-01", "2008-01-01T00:00:32"),
        workers=1,
        cache="never",
        download="never",
    )

    frame = result.to_pandas()
    assert len(frame) == 2
    assert frame["fit_status"].tolist() == ["skipped", "skipped"]
    assert frame["fit_error"].tolist() == [
        "no_records",
        "no_records",
    ]
