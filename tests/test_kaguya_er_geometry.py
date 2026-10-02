from types import SimpleNamespace

import numpy as np
import pytest

import sopran as spn
from sopran.core.data import SopranArray
from sopran.core.schema import VariableSchema
from sopran.experimental.kaguya.er import _vectors_at
from sopran.missions.kaguya import pitch
from sopran.missions.kaguya.magnetic_geometry import (
    interpolate_vectors,
    load_lmag_with_margin,
)
from sopran.missions.kaguya.pace import PaceData, PaceRecord

xr = pytest.importorskip("xarray")


def test_interpolation_rejects_extrapolation_gaps_and_missing_brackets():
    values = np.array([[1, 0, 0], [2, 0, 0], [3, 0, 0], [np.nan, 0, 0], [5, 0, 0]])
    out = interpolate_vectors([0, 4, 604, 608, 612], values, [-1, 0, 2, 300, 604, 606, 612, 613])
    assert out.valid.tolist() == [False, True, True, False, True, False, True, False]
    np.testing.assert_allclose(out.values[out.valid, 0], [1, 1.5, 3, 5])
    assert np.isnan(out.values[~out.valid]).all()
    assert out.bracket_seconds[3] == 600
    assert out.nearest_seconds[3] == 296
    assert interpolate_vectors([], np.empty((0, 3)), [1]).valid.tolist() == [False]
    assert interpolate_vectors([1], [[1, 0, 0]], [0, 1, 2]).valid.tolist() == [False, True, False]


@pytest.mark.parametrize("times", [[0, 0], [1, 0], [np.nan, 1]])
def test_interpolation_rejects_ambiguous_source_times(times):
    with pytest.raises(ValueError, match="strictly increasing"):
        interpolate_vectors(times, np.ones((2, 3)), [0])


def test_er_and_pitch_share_bounded_interpolation():
    times = np.array(["2008-01-01", "2008-01-01T00:10:00"], dtype="datetime64[ns]")
    source = SopranArray(
        name="b",
        time=spn.day("2008-01-01"),
        schema=VariableSchema(name="b", dims=("time", "component"), units="nT"),
        xr=xr.DataArray(np.ones((2, 3)), dims=("time", "component"), coords={"time": times}),
    )
    target = times[0] + np.array([-1, 0, 300, 600, 601], dtype="timedelta64[s]")
    actual = _vectors_at(source, target, "b")
    other, _ = pitch._magnetic_source_vectors(source, target.astype("int64") / 1e9, None)
    np.testing.assert_equal(actual, other)
    assert np.isfinite(actual[:, 0]).tolist() == [False, True, False, True, False]
    from sopran.missions.kaguya.data import _cache_fingerprint

    shifted = SopranArray(
        name=source.name,
        time=source.time,
        schema=source.schema,
        xr=source.to_xarray().assign_coords(time=times + np.timedelta64(1, "s")),
    )
    assert _cache_fingerprint(source) != _cache_fingerprint(shifted)


def _array(seconds, mode=0x14):
    times = np.datetime64("2008-01-01", "ns") + np.array(seconds) * np.timedelta64(1, "ms")
    counts = np.arange(len(times), dtype=float).reshape(-1, 1, 1)
    array = xr.DataArray(
        counts,
        dims=("time", "energy", "pitch_angle"),
        coords={
            "time": times,
            "pitch_angle": [45.0],
            "energy_eV": (("time", "energy"), np.full((len(times), 1), 100.0)),
            "exposure": (("time", "energy", "pitch_angle"), np.ones_like(counts)),
            "pace_data_mode": ("time", np.full(len(times), mode)),
            "record_duration_seconds": ("time", np.full(len(times), 2.0)),
        },
        attrs={"value": "counts", "pitch_edges": [0, 90]},
    )
    array.exposure.attrs["mode"] = "calibrated"
    return array


def test_native_pitch_builder_does_not_require_pairing(monkeypatch):
    paces = []
    original = [_array([1000, 15000]), _array([1500])]
    for sensor in (0, 1):
        records = tuple(
            PaceRecord(type=1, index=i, arrays={}) for i in range(len(original[sensor]))
        )
        paces.append(
            PaceData(
                sensor=sensor,
                headers=tuple(
                    {"time": spn.day("2008-01-01").start.timestamp() + i, "mode": 0x14}
                    for i in range(len(records))
                ),
                records={1: records},
                source_files=(),
                record_order=records,
            )
        )

    def build(**kw):
        a = original[kw["pace"].sensor]
        return SopranArray(
            name="counts",
            time=spn.day("2008-01-01"),
            schema=VariableSchema(name="counts", dims=a.dims, units="count"),
            xr=a,
        )

    monkeypatch.setattr(pitch, "build_pitch_angle_spectrum", build)
    monkeypatch.setattr(pitch, "_aligned_sampled_paces", lambda *a, **k: pytest.fail("paired"))
    output = pitch.build_aligned_pitch_angle_spectra(
        paces=paces,
        time=spn.day("2008-01-01"),
        calibration=None,
        magnetic_field=[1, 0, 0],
        align=False,
    )
    assert [a.to_xarray().sizes["time"] for a in output.values()] == [2, 1]


def test_geometry_load_keeps_real_brackets_outside_requested_interval():
    period = spn.period("2008-01-01", "2008-01-01T00:00:16")
    times = np.datetime64("2008-01-01", "ns") + np.arange(-4, 25, 4) * np.timedelta64(1, "s")
    source = xr.DataArray(
        np.ones((len(times), 3)), dims=("time", "component"), coords={"time": times}
    )
    calls = []

    def load(time, **kwargs):
        calls.append((time, kwargs["missing"]))
        a = source.where(
            (source.time >= np.datetime64(time.start.replace(tzinfo=None)))
            & (source.time < np.datetime64(time.stop.replace(tzinfo=None))),
            drop=True,
        )
        return SimpleNamespace(
            magnetic_field=SopranArray(
                name="b", time=time, schema=VariableSchema(name="b", dims=a.dims, units="nT"), xr=a
            )
        )

    loaded = load_lmag_with_margin(SimpleNamespace(load=load), period, download="never")
    assert calls[0] == (period, "error")
    assert calls[1][1] == "empty"
    target = np.array(["2008-01-01T00:00:14"], dtype="datetime64[ns]")
    assert np.isfinite(_vectors_at(loaded.magnetic_field, target, "b")).all()
    assert calls[1][0].start < period.start and calls[1][0].stop > period.stop
