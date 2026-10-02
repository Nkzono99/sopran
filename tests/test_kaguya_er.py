from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import sopran as spn
import sopran.experimental.kaguya.er as er_module
from sopran.core.data import SopranArray
from sopran.core.schema import VariableSchema
from sopran.experimental.electron_reflection import (
    FiniteBinFitSettings,
    FiniteBinObservation,
    HalekasFitSettings,
    mirror_boundary_sin2,
)

xr = pytest.importorskip("xarray")


def spectrum():
    energy = np.array([120.0, 180.0, 270.0, 400.0, 600.0, 900.0])
    pitch = np.arange(5.0, 90.0, 10.0)
    boundary = mirror_boundary_sin2(energy, 1.35, -60.0)
    ratio = np.where(np.sin(np.deg2rad(pitch))[None, :] ** 2 < boundary[:, None], 0.1, 1.0)
    reference = np.full(ratio.shape, 100_000.0)
    affected = np.rint(reference * ratio)
    full = np.concatenate((affected, reference[:, ::-1]), axis=1)
    return xr.DataArray(
        np.stack((full, full)),
        dims=("time", "energy", "pitch_angle"),
        coords={
            "time": np.array(
                ["2008-04-02T14:58:32", "2008-04-02T14:58:34"], dtype="datetime64[ns]"
            ),
            "energy": energy,
            "pitch_angle": np.concatenate((pitch, 180.0 - pitch[::-1])),
        },
        attrs={"units": "count", "value": "counts"},
    )


def adapter():
    return er_module.KaguyaErInstrument(spn.Kaguya(download="never"))


def test_paired_input_feeds_both_retained_estimators():
    er = adapter()
    paired = er.paired_counts(spectrum(), index=0, b_sc_nT=8.0, affected_side="low")
    hard = er.effective_field.fit_halekas(
        paired, settings=HalekasFitSettings(mirror_grid_points=72, delta_u_grid_points=81)
    )
    assert hard.success
    assert hard.effective_field_nT == pytest.approx(8.0 * hard.mirror_ratio)
    obs = FiniteBinObservation.from_counts(
        paired,
        energy_edges_eV=[100, 150, 220, 330, 500, 750, 1100],
        pitch_edges_deg=np.arange(0, 91, 10),
    )
    fitted = er.effective_field.fit_finite_bin(
        obs,
        settings=FiniteBinFitSettings(
            mirror_ratio_bounds=(1.35, 1.35),
            bottom_ratio_bounds=(0.1, 0.1),
            delta_u_bounds_eV=(-60, -60),
            scale_bounds=(1, 1),
            beam_enabled=False,
        ),
    )
    assert fitted.effective_field_nT == pytest.approx(10.8)
    assert np.isfinite(fitted.fitted_log_ratio_dex).all()
    assert paired.metadata["exposure_assumed_equal"] is True


def test_geometry_and_hemisphere_preserve_counts_and_exposure():
    er = adapter()
    data = spectrum()
    exposure = np.ones(data.shape)
    exposure[:, :, 9:] = 2.0
    data.coords["exposure"] = (data.dims, exposure)
    low = er.paired_counts(data, index=1, magnetic_field=[8, 0, 0], position=[1738, 0, 0])
    high = er.paired_counts(data, index=1, magnetic_field=[-8, 0, 0], position=[1738, 0, 0])
    assert low.metadata["affected_side"] == "low"
    assert high.metadata["affected_side"] == "high"
    np.testing.assert_array_equal(low.affected_counts, high.reference_counts)
    np.testing.assert_array_equal(low.reference_counts, high.affected_counts)
    assert np.all(low.affected_exposure == 1)
    assert np.all(high.affected_exposure == 2)
    assert high.b_sc_nT == 8


def test_joint_count_exposure_gap_preserves_missing_cell():
    data = spectrum()
    exposure = np.ones(data.shape)
    data.values[0, 0, 0] = np.nan
    exposure[0, 0, 0] = np.nan
    data.coords["exposure"] = (data.dims, exposure)
    data.coords["exposure"].attrs["mode"] = "calibrated"
    counts = adapter().paired_counts(data, index=0, b_sc_nT=8.0, affected_side="low")
    assert np.isnan(counts.affected_counts[0, 0])
    assert counts.metadata["exposure_mode"] == "calibrated"
    exposure[0, 0, 1] = 0
    data.coords["exposure"] = (data.dims, exposure)
    with pytest.raises(ValueError, match="exposure"):
        adapter().paired_counts(data, index=0, b_sc_nT=8.0, affected_side="low")


def test_pairing_uses_only_selected_geometry_for_arrays_and_time_series():
    data = spectrum()
    magnetic = np.array([[8.0, 0.0, 0.0], [np.nan, np.nan, np.nan]])
    radial = np.array([[1738.0, 0.0, 0.0], [np.nan, np.nan, np.nan]])
    field = SopranArray(
        name="b",
        time=spn.day("2008-04-02"),
        schema=VariableSchema(name="b", dims=("time", "component"), units="nT"),
        xr=xr.DataArray(
            magnetic,
            dims=("time", "component"),
            coords={"time": data.time.values},
        ),
    )
    er = adapter()
    array_counts = er.paired_counts(data, index=0, magnetic_field=magnetic, position=radial)
    series_counts = er.paired_counts(data, index=0, magnetic_field=field, position=radial)
    assert array_counts.b_sc_nT == series_counts.b_sc_nT == 8.0
    assert array_counts.metadata == series_counts.metadata
    np.testing.assert_array_equal(array_counts.affected_counts, series_counts.affected_counts)
    with pytest.raises(ValueError, match="finite"):
        er.paired_counts(data, index=1, magnetic_field=magnetic, position=radial)


def test_pairing_requires_counts_and_an_existing_sample():
    data = spectrum()
    data.attrs["value"] = "energy_flux"
    with pytest.raises(ValueError, match="counts"):
        adapter().paired_counts(data, index=0, b_sc_nT=8.0, affected_side="low")
    data.attrs["value"] = "counts"
    with pytest.raises(IndexError, match="index"):
        adapter().paired_counts(data, index=2, b_sc_nT=8.0, affected_side="low")
    with pytest.raises(TypeError, match="position"):
        adapter().paired_counts(data, index=0, b_sc_nT=8.0)


def test_shared_reader_preparation_preserves_builder_options(monkeypatch):
    er = adapter()
    inputs = SimpleNamespace(
        paces=object(),
        calibration=object(),
        magnetic_field=object(),
        files=(),
        context=object(),
    )
    monkeypatch.setattr(er, "_load_pitch_inputs", lambda *args: inputs)
    calls = []

    def builder(**kwargs):
        calls.append(kwargs)
        return kwargs

    monkeypatch.setattr(er_module, "build_combined_pitch_angle_spectrum", builder)
    monkeypatch.setattr(er_module, "build_aligned_pitch_angle_spectra", builder)
    time = spn.day("2008-04-02")
    er.pitch_angle_spectrum(time, energy_bins=30, cadence_seconds=None)
    er.pitch_angle_spectra(time, align=False, max_time_offset_seconds=2)
    assert calls[0]["paces"] is calls[1]["paces"] is inputs.paces
    assert calls[0]["energy_bins"] == 30
    assert calls[0]["options"].cadence_seconds is None
    assert calls[1]["align"] is False
    assert calls[1]["max_time_offset_seconds"] == 2
