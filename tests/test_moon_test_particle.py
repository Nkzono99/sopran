from __future__ import annotations

import numpy as np
import pytest

from sopran.experimental.moon.svm3d import MOON_MEAN_RADIUS_KM, SVM3DShellGrid
from sopran.experimental.moon.test_particle import (
    TestParticleSettings,
    electron_velocity_me,
    gyro_period_s,
    trace_test_particles,
)


def _zero_grid() -> SVM3DShellGrid:
    return SVM3DShellGrid(
        longitude_deg=np.array([0.0, 180.0]),
        latitude_deg=np.array([-90.0, 0.0, 90.0]),
        altitude_km=np.array([0.0, 500.0, 1000.0]),
        field_me_nT=np.zeros((3, 3, 2, 3)),
    )


def test_uniform_field_orbit_returns_to_the_start_ring() -> None:
    settings = TestParticleSettings.for_field(
        10.0,
        steps_per_gyration=120,
        gyrations=2.5,
        stop_altitude_km=1.0,
        escape_altitude_km=5000.0,
        return_radius_km=0.75,
        min_return_steps=20,
        svm_scale=0.0,
    )
    assert settings.dt_s == pytest.approx(float(gyro_period_s(10.0)) / 120.0)
    result = trace_test_particles(
        _zero_grid(),
        [[MOON_MEAN_RADIUS_KM + 100.0, 0.0, 0.0]],
        [[1000.0, 0.0, 0.0]],
        [[0.0, 0.0, 10.0]],
        settings=settings,
    )
    assert result.status.tolist() == ["returned"]
    assert result.arrays["closest_sc_distance_km"][0] < 0.75
    assert result.counts()["returned"] == 1
    frame = result.to_pandas()
    assert {"status", "final_r_me_km_x", "path_km"} <= set(frame.columns)


def test_field_free_orbit_hits_the_surface() -> None:
    settings = TestParticleSettings(
        dt_s=1.0,
        max_steps=50,
        stop_altitude_km=5.0,
        escape_altitude_km=5000.0,
        return_radius_km=5.0,
        min_return_steps=10,
        svm_scale=0.0,
    )
    result = trace_test_particles(
        _zero_grid(),
        [[MOON_MEAN_RADIUS_KM + 30.0, 0.0, 0.0]],
        [[-2.0, 0.0, 0.0]],
        [[0.0, 0.0, 0.0]],
        settings=settings,
    )
    assert result.status.tolist() == ["surface_hit"]
    assert result.arrays["min_alt_km"][0] <= 5.0
    with pytest.raises(ValueError):
        trace_test_particles(
            _zero_grid(), [[1.0, 0.0, 0.0]], [[1.0, 0.0]], [[0.0, 0.0, 0.0]], settings=settings
        )


def test_electron_velocity_has_the_requested_pitch_angle() -> None:
    field = np.array([[0.0, 0.0, 10.0], [3.0, 4.0, 0.0]])
    velocity = electron_velocity_me([100.0, 400.0], [30.0, 120.0], [0.0, 90.0], field)
    speed = np.linalg.norm(velocity, axis=1)
    np.testing.assert_allclose(speed, 593.0967822173509 * np.sqrt([100.0, 400.0]))
    cosine = np.sum(velocity * field, axis=1) / (speed * np.linalg.norm(field, axis=1))
    np.testing.assert_allclose(np.rad2deg(np.arccos(cosine)), [30.0, 120.0])
    with pytest.raises(ValueError):
        TestParticleSettings(dt_s=0.0, max_steps=1)
