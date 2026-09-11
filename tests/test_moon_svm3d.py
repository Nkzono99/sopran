from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import sopran.bodies.moon.svm3d as svm3d_module
from sopran.bodies.moon.svm3d import (
    MOON_MEAN_RADIUS_KM,
    SVM3DShellGrid,
    SVM3DTraceSettings,
    cartesian_to_lon_lat_alt,
    lon_lat_alt_to_cartesian,
)


def _linear_shell_grid() -> SVM3DShellGrid:
    longitude = np.array([0.0, 180.0])
    latitude = np.array([-90.0, 0.0, 90.0])
    altitude = np.array([6.0, 100.0, 200.0])
    values = np.zeros((3, 3, 2, 3), dtype=np.float64)
    for index, altitude_km in enumerate(altitude):
        values[index, ..., 0] = -(2.0 - altitude_km / 100.0)
    return SVM3DShellGrid(
        longitude_deg=longitude,
        latitude_deg=latitude,
        altitude_km=altitude,
        field_me_nT=values,
        metadata={"fixture": True},
    )


def test_shell_grid_load_and_interpolation_are_periodic(tmp_path: Path) -> None:
    grid = _linear_shell_grid()
    path = tmp_path / "shell.npz"
    np.savez_compressed(
        path,
        lon_deg=grid.longitude_deg,
        lat_deg=grid.latitude_deg,
        alt_km=grid.altitude_km,
        field_me_nT=grid.field_me_nT,
        metadata_json='{"fixture": true}',
    )

    loaded = SVM3DShellGrid.load(path)
    values = loaded.interpolate([0.0, 360.0], [0.0, 0.0], [50.0, 50.0])

    np.testing.assert_allclose(values[:, 0], [-1.5, -1.5])
    np.testing.assert_allclose(values[:, 1:], 0.0)
    assert loaded.metadata == {"fixture": True}
    with pytest.raises(ValueError, match="outside"):
        loaded.interpolate(0.0, 0.0, 300.0, bounds="raise")


def test_shell_grid_build_uses_adaptive_rows_and_roundtrips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "svm.dat"
    source.write_bytes(b"fixture")
    calls: list[np.ndarray] = []

    def evaluate_fixture(
        source_path: Path | str,
        positions_me_km: np.ndarray,
        *,
        min_altitude_km: float,
    ) -> np.ndarray:
        assert Path(source_path) == source
        assert min_altitude_km == pytest.approx(6.05)
        calls.append(positions_me_km.copy())
        return positions_me_km / 1000.0

    monkeypatch.setattr(svm3d_module, "evaluate_tsunakawa_svm3d", evaluate_fixture)
    grid = SVM3DShellGrid.build(
        source,
        altitudes_km=(10.0, 20.0),
        longitude_step_deg=45.0,
        latitude_step_deg=90.0,
        adaptive_longitude=True,
    )

    assert grid.field_me_nT.shape == (2, 3, 8, 3)
    assert len(calls) == 2
    assert all(call.shape == (10, 3) for call in calls)
    assert grid.metadata["direct_nodes_per_shell"] == 10
    assert grid.metadata["adaptive_longitude"] is True
    path = grid.save(tmp_path / "built-shell.npz")
    loaded = SVM3DShellGrid.load(path)
    np.testing.assert_allclose(loaded.field_me_nT, grid.field_me_nT)
    assert loaded.metadata == grid.metadata


def test_shell_grid_residual_field_reproduces_spacecraft_measurement() -> None:
    grid = _linear_shell_grid()
    position = np.array([[MOON_MEAN_RADIUS_KM + 100.0, 0.0, 0.0]])
    measured = np.array([[-4.0, 2.0, 1.0]])

    residual = grid.residual_external_field(position, measured)

    np.testing.assert_allclose(grid.field_at(position) + residual, measured)


def test_shell_grid_native_trace_reaches_surface_and_target() -> None:
    grid = _linear_shell_grid()
    position = np.array([[MOON_MEAN_RADIUS_KM + 100.0, 0.0, 0.0]])
    result = grid.trace(
        position,
        np.zeros((1, 3)),
        np.array([1]),
        target_field_nT=np.array([1.5]),
        settings=SVM3DTraceSettings(step_km=1.0, max_steps=150, stop_altitude_km=6.0),
    )

    assert result.valid.tolist() == [True]
    assert result.target_crossed.tolist() == [True]
    assert result.arrays["footpoint_altitude_km"][0] == pytest.approx(6.0)
    assert result.arrays["target_altitude_km"][0] == pytest.approx(50.0, abs=0.1)
    assert result.arrays["maximum_total_nT"][0] == pytest.approx(1.94, rel=0.01)


def test_lunar_cartesian_lon_lat_roundtrip() -> None:
    positions = lon_lat_alt_to_cartesian([20.0, -170.0], [30.0, -45.0], [100.0, 50.0])

    longitude, latitude, altitude = cartesian_to_lon_lat_alt(positions)

    np.testing.assert_allclose(longitude, [20.0, -170.0], atol=1.0e-12)
    np.testing.assert_allclose(latitude, [30.0, -45.0], atol=1.0e-12)
    np.testing.assert_allclose(altitude, [100.0, 50.0], atol=1.0e-12)
