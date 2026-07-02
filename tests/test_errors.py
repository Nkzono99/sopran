from __future__ import annotations

import pytest

import sopran as spn
from sopran import Store


def test_unknown_dataset_id_raises_dataset_not_found_error(tmp_path) -> None:
    with pytest.raises(spn.DatasetNotFoundError) as exc:
        spn.load("unknown.dataset", spn.day("2008-01-01"), store=Store(tmp_path / "store"))

    assert "unknown.dataset" in str(exc.value)


def test_scan_empty_registered_dataset_raises_dataset_not_found_error(tmp_path) -> None:
    store = Store(tmp_path / "store")
    store.register_dataset(
        dataset_id="kaguya.esa1.empty",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="empty",
        schema=spn.Kaguya(store=store).esa1.schema(),
        time_coverage=spn.day("2008-01-01"),
    )

    with pytest.raises(spn.DatasetNotFoundError) as exc:
        store.scan_dataset("kaguya.esa1.empty", layer="normalized")

    assert "kaguya.esa1.empty" in str(exc.value)


def test_public_exception_hierarchy_matches_spec() -> None:
    expected = (
        "ConfigError",
        "DownloadError",
        "DecodeError",
        "SchemaError",
        "FrameTransformError",
        "PipelineError",
        "BackendError",
    )

    for name in expected:
        error_type = getattr(spn, name)
        assert issubclass(error_type, spn.SopranError)
