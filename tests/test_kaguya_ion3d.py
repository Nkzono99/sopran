from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from sopran.core.time import day
from sopran.missions.kaguya.ion3d import PROTON_MASS_EV, pace_ion_3d
from sopran.missions.kaguya.pace import PaceCalibration, PaceData, PaceRecord, _init_info

T0 = datetime(2009, 2, 17, 12, 0, 0, tzinfo=UTC).timestamp()
ENERGY_KEV = np.geomspace(0.01, 10.0, 32)
POLAR = np.array([11.25, 33.75, 56.25, 78.75])
POLAR16 = np.linspace(2.8125, 87.1875, 16)
ENESQ = np.arange(32)[::-1]  # table row i holds energy step 31 - i
POLSQ4 = np.array([1, 0, 3, 2])


def _info(sensor: int) -> dict[str, np.ndarray]:
    info = _init_info(sensor)
    az16 = np.arange(16) * 22.5 + 11.25
    az64 = np.arange(64) * 5.625 + 2.8125
    for key, polar, azimuth, polsq in (
        ("4x16", POLAR, az16, POLSQ4),
        ("16x64", POLAR16, az64, np.arange(16)),
    ):
        shape = info[f"ene_{key}"].shape[1:]
        # table order: row i is energy step ENESQ[i], column j is polar step polsq[j]
        info[f"ene_{key}"][0] = np.broadcast_to(ENERGY_KEV[ENESQ][:, None, None], shape)
        info[f"pol_{key}"][0] = np.broadcast_to(polar[polsq][None, :, None], shape)
        info[f"az_{key}"][0] = np.broadcast_to(azimuth[None, None, :], shape)
        info[f"gfactor_{key}"][0] = 1e-4
        info[f"ene_sqno_{key}"][0] = np.broadcast_to(ENESQ[:, None, None], shape)
        info[f"pol_sqno_{key}"][0] = np.broadcast_to(polsq[None, :, None], shape)
    return info


def _pace(sensor: int, record_type: int, arrays: dict[str, np.ndarray], *, n: int = 1) -> PaceData:
    headers, records = [], []
    for i in range(n):
        headers.append(
            dict(
                type=record_type,
                time=T0 + 16.0 * i,
                time_resolution=16000,
                sampl_time=512,
                svs_tbl=0,
            )
        )
        records.append(PaceRecord(type=record_type, index=i, arrays=arrays))
    return PaceData(
        sensor=sensor,
        headers=tuple(headers),
        records={record_type: tuple(records)},
        source_files=(),
        record_order=tuple(records),
    )


def _calibration(sensor: int) -> PaceCalibration:
    return PaceCalibration(info={sensor: _info(sensor)})


def test_iea_counts_and_grid_follow_the_spedas_sequence_remap() -> None:
    cnt = np.arange(32 * 4 * 16, dtype=np.uint16).reshape(32, 4, 16)
    pace = _pace(
        3,
        0x80,
        {"cnt": cnt, "event": np.zeros(16, np.uint32), "trash": np.zeros((32, 4, 2), np.uint16)},
    )
    d = pace_ion_3d(pace, _calibration(3))[0x80]
    assert d.counts.shape == (1, 32, 64)
    grid = d.grids[0]
    for i, j, k in ((0, 0, 0), (5, 2, 7), (31, 3, 15)):
        step, polar = ENESQ[i], POLSQ4[j]
        b = polar + k * 4  # sabin: bin = polar + azimuth * n_polar
        assert d.counts[0, step, b] == cnt[i, j, k]
        assert grid.energy_eV[step, b] == pytest.approx(ENERGY_KEV[step] * 1000.0)
        assert grid.theta_deg[step, b] == pytest.approx(POLAR[polar])
    assert np.all(np.diff(grid.energy_eV[:, 0]) > 0)
    assert np.all(grid.denergy_eV > 0)
    assert d.integration_s[0] == pytest.approx(16.0 / 512)


def test_units_and_moments_match_the_spedas_formulas() -> None:
    cnt = np.zeros((32, 4, 16), np.uint16)
    cnt[ENESQ.tolist().index(20), POLSQ4.tolist().index(2), 3] = 50  # energy step 20, polar step 2
    pace = _pace(
        3,
        0x80,
        {"cnt": cnt, "event": np.zeros(16, np.uint32), "trash": np.zeros((32, 4, 2), np.uint16)},
    )
    d = pace_ion_3d(pace, _calibration(3))[0x80]
    g = d.grids[0]
    b = 2 + 3 * 4
    dt, gf, energy = 16.0 / 512, 1e-4 * 0.6, g.energy_eV[20, b]
    assert d.to_units("eflux")[0, 20, b] == pytest.approx(50 / (dt * gf))
    assert d.to_units("flux")[0, 20, b] == pytest.approx(50 / (dt * gf * energy))
    df = 50 / (dt * gf * energy**2 * 2 / PROTON_MASS_EV**2 * 1e5)
    assert d.to_units("df")[0, 20, b] == pytest.approx(df)
    theta, phi = np.deg2rad(g.theta_deg[20, b]), np.deg2rad(g.phi_deg[20, b])
    solid = 2 * np.cos(theta) * np.sin(np.deg2rad(22.5) / 2) * np.deg2rad(22.5)
    density = PROTON_MASS_EV**-1.5 * np.sqrt(2) * g.denergy_eV[20, b] * np.sqrt(energy) * df * solid
    assert d.density()[0] == pytest.approx(density)
    flux = 2 / PROTON_MASS_EV**2 * 1e5 * g.denergy_eV[20, b] * energy * df * solid
    direction = np.array([np.cos(theta) * np.cos(phi), np.cos(theta) * np.sin(phi), np.sin(theta)])
    np.testing.assert_allclose(d.number_flux()[0], flux * direction, rtol=1e-12)
    np.testing.assert_allclose(d.velocity()[0], flux * direction / density / 1e5, rtol=1e-12)
    assert d.density(energy_range=(1.0, 2.0))[0] == 0.0


def test_ima_event_correction_uses_the_tof_event_rows() -> None:
    cnt = np.ones((32, 4, 16), np.uint16)
    event = np.zeros((4, 16), np.uint32)
    event[0] = 999  # position events, ignored
    event[1:] = 64  # TOF events: each energy pair has 2*4*16 = 128 counts -> factor 192/128
    pace = _pace(2, 0x42, {"cnt": cnt, "event": event, "trash": np.zeros((32, 4, 2), np.uint16)})
    corrected = pace_ion_3d(pace, _calibration(2), count_correction="event_trash")[0x42]
    assert np.nanmax(corrected.counts) == pytest.approx(192 / 128)
    assert np.nanmin(corrected.counts) == pytest.approx(192 / 128)


def test_ima_type40_sums_mass_and_keeps_missing_cells() -> None:
    cnt = np.zeros((4, 32, 1024), np.uint16)
    cnt[1, 0, :10] = 3  # polar row 1, table energy row 0 -> 30 counts
    cnt[2, 5, :] = 65535  # every mass channel is a fill value
    info_sensor = 2
    pace = _pace(info_sensor, 0x40, {"cnt": cnt, "event": np.zeros((4, 16), np.uint32)})
    d = pace_ion_3d(pace, _calibration(info_sensor))[0x40]
    assert d.counts.shape == (1, 32, 4)
    assert d.counts[0, ENESQ[0], 1] == 30  # data polar order is kept for type 0x40
    assert np.isnan(d.counts[0, ENESQ[5], 2])
    assert np.all(d.grids[0].dphi_deg == 360.0)
    # the grid polar axis is remapped by the polar sequence (SPEDAS g[*, polsq] = g)
    assert d.grids[0].theta_deg[0, POLSQ4[0]] == pytest.approx(POLAR[POLSQ4[0]])


def test_ima_type43_sums_mass_counts_and_trash() -> None:
    cnt = np.zeros((8, 32, 4, 16), np.uint16)
    cnt[:, 3, 0, 0] = 2  # 16 counts over mass
    trash = np.zeros((8, 32, 4, 2), np.uint16)
    trash[:, 3, 0, :] = 1  # 16 discarded counts in that row -> factor 2 for that (energy, polar)
    pace = _pace(
        2, 0x43, {"cnt": cnt, "event": np.full((4, 16), 4294967295, np.uint32), "trash": trash}
    )
    raw = pace_ion_3d(pace, _calibration(2))[0x43]
    assert raw.counts[0, ENESQ[3], POLSQ4[0]] == 16
    trashed = pace_ion_3d(pace, _calibration(2), count_correction="trash")[0x43]
    assert trashed.counts[0, ENESQ[3], POLSQ4[0]] == 32


class _RotateZ90:
    """Stand-in for FrameContext: rotates by +90 deg about z."""

    def transform_vectors(self, vectors, *, times, source_frame, target_frame, missing="error"):
        v = np.asarray(vectors, dtype=float)
        return np.stack((-v[..., 1], v[..., 0], v[..., 2]), axis=-1)


def test_frame_rotation_applies_per_record_matrices() -> None:
    cnt = np.zeros((32, 4, 16), np.uint16)
    cnt[ENESQ.tolist().index(20), POLSQ4.tolist().index(0), 0] = 10
    pace = _pace(
        3,
        0x80,
        {"cnt": cnt, "event": np.zeros(16, np.uint32), "trash": np.zeros((32, 4, 2), np.uint16)},
        n=2,
    )
    d = pace_ion_3d(pace, _calibration(3))[0x80]
    v = d.velocity()
    rotated = d.velocity(frame="MOON_ME", context=_RotateZ90())  # type: ignore[arg-type]
    np.testing.assert_allclose(rotated[:, 0], -v[:, 1])
    np.testing.assert_allclose(rotated[:, 1], v[:, 0])
    directions = d.directions(frame="MOON_ME", context=_RotateZ90())  # type: ignore[arg-type]
    np.testing.assert_allclose(directions[..., 0], -d.directions()[..., 1])
    with pytest.raises(ValueError, match="FrameContext"):
        d.velocity(frame="MOON_ME")


def test_unsupported_types_are_reported_and_time_is_filtered() -> None:
    pace = _pace(3, 0x82, {"cnt": np.zeros((32, 16, 64), np.uint16)})
    assert pace_ion_3d(pace, _calibration(3)) == {}
    arrays = {
        "cnt": np.zeros((32, 4, 16), np.uint16),
        "event": np.zeros(16, np.uint32),
        "trash": np.zeros((32, 4, 2), np.uint16),
    }
    two = pace_ion_3d(_pace(3, 0x80, arrays, n=2), _calibration(3), time=day("2009-02-17"))[0x80]
    assert two.n_records == 2
    assert pace_ion_3d(_pace(3, 0x80, arrays), _calibration(3), time=day("2009-02-18")) == {}
    with pytest.raises(ValueError, match="IMA or IEA"):
        pace_ion_3d(_pace(0, 0x00, {"cnt": np.zeros((32, 16, 64), np.uint16)}), _calibration(3))
