from __future__ import annotations

import numpy as np
import pytest

import sopran as spn
import sopran.experimental.kaguya.er as er_module
from sopran.core.data import SopranArray
from sopran.core.schema import VariableSchema
from sopran.experimental.electron_reflection import (
    EffectiveFieldFitSettings,
    simulate_electron_reflection_counts,
)
from sopran.experimental.kaguya.er import affected_side_from_geometry

pytest.importorskip("scipy")
xr = pytest.importorskip("xarray")


def _full_pitch_spectrum() -> SopranArray:
    energy = np.array([120.0, 180.0, 270.0, 400.0, 600.0, 900.0])
    folded_pitch = np.arange(5.0, 90.0, 10.0)
    full_pitch = np.concatenate((folded_pitch, 180.0 - folded_pitch[::-1]))
    rows = []
    for seed in (3, 4):
        paired = simulate_electron_reflection_counts(
            energy_eV=energy,
            pitch_deg=folded_pitch,
            b_sc_nT=8.0,
            mirror_ratio=7.0,
            sigma_ln_b=0.18,
            reference_counts=1_200.0,
            concentration=220.0,
            random_seed=seed,
        )
        values = np.empty((energy.size, full_pitch.size), dtype=float)
        values[:, : folded_pitch.size] = paired.affected_counts
        values[:, folded_pitch.size :] = paired.reference_counts[:, ::-1]
        rows.append(values)
    array = xr.DataArray(
        np.stack(rows),
        dims=("time", "energy", "pitch_angle"),
        coords={
            "time": np.array(
                ["2008-04-02T14:58:32", "2008-04-02T14:58:34"],
                dtype="datetime64[ns]",
            ),
            "energy": np.arange(energy.size),
            "energy_eV": (("time", "energy"), np.broadcast_to(energy, (2, energy.size))),
            "pitch_angle": full_pitch,
        },
        name="pitch_angle_spectrum",
        attrs={"units": "count", "value": "counts"},
    )
    return SopranArray(
        name="pitch_angle_spectrum",
        time=spn.period("2008-04-02T14:58:32", "2008-04-02T14:58:36"),
        schema=VariableSchema(
            name="pitch_angle_spectrum",
            dims=("time", "energy", "pitch_angle"),
            units="count",
        ),
        xr=array,
    )


def test_affected_side_from_geometry_uses_outgoing_field_direction() -> None:
    magnetic = np.array([[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]])
    position = np.array([[1738.0, 0.0, 0.0], [1738.0, 0.0, 0.0]])

    assert affected_side_from_geometry(magnetic, position).tolist() == ["low", "high"]


def test_kaguya_effective_field_endpoint_fits_pitch_spectrum(tmp_path) -> None:
    kg = spn.Kaguya(store=spn.Store(tmp_path / "store"), download="never")

    fitted = er_module.KaguyaErInstrument(kg).effective_field.fit(
        _full_pitch_spectrum(),
        b_sc_nT=np.array([8.0, 8.0]),
        affected_side="low",
        settings=EffectiveFieldFitSettings(
            optimizer_starts=3,
            profile_likelihood=False,
        ),
        cache="never",
        workers=2,
    )
    frame = fitted.to_pandas()

    assert len(frame) == 2
    assert frame["success"].all()
    assert frame["edge_supported"].all()
    assert set(frame["selected_model"]) == {"mirror_only"}
    assert frame["mirror_ratio"].to_numpy() == pytest.approx([7.0, 7.0], rel=0.3)
    assert frame["effective_field"].to_numpy() == pytest.approx([56.0, 56.0], rel=0.3)
    assert frame["affected_side"].tolist() == ["low", "low"]
    assert set(frame["quality_grade"]) == {"good"}


def test_kaguya_effective_field_endpoint_can_infer_affected_side(tmp_path) -> None:
    kg = spn.Kaguya(store=spn.Store(tmp_path / "store"), download="never")
    magnetic = np.array([[8.0, 0.0, 0.0], [8.0, 0.0, 0.0]])
    position = np.array([[1738.0, 0.0, 0.0], [1738.0, 0.0, 0.0]])

    fitted = er_module.KaguyaErInstrument(kg).effective_field.fit(
        _full_pitch_spectrum(),
        magnetic_field=magnetic,
        position=position,
        affected_side="auto",
        settings=EffectiveFieldFitSettings(
            optimizer_starts=2,
            profile_likelihood=False,
        ),
        cache="never",
    )

    assert fitted.to_pandas()["affected_side"].tolist() == ["low", "low"]


def test_kaguya_effective_field_endpoint_requires_count_pitch_data(tmp_path) -> None:
    kg = spn.Kaguya(store=spn.Store(tmp_path / "store"), download="never")
    spectrum = _full_pitch_spectrum()
    spectrum.to_xarray().attrs["value"] = "energy_flux"

    with pytest.raises(ValueError, match="counts"):
        er_module.KaguyaErInstrument(kg).effective_field.fit(
            spectrum,
            b_sc_nT=8.0,
            affected_side="low",
            cache="never",
        )


def test_kaguya_effective_field_endpoint_allows_joint_count_exposure_gaps(tmp_path) -> None:
    kg = spn.Kaguya(store=spn.Store(tmp_path / "store"), download="never")
    spectrum = _full_pitch_spectrum()
    array = spectrum.to_xarray()
    exposure = np.ones(array.shape, dtype=float)
    array.values[0, 0, 0] = np.nan
    exposure[0, 0, 0] = np.nan
    array.coords["exposure"] = (array.dims, exposure)
    array.coords["exposure"].attrs["mode"] = "calibrated"

    fitted = er_module.KaguyaErInstrument(kg).effective_field.fit(
        spectrum,
        b_sc_nT=8.0,
        affected_side="low",
        settings=EffectiveFieldFitSettings(
            optimizer_starts=2,
            profile_likelihood=False,
        ),
        cache="never",
    )

    assert fitted.to_pandas()["success"].all()
    assert fitted.to_pandas()["exposure_mode"].tolist() == ["calibrated", "calibrated"]


def test_kaguya_effective_field_endpoint_reuses_store_cache(tmp_path, monkeypatch) -> None:
    store = spn.Store(tmp_path / "store")
    kg = spn.Kaguya(store=store, download="never")
    settings = EffectiveFieldFitSettings(
        optimizer_starts=2,
        profile_likelihood=False,
    )

    first = er_module.KaguyaErInstrument(kg).effective_field.fit(
        _full_pitch_spectrum(),
        b_sc_nT=8.0,
        affected_side="low",
        settings=settings,
        cache="use",
        variant_id="synthetic_mirror_v1",
    )
    record = store.dataset(
        "experimental.kaguya.er.effective_field",
        layer="features",
        variant_id="synthetic_mirror_v1",
    )

    def unexpected_refit(*args, **kwargs):
        raise AssertionError("cached effective-field data should be reused")

    monkeypatch.setattr(er_module, "fit_effective_field", unexpected_refit)
    second = er_module.KaguyaErInstrument(kg).effective_field.fit(
        _full_pitch_spectrum(),
        b_sc_nT=8.0,
        affected_side="low",
        settings=settings,
        cache="use",
        variant_id="synthetic_mirror_v1",
    )

    assert record.manifest()["producer"] == "sopran.experimental.kaguya.er.robust_counts"
    assert record.verify_checksums()
    assert second.to_pandas()["mirror_ratio"].tolist() == pytest.approx(
        first.to_pandas()["mirror_ratio"].tolist()
    )
