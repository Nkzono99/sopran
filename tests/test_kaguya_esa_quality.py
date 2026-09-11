from __future__ import annotations

import numpy as np
import pytest

import sopran as spn
from sopran.experimental.kaguya.er_timeseries import _window_record, _window_skip_reason
from sopran.missions.kaguya.esa_quality import esa_pitch_rejection_reason
from sopran.missions.kaguya.pace import PaceCalibration, PaceData, PaceRecord
from sopran.missions.kaguya.pitch import PitchAngleSpectrumOptions, build_pitch_angle_spectrum


@pytest.mark.parametrize(
    "mode,kind,ram,reason",
    [
        (0x11, 0, 6, None),
        (0x12, 0, 6, None),
        (0x17, 1, 6, None),
        (0x18, 0, 6, None),
        (0x29, 1, 0, "spedas_mode29_type1_ram0_invalid"),
        (0x29, 1, 6, None),
        (0x29, 0, 0, None),
        (0x14, 1, 0, None),
        (0x91, 0, 6, "internal_count_mode"),
        (0x72, 0, 6, "unvalidated_command"),
        (0x73, 0, 6, "unvalidated_command"),
        (0x70, 1, 0, "unvalidated_command"),
        (0x03, 1, 0, "unvalidated_command"),
        (0x15, 2, 6, "onboard_pitch_sorted_not_supported"),
        (0x14, 3, 6, "unsupported_esa_look_type"),
    ],
)
def test_esa_specific_record_decision(mode, kind, ram, reason):
    assert (
        esa_pitch_rejection_reason(
            dict(mode=mode, svs_tbl=ram, data_quality=0xFFFFFFFF), data_type=kind
        )
        == reason
    )


@pytest.mark.parametrize("sensor", [0, 1])
def test_ion_checks_build_esa_pitch_counts(sensor):
    period = spn.day("2008-04-11")
    records = tuple(
        PaceRecord(type=0, index=i, arrays={"cnt": np.ones((32, 16, 64), dtype=np.uint16)})
        for i in range(2)
    )
    headers = tuple(
        dict(
            time=period.start.timestamp() + 8 + i * 16,
            mode=mode,
            mode2=0,
            type=0,
            svs_tbl=6,
            sampl_time=512,
            time_resolution=16000,
            data_quality=0xFFFFFFFF,
        )
        for i, mode in enumerate((0x11, 0x12))
    )
    pace = PaceData(
        sensor=sensor, headers=headers, records={0: records}, source_files=(), record_order=records
    )
    fov = dict(
        az16=np.linspace(0, 360, 16, endpoint=False),
        az64=np.linspace(0, 360, 64, endpoint=False),
        ene=np.broadcast_to(np.arange(32) + 1.0, (8, 32)),
        pol4=np.zeros((8, 32, 4)),
        pol16=np.zeros((8, 32, 16)),
    )
    array = build_pitch_angle_spectrum(
        pace=pace,
        time=period,
        calibration=PaceCalibration(fov={sensor: fov}),
        magnetic_field=np.array([1.0, 0.0, 0.0]),
        options=PitchAngleSpectrumOptions(pitch_bins=16),
    ).to_xarray()
    assert array.sizes["time"] == 2
    assert np.nansum(array.values) == 2 * 32 * 16 * 64
    assert array.pace_data_mode.values.tolist() == [17, 18]
    assert array.pace_data_quality.values.tolist() == [0xFFFFFFFF] * 2
    assert array.record_duration_seconds.values.tolist() == [16.0, 16.0]
    assert array.integration_time_seconds.values.tolist() == [16.0 / 512] * 2
    assert array.attrs["pace_data_mode_policy"] == "esa_look_quality_v2"


def test_ion_check_command_transition_is_not_esa_response_change():
    import xarray as xr

    array = xr.DataArray(
        np.ones(2),
        dims="time",
        coords={
            "pace_data_mode": ("time", [17, 18]),
            "pace_submode": ("time", [0, 0]),
            "pace_data_type": ("time", [0, 0]),
            "pace_svs_tbl": ("time", [6, 6]),
        },
    )
    assert _window_skip_reason(np.arange(2), arrays={"ESA-S1": array}) is None
    changed = array.assign_coords(pace_svs_tbl=("time", [6, 7]))
    assert (
        _window_skip_reason(np.arange(2), arrays={"ESA-S1": changed})
        == "ESA-S1_pace_svs_tbl_changed"
    )


def test_full_16s_record_is_not_one_eighth_window_coverage():
    import xarray as xr

    time = np.array(["2008-04-11T00:00:08"], dtype="datetime64[ns]")
    array = xr.DataArray([1.0], dims="time", coords={"record_duration_seconds": ("time", [16.0])})
    row = _window_record(
        int(time.astype("int64")[0] // 16_000_000_000),
        np.array([0]),
        record_times=time,
        integration_seconds=16,
        native_cadence_seconds=2,
        expected_records=8,
        minimum_records=1,
        b_sc=np.array([4.0]),
        sides=np.array(["parallel"]),
        arrays={"ESA-S1": array, "ESA-S2": array},
        count_correction="event_trash",
    )
    assert row["native_cadence_seconds"] == 16
    assert row["expected_records"] == 1
    assert row["window_coverage"] == 1


def test_changed_cadence_uses_original_coverage_fraction():
    import xarray as xr

    time = np.array(["2008-04-11T00:00:08"], dtype="datetime64[ns]")
    array = xr.DataArray([1.0], dims="time", coords={"record_duration_seconds": ("time", [1.0])})
    row = _window_record(
        int(time.astype("int64")[0] // 16_000_000_000),
        np.array([0]),
        record_times=time,
        integration_seconds=16,
        native_cadence_seconds=2,
        expected_records=8,
        minimum_records=3,
        min_window_coverage=0.3,
        b_sc=np.array([4.0]),
        sides=np.array(["low"]),
        arrays={"ESA-S1": array},
        count_correction="event_trash",
    )
    assert row["expected_records"] == 16
    assert row["minimum_records"] == 5
