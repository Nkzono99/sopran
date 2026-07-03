from __future__ import annotations

import pytest

import sopran as spn
from sopran.core.data import SopranArray


def test_frame_context_records_backend_and_kernel_metadata() -> None:
    context = spn.FrameContext(
        spice_kernels=("kernels/naif0012.tls", "kernels/moon_pa_de421_1900-2050.bpc"),
        time_scale="utc",
    )

    metadata = context.metadata()

    assert metadata["time_scale"] == "utc"
    assert metadata["spice_kernels"] == [
        "kernels/naif0012.tls",
        "kernels/moon_pa_de421_1900-2050.bpc",
    ]
    assert "spiceypy" in metadata["available_backends"]
    assert "spacepy" in metadata["available_backends"]


def test_sopran_array_identity_transform_preserves_values_and_records_provenance() -> None:
    xr = pytest.importorskip("xarray")
    array = xr.DataArray(
        [[-2.61, 2.98, -1.09]],
        dims=("time", "component"),
        coords={"time": ["2008-01-01T00:00:00Z"], "component": ["x", "y", "z"]},
        name="magnetic_field",
        attrs={"units": "nT", "frame": "MOON_ME"},
    )
    field = SopranArray(
        name="magnetic_field",
        time=spn.day("2008-01-01"),
        schema=spn.VariableSchema(
            name="magnetic_field",
            dims=("time", "component"),
            units="nT",
            frame="MOON_ME",
        ),
        xr=array,
    )

    transformed = field.transform("moon_me", context=spn.FrameContext())

    assert transformed.schema.frame == "MOON_ME"
    assert transformed.to_xarray().attrs["frame"] == "MOON_ME"
    assert transformed.to_xarray().values.tolist() == [[-2.61, 2.98, -1.09]]
    assert transformed.to_xarray().attrs["frame_transform"]["backend"] == "identity"
    assert transformed.metadata["operations"][0]["operation"] == "frame_transform"


def test_frame_context_rejects_unimplemented_non_identity_transform() -> None:
    xr = pytest.importorskip("xarray")
    field = SopranArray(
        name="magnetic_field",
        time=spn.day("2008-01-01"),
        schema=spn.VariableSchema(
            name="magnetic_field",
            dims=("time", "component"),
            units="nT",
            frame="MOON_ME",
        ),
        xr=xr.DataArray(
            [[-2.61, 2.98, -1.09]],
            dims=("time", "component"),
            coords={"time": ["2008-01-01T00:00:00Z"], "component": ["x", "y", "z"]},
            name="magnetic_field",
            attrs={"units": "nT", "frame": "MOON_ME"},
        ),
    )

    with pytest.raises(spn.FrameTransformError, match="MOON_ME -> GSE"):
        field.transform("GSE", context=spn.FrameContext())


def test_frame_context_transforms_identity_vectors_without_spice() -> None:
    import numpy as np

    vectors = np.array([[1.0, 2.0, 3.0], [-1.0, 0.0, 4.0]])

    transformed = spn.FrameContext().transform_vectors(
        vectors,
        times=["2008-01-01T00:00:00", "2008-01-01T00:00:01"],
        source_frame="SELENE_M_SPACECRAFT",
        target_frame="selene_m_spacecraft",
    )

    assert transformed.tolist() == vectors.tolist()


def test_frame_context_non_identity_vector_transform_reports_spice_setup() -> None:
    import numpy as np

    with pytest.raises(spn.FrameTransformError, match="SELENE_M_SPACECRAFT -> MOON_ME"):
        spn.FrameContext().transform_vectors(
            np.array([[1.0, 0.0, 0.0]]),
            times=["2008-01-01T00:00:00"],
            source_frame="SELENE_M_SPACECRAFT",
            target_frame="MOON_ME",
        )
