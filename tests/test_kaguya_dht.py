"""Velocity convention, look shift and shifted-frame binning of the dHT adapter."""

from __future__ import annotations

import contextlib
import sys
import types
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

import sopran as spn
import sopran.experimental.kaguya.dht as dht
from sopran.core.data import SopranArray
from sopran.core.schema import VariableSchema
from sopran.missions.kaguya.pace import PaceCalibration, PaceData, PaceRecord

MOON_RADIUS_KM = 1737.4


def test_gse_basis_is_orthonormal_with_x_toward_the_sun() -> None:
    sun = np.array([[1.0, 2.0, 0.5], [0.0, 1.0, 0.0]])
    basis = dht.gse_basis_j2000(sun)
    for row, direction in zip(basis, sun, strict=True):
        np.testing.assert_allclose(row.T @ row, np.eye(3), atol=1e-12)
        np.testing.assert_allclose(row[:, 0], direction / np.linalg.norm(direction))
        assert row[:, 2] @ dht._ECLIPTIC_NORTH_J2000 > 0.9


def test_tangential_velocity_matches_numpy_and_rejects_tangent_fields(monkeypatch) -> None:
    plasma = np.array([[400.0, 10.0, -5.0], [400.0, 0.0, 0.0]])
    magnetic = np.array([[20.0, 4.0, 10.0], [1.0, 0.0, 0.001]])
    normal = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])
    velocity, ok, fraction = dht.dht_tangential_velocity(plasma, magnetic, normal)
    assert ok.tolist() == [True, False]
    assert abs(velocity[0, 2]) < 1e-9 and np.isnan(velocity[1]).all()
    assert fraction[1] < 0.15
    monkeypatch.setattr(dht, "_native_module", lambda: None)
    numpy_velocity, numpy_ok, numpy_fraction = dht.dht_tangential_velocity(plasma, magnetic, normal)
    np.testing.assert_allclose(numpy_velocity[0], velocity[0])
    assert numpy_ok.tolist() == ok.tolist()
    np.testing.assert_allclose(numpy_fraction, fraction)


def test_moon_frame_boost_follows_the_validated_order() -> None:
    plasma = np.array([[400.0, 20.0, 30.0]])
    moon = np.array([[1.0, 2.0, 3.0]])
    spacecraft = np.array([[0.2, 0.3, 0.4]])
    magnetic = np.array([[1.0, 0.0, 1.0]])
    normal = np.array([[0.0, 0.0, 1.0]])

    def boost(p, m, s):
        ht, ok, _ = dht.dht_tangential_velocity(p - m, magnetic, normal)
        assert ok.all()
        return ht - s

    np.testing.assert_allclose(boost(plasma, moon, spacecraft), [[371.8, 17.7, -0.4]])
    np.testing.assert_allclose(
        np.sum((boost(plasma, moon, spacecraft) + spacecraft) * normal, axis=1), 0.0, atol=1e-12
    )
    shift = np.array([[12.0, -30.0, 1.0]])
    np.testing.assert_allclose(
        boost(plasma + shift, moon + shift, spacecraft), boost(plasma, moon, spacecraft)
    )
    np.testing.assert_allclose(boost(plasma, 0 * moon, 0 * spacecraft), [[370.0, 20.0, 0.0]])
    restored = boost(plasma + np.array(dht.OMNI_ABERRATION_CORRECTION_KM_S), moon, spacecraft)
    np.testing.assert_allclose(restored - boost(plasma, moon, spacecraft), [[0.0, 29.8, 0.0]])


def test_shift_looks_keeps_zero_frame_and_raises_energy_against_the_flow() -> None:
    energy = np.array([[100.0, 100.0]])
    theta = np.zeros((1, 2))
    phi = np.array([[0.0, 180.0]])
    magnetic = np.array([[1.0, 0.0, 0.0]])
    pitch, shifted, ok = dht.shift_looks(energy, theta, phi, magnetic, np.zeros((1, 3)))
    assert ok.all()
    np.testing.assert_allclose(pitch, [[0.0, 180.0]], atol=1e-9)
    np.testing.assert_allclose(shifted, energy)
    speed = dht.ELECTRON_SPEED_KM_S_PER_SQRT_EV * 10.0
    _, shifted, ok = dht.shift_looks(energy, theta, phi, magnetic, [[-0.1 * speed, 0.0, 0.0]])
    np.testing.assert_allclose(shifted, [[121.0, 81.0]], atol=1e-6)
    numpy_pitch, numpy_energy, numpy_ok = dht._shift_looks_numpy(
        energy, theta, phi, magnetic, np.array([[-0.1 * speed, 0.0, 0.0]]), 1.0
    )
    np.testing.assert_allclose(numpy_energy, shifted, atol=1e-6)
    assert numpy_ok.all()


def test_lunar_arrival_shift_uses_bow_shock_nose_and_moon_x() -> None:
    arrival, correction = dht.lunar_arrival_times(
        [0.0, 300.0], [13.0, 13.0], [400.0, 0.0], [-380_000.0, -380_000.0]
    )
    expected = (dht.EARTH_RADIUS_KM * 13.0 + 380_000.0) / 400.0
    assert correction[0] == pytest.approx(expected)
    assert arrival[0] == pytest.approx(expected)
    assert np.isnan(arrival[1])


def _omni_table(vx: float, vy: float, vz: float, start: float, count: int = 4) -> pd.DataFrame:
    times = pd.to_datetime(start + 300.0 * np.arange(count), unit="s", utc=True)
    return pd.DataFrame(
        {
            "vx_gse": np.full(count, vx),
            "vy_gse": np.full(count, vy),
            "vz_gse": np.full(count, vz),
            "speed": np.full(count, 400.0),
            "bsn_x": np.full(count, 13.0),
        },
        index=pd.DatetimeIndex(times, name="time"),
    )


class _FakeContext:
    """Identity frames with the kernel list of a real FrameContext."""

    spice_kernels = ()

    def transform_vectors(self, vectors, *, times, source_frame, target_frame, missing="error"):
        return np.asarray(vectors, dtype=float)


def _install_fake_spice(monkeypatch, moon_velocity, sc_velocity, sun_direction=(1.0, 0.0, 0.0)):
    module = types.ModuleType("spiceypy")

    def str2et(text: str) -> float:
        return datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()

    def spkpos(target, et, frame, correction, observer):
        assert target == "SUN" and observer == "EARTH"
        return np.asarray(sun_direction, dtype=float) * 1.5e8, 500.0

    def spkezr(target, et, frame, correction, observer):
        if target == "MOON":
            return np.concatenate(([1.0, 2.0, 3.0], moon_velocity)), 1.0
        assert target == "-131" and observer == "MOON"
        return np.concatenate(([4.0, 5.0, 6.0], sc_velocity)), 0.1

    module.str2et = str2et
    module.spkpos = spkpos
    module.spkezr = spkezr
    module.reset = lambda: None
    monkeypatch.setitem(sys.modules, "spiceypy", module)
    monkeypatch.setattr(
        dht, "spice_kernel_context", lambda spice, kernels: contextlib.nullcontext()
    )


def test_frame_velocity_restores_aberration_and_subtracts_orbital_motion(monkeypatch) -> None:
    _install_fake_spice(monkeypatch, moon_velocity=[0.0, 0.0, 0.0], sc_velocity=[0.0, 0.0, 0.0])
    start = 1_207_008_000.0 + 1000.0
    times = np.array([start + 10.0, start + 20.0])
    magnetic = np.array([[5.0, 0.0, 0.0], [0.0, 5.0, 0.0]])
    position = np.array([[MOON_RADIUS_KM + 100.0, 0.0, 0.0]] * 2)
    position_gse = np.array([[-380_000.0, 0.0, 0.0]] * 2)
    omni = _omni_table(
        -400.0, 0.0, 0.0, start=start - (dht.EARTH_RADIUS_KM * 13.0 + 380_000.0) / 400.0
    )
    result = dht.frame_velocity(
        times,
        magnetic_field_me_nT=magnetic,
        position_me_km=position,
        position_gse_km=position_gse,
        omni=omni,
        frame_context=_FakeContext(),
        look_frame="MOON_ME",
    )
    assert result.status.tolist() == ["ok", "field_tangent"]
    expected = dht.gse_basis_j2000([[1.0, 0.0, 0.0]])[0] @ np.array([0.0, 29.8, 0.0])
    np.testing.assert_allclose(result.velocity_look_frame_km_s[0], expected, atol=1e-9)
    assert expected[1] > 27.0 and expected[2] > 11.0
    assert np.isnan(result.velocity_look_frame_km_s[1]).all()
    assert result.coverage()["ok"] == 1 and result.coverage()["field_tangent"] == 1
    assert result.omni_dt_seconds[0] == pytest.approx(10.0, abs=1e-6)

    _install_fake_spice(monkeypatch, moon_velocity=[0.0, 1.0, 0.0], sc_velocity=[0.0, 0.0, 1.6])
    moved = dht.frame_velocity(
        times[:1],
        magnetic_field_me_nT=magnetic[:1],
        position_me_km=position[:1],
        position_gse_km=position_gse[:1],
        omni=omni,
        frame_context=_FakeContext(),
        look_frame="MOON_ME",
        settings=dht.DhtSettings(restore_omni_aberration=False),
    )
    np.testing.assert_allclose(moved.velocity_look_frame_km_s[0], [0.0, -1.0, -1.6], atol=1e-9)
    assert moved.moon_speed_km_s[0] == pytest.approx(1.0)

    empty = dht.frame_velocity(
        times[:1],
        magnetic_field_me_nT=magnetic[:1],
        position_me_km=position[:1],
        position_gse_km=position_gse[:1],
        omni=omni.iloc[:0],
        frame_context=_FakeContext(),
    )
    assert empty.status.tolist() == ["omni_missing"]


def _pace(sample_time: float) -> tuple[PaceData, PaceCalibration]:
    counts = np.zeros((32, 4, 16), dtype=np.uint16)
    counts[0, 0, 0] = 5
    counts[0, 0, 8] = 7
    counts[3, 0, 0] = 11
    record = PaceRecord(
        type=0x01, index=0, arrays={"cnt": counts, "trash": np.zeros((32, 4, 2), np.uint16)}
    )
    header = {
        "time": sample_time,
        "mode": 0x14,
        "type": 0x01,
        "sensor": 0,
        "svs_tbl": 0,
        "sampl_time": 16000,
        "time_resolution": 16000,
        "data_quality": 0,
    }
    pace = PaceData(
        sensor=0,
        headers=(header,),
        records={0x01: (record,)},
        source_files=(),
        record_order=(record,),
    )
    fov = {
        "az16": np.linspace(0.0, 360.0, 16, endpoint=False),
        "az64": np.linspace(0.0, 360.0, 64, endpoint=False),
        "ene": np.broadcast_to(np.geomspace(0.02, 2.0, 32), (8, 32)).copy(),
        "pol4": np.zeros((8, 32, 4)),
        "pol16": np.zeros((8, 32, 16)),
    }
    return pace, PaceCalibration(fov={0: fov})


def _vector_array(times, values, name, units, frame="MOON_ME"):
    xr = pytest.importorskip("xarray")
    array = xr.DataArray(
        np.asarray(values, dtype=float),
        dims=("time", "component"),
        coords={"time": times},
        attrs={"units": units, "frame": frame},
    )
    return SopranArray(
        name=name,
        time=spn.day("2008-04-01"),
        schema=VariableSchema(name=name, dims=("time", "component"), units=units, frame=frame),
        xr=array,
    )


def test_dht_spectrum_with_zero_boost_reproduces_plain_binning(monkeypatch) -> None:
    pytest.importorskip("xarray")
    _install_fake_spice(monkeypatch, moon_velocity=[0.0, 0.0, 0.0], sc_velocity=[0.0, 0.0, 0.0])
    sample = datetime(2008, 4, 1, 1, 0, tzinfo=UTC).timestamp()
    pace, calibration = _pace(sample)
    times = np.array([sample - 2.0, sample + 2.0]).astype("datetime64[s]").astype("datetime64[ns]")
    magnetic = _vector_array(times, [[1.0, 0.0, 0.0]] * 2, "magnetic_field", "nT")
    position = _vector_array(times, [[MOON_RADIUS_KM + 100.0, 0.0, 0.0]] * 2, "position", "km")
    gse = _vector_array(times, [[-380_000.0, 0.0, 0.0]] * 2, "position_gse", "km", frame="GSE")
    omni = _omni_table(
        0.0,
        0.0,
        0.0,
        start=sample - (dht.EARTH_RADIUS_KM * 13.0 + 380_000.0) / 400.0 - 600.0,
        count=8,
    )
    result = dht.dht_pitch_angle_spectrum(
        pace=pace,
        time=spn.day("2008-04-01"),
        calibration=calibration,
        magnetic_field=magnetic,
        position=position,
        position_gse=gse,
        omni=omni,
        frame_context=_FakeContext(),
        energy_edges_eV=[10.0, 100.0, 1000.0, 3000.0],
        pitch_bins=2,
        settings=dht.DhtSettings(restore_omni_aberration=False),
    )
    array = result.spectrum.to_xarray()
    assert result.frame.status.tolist() == ["ok"]
    assert array.dims == ("time", "energy", "pitch_angle")
    assert array.shape == (1, 3, 2)
    assert np.nansum(array.values) == pytest.approx(23.0)
    energies = np.geomspace(0.02, 2.0, 32) * 1000.0
    band_of_first = np.searchsorted([10.0, 100.0, 1000.0, 3000.0], energies[0], side="right") - 1
    assert array.values[0, band_of_first, 0] == pytest.approx(16.0)
    assert array.values[0, band_of_first, 1] == pytest.approx(7.0)
    assert np.all(array.coords["exposure"].values[np.isfinite(array.values)] > 0.0)
    assert array.attrs["frame_policy"] == dht.FRAME_POLICY
    assert array.attrs["coverage"]["ok"] == 1
    assert result.spectrum.metadata["operations"][0]["operation"] == "dht_pitch_angle_spectrum"


def test_settings_reject_invalid_values() -> None:
    with pytest.raises(ValueError):
        dht.DhtSettings(min_abs_b_normal_fraction=-1.0)
    with pytest.raises(ValueError):
        dht.DhtSettings(look_sign=2.0)
    with pytest.raises(ValueError):
        dht.DhtSettings(arrival_shift="linear")
