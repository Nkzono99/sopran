"""ER input pieces: paired maps, native-record windows, SVM3D connection, shard writer."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import sopran as spn
from sopran.core.store import Store
from sopran.experimental.electron_reflection.maps import (
    PairedMapSettings,
    PitchCountRecord,
    accumulate_pitch_map,
    bin_overlap_fraction,
    build_paired_map,
    fold_pitch_map,
)
from sopran.experimental.kaguya import er_batch
from sopran.experimental.kaguya.er_windows import (
    NativeEsaRecords,
    attach_record_geometry,
    calendar_windows,
    field_radial_geometry,
    native_record_arrays,
    window_input_diagnostic,
    window_pitch_records,
    window_record,
    window_sample_id,
)
from sopran.experimental.moon.connection import (
    ConnectionPolicy,
    classify_connection,
    trace_connection,
)
from sopran.experimental.moon.svm3d import SVM3DTraceResult

xr = pytest.importorskip("xarray")

GRID = PairedMapSettings(energy_bins=4, pitch_bins=8)


def _record(side: str = "low", pitch_bin: int = 0) -> PitchCountRecord:
    counts = np.zeros((GRID.energy_bins, GRID.pitch_bins))
    counts[:, pitch_bin] = 10.0
    return PitchCountRecord(
        counts=counts,
        exposure=np.ones_like(counts),
        energy_edges_eV=GRID.energy_edges_eV,
        pitch_edges_deg=GRID.pitch_edges_deg,
        affected_side=side,  # type: ignore[arg-type]
    )


def test_bin_overlap_fraction_splits_each_source_bin_once() -> None:
    fraction = bin_overlap_fraction([0.0, 2.0, 4.0], [0.0, 1.0, 3.0, 4.0])
    np.testing.assert_allclose(fraction, [[0.5, 0.5, 0.0], [0.0, 0.5, 0.5]])
    np.testing.assert_allclose(fraction.sum(axis=1), 1.0)


def test_accumulation_orients_the_affected_side_to_low_pitch_and_keeps_counts() -> None:
    counts, exposure = accumulate_pitch_map([_record("low", 0), _record("high", 0)], GRID)
    assert counts.sum() == pytest.approx(2 * 10.0 * GRID.energy_bins)
    # A "high" record is mirrored: its first native pitch bin lands at the far end.
    np.testing.assert_allclose(counts[:, 0], 10.0)
    np.testing.assert_allclose(counts[:, -1], 10.0)
    np.testing.assert_allclose(exposure, 2.0)


def test_fold_pairs_mirror_bins_and_requires_energy_support() -> None:
    counts = np.zeros((GRID.energy_bins, GRID.pitch_bins))
    counts[:, 0] = 5.0  # affected, folded column 0
    counts[:, -1] = 7.0  # reference, folded column 0
    counts[0, 1:3] = 1.0  # only the lowest energy row has 3 non-empty pairs
    exposure = np.ones_like(counts)
    exposure[1, 2] = 0.0
    paired = fold_pitch_map(counts, exposure, GRID, min_pitch_bins_per_energy=3)
    np.testing.assert_allclose(paired.affected_counts[:, 0], 5.0)
    np.testing.assert_allclose(paired.reference_counts[:, 0], 7.0)
    assert not paired.pair_observed[1, 2]
    assert paired.fit_valid[0, :3].all() and not paired.fit_valid[1:].any()
    assert set(paired.arrays()) >= set(er_batch.FLOAT_ARRAYS) | set(er_batch.BOOL_ARRAYS)


def test_count_record_from_spectrum_sorts_and_sums_duplicate_energies() -> None:
    values = np.arange(2 * 3 * 2, dtype=float).reshape(2, 3, 2)
    array = xr.DataArray(
        values,
        dims=("time", "energy", "pitch_angle"),
        coords={
            "time": np.array(["2008-01-01T00:00:00", "2008-01-01T00:00:02"], "datetime64[ns]"),
            "pitch_angle": [45.0, 135.0],
            "energy_eV": (("time", "energy"), [[100.0, 50.0, 100.0], [10.0, 20.0, 30.0]]),
            "exposure": (("time", "energy", "pitch_angle"), np.ones_like(values)),
        },
        attrs={"value": "counts", "units": "count", "pitch_edges": [0.0, 90.0, 180.0]},
    )
    record = PitchCountRecord.from_spectrum(array, index=0, affected_side="low")
    np.testing.assert_allclose(record.counts, [[2.0, 3.0], [0.0 + 4.0, 1.0 + 5.0]])
    np.testing.assert_allclose(record.exposure, [[1.0, 1.0], [2.0, 2.0]])
    np.testing.assert_allclose(record.energy_edges_eV[1], np.sqrt(50.0 * 100.0))
    np.testing.assert_allclose(record.pitch_edges_deg, [0.0, 90.0, 180.0])


def _sensor(times: list[str], value: float, mode: int = 0x24) -> xr.DataArray:
    counts = np.full((len(times), GRID.energy_bins, GRID.pitch_bins), value)
    energy = np.sqrt(GRID.energy_edges_eV[:-1] * GRID.energy_edges_eV[1:])
    pitch = 0.5 * (GRID.pitch_edges_deg[:-1] + GRID.pitch_edges_deg[1:])
    return xr.DataArray(
        counts,
        dims=("time", "energy", "pitch_angle"),
        coords={
            "time": np.array(times, dtype="datetime64[ns]"),
            "pitch_angle": pitch,
            "energy_eV": (("time", "energy"), np.tile(energy, (len(times), 1))),
            "exposure": (("time", "energy", "pitch_angle"), np.ones_like(counts)),
            "pace_data_mode": ("time", np.full(len(times), mode)),
            "record_duration_seconds": ("time", np.full(len(times), 4.0)),
        },
        attrs={"value": "counts", "units": "count", "pitch_edges": list(GRID.pitch_edges_deg)},
    )


def _native() -> NativeEsaRecords:
    arrays = native_record_arrays(
        {
            "ESA-S1": _sensor(["2008-01-01T00:00:01", "2008-01-01T00:00:05"], 1.0),
            "ESA-S2": _sensor(["2008-01-01T00:00:03"], 2.0),
        }
    )
    times = arrays["ESA-S1"].time.values
    magnetic = np.tile([0.0, 0.0, 5.0], (times.size, 1))
    position = np.tile([0.0, 0.0, 1800.0], (times.size, 1))
    _, _, sides = field_radial_geometry(magnetic, position)
    lmag_times = np.datetime64("2008-01-01T00:00:00", "ns") + np.arange(4) * np.timedelta64(4, "s")
    field = xr.DataArray(
        np.tile([0.0, 0.0, 5.0], (4, 1)), dims=("time", "component"), coords={"time": lmag_times}
    )
    return NativeEsaRecords(
        arrays=attach_record_geometry(arrays, magnetic, position),
        times=times,
        position_km=position,
        magnetic_field_nT=magnetic,
        field_nT=np.linalg.norm(magnetic, axis=1),
        affected_side=sides,
        magnetic_field=field,
    )


def test_native_records_window_summary_and_count_records() -> None:
    records = _native()
    assert records.arrays["ESA-S2"].record_present.values.tolist() == [False, True, False]
    windows = list(calendar_windows(records.times, spn.day("2008-01-01")))
    assert len(windows) == 5400
    window_id, indices = windows[0]
    assert indices.tolist() == [0, 1, 2]
    record = window_record(window_id, indices, records)
    assert record["sample_id"] == window_sample_id(window_id) == "20080101-000008"
    assert record["records_integrated"] == 3
    assert record["expected_records"] == 4  # 16 s / median 4 s record duration
    assert record["window_coverage"] == pytest.approx(0.25)
    assert record["affected_side"] == "low"
    assert record["b_sc_nT"] == pytest.approx(5.0)
    assert record["field_radial_abs_cosine_min"] == pytest.approx(1.0)
    assert record["magnetic_direction_max_deviation_deg"] == pytest.approx(0.0)
    assert record["geometry_sampling"] == "lmag_samples"
    assert window_input_diagnostic(indices, records.arrays) is None
    assert window_input_diagnostic(windows[1][1], records.arrays) == "no_records"
    pitch_records = window_pitch_records(records, indices)
    assert len(pitch_records) == 3
    paired = build_paired_map(pitch_records, GRID, min_pitch_bins_per_energy=1)
    assert paired.global_counts.sum() == pytest.approx((1 + 1 + 2) * GRID.energy_bins * 8)


def test_connection_status_follows_the_check_order() -> None:
    traces = pd.DataFrame(
        dict(
            trace_input_valid=[True, False, True, True, True, True, True, True],
            inward_valid=[True, True, False, True, True, True, True, True],
            reverse_valid=[False, False, False, True, False, False, False, False],
            inward_connection_sign=[1, 1, 1, 1, 1, -1, 1, 1],
        )
    )
    status = classify_connection(traces, [0, 1, 2, 3, 4, 4, 5, 5])
    assert {k: v["field_connection_status"] for k, v in status.items()} == {
        0: "model_connected",
        1: "trace_input_invalid",
        2: "inward_not_reached",
        3: "both_branches_connected",
        4: "side_changed",
        5: "model_connected",
    }
    assert status[5]["connection_records"] == 2 and status[5]["connection_eligible"]


class _Shell:
    def residual_external_field(self, positions, magnetic):
        return np.zeros_like(positions)

    def trace(self, positions, external, signs, *, settings):
        assert settings.max_steps == 2000 and settings.stop_altitude_km == 6.1
        valid = np.asarray(signs) > 0
        return SVM3DTraceResult(
            np.asarray(signs), {"valid": valid, "target_crossed": np.zeros_like(valid)}, settings
        )


def test_trace_connection_traces_inward_toward_the_moon() -> None:
    positions = [[0.0, 0.0, 1800.0], [0.0, 0.0, 1800.0], [np.nan, 0.0, 1800.0]]
    magnetic = [[0.0, 0.0, -5.0], [0.0, 0.0, 5.0], [0.0, 0.0, 5.0]]
    traces = trace_connection(_Shell(), positions, magnetic, policy=ConnectionPolicy())  # type: ignore[arg-type]
    # Inward follows -sign(r.B): +1 for B toward the Moon, -1 for B outward.
    assert traces.record_connected.tolist() == [True, False, False]
    assert traces.trace_input_valid.tolist() == [True, True, False]
    assert traces.inward_valid.tolist()[:2] == [True, False]


def test_window_rows_are_written_as_input_shards_that_fit(tmp_path) -> None:
    store = Store(tmp_path / "store")
    rng = np.random.default_rng(3)
    grid = PairedMapSettings()
    rows = []
    for k in range(3):
        counts = rng.poisson(40.0, (grid.energy_bins, grid.pitch_bins)).astype(float)
        paired = fold_pitch_map(counts, np.ones_like(counts), grid)
        record = dict(
            sample_id=f"20080101-0000{k}8",
            time=pd.Timestamp(f"2008-01-01T00:00:{k}8Z"),
            b_sc_nT=5.0,
            affected_side="low",
            field_connection_status="model_connected",
            field_radial_abs_cosine_min=0.9,
            magnetic_direction_max_deviation_deg=5.0,
        )
        rows.append(er_batch.window_input_row(record, paired if k else None))
    assert json.loads(rows[1]["record_json"])["time"] == "2008-01-01T00:00:18+00:00"
    root = er_batch.write_input_days(store, "built", {"2008-01-01": rows}, log=lambda _: None)
    assert er_batch.verify_inputs(store, "built")
    entry = json.loads((root / "days.json").read_text())[0]
    assert entry == {**entry, "windows": 3, "distributions": 2, "source_status": "built"}
    config = er_batch.RunConfig(
        "built", "run", fit_settings={"generations": 4, "seeds": 1}, profile_points=5
    )
    er_batch.prepare_run(store, config)
    assert er_batch.run_days(store, "run", workers=0, log=lambda _: None)["completed"] == 1
    fits = er_batch.scan_run(store, "run")
    assert fits.height == 3
    assert fits.filter(fits["status"] == "no_saved_distribution").height == 1
