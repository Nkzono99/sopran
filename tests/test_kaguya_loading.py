from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest

import sopran as spn
import sopran.missions.kaguya.files as kaguya_files
from sopran import Store
from sopran.missions.kaguya import Kaguya, normalize_sensors
from sopran.missions.kaguya.data import KaguyaESA1Data
from sopran.missions.kaguya.pace import PaceData, PaceRecord
from sopran.missions.kaguya.schema import KAGUYA_ESA1_SCHEMA


def test_normalize_sensors_accepts_spedas_ids_and_names() -> None:
    assert normalize_sensors([0, "ESA-S2", "lmag", "esa1"]) == ["ESA1", "ESA2", "LMAG"]


def test_kaguya_esa1_query_builds_public_pbf_paths(tmp_path) -> None:
    kaguya = Kaguya(store=Store(tmp_path / "store"))

    query = kaguya.esa1.select("2008-01-01", "2008-01-02")

    assert query.remote_files() == [
        "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz",
        "sln-l-pace-3-pbf1-v3.0/20080102/data/IPACE_PBF1_080102_ESA1_V003.dat.gz",
    ]


def test_kaguya_esa1_calibration_loads_local_store_tables(tmp_path) -> None:
    store = Store(tmp_path / "store")
    root = store.raw_path("kaguya", "calibration", "pace")
    fov_file = root / "public/FOV_ANGLE_070726/ESAS1/esas1-ch_angle"
    info_file = (
        root
        / "public/Kaguya_MAP_PACE_information/ESA-S1_ENE_POL_AZ_GFACTOR_4X16_20090828.dat"
    )
    fov_file.parent.mkdir(parents=True)
    info_file.parent.mkdir(parents=True)
    fov_file.write_text("AZ AZ64 AZ16\n3 22.5 67.5\n", encoding="utf-8")
    info_file.write_text(
        "\n".join(
            [
                "RAM ENE POL AZ ENERGY POLAR AZIMUTH GFACTOR ENE_SQNO POL_SQNO",
                "0 1 2 3 0.25 -12.5 90.0 4.5 6 7",
            ]
        ),
        encoding="utf-8",
    )

    kg = Kaguya(store=store)

    assert kg.esa1.calibration_remote_files()[:2] == [
        "public/FOV_ANGLE_070726/ESAS1/esas1-ch_angle",
        "public/FOV_ANGLE_070726/ESAS1/esas1-pol_angle-RAM0",
    ]
    assert kg.esa1.calibration_files(download="never") == [fov_file, info_file]

    calibration = kg.esa1.load_calibration(download="never")

    assert calibration.coverage("ESA1") == {"fov": True, "info": True}
    assert calibration.fov[0]["az64"][3] == pytest.approx(22.5)
    assert calibration.info[0]["gfactor_4x16"][0, 1, 2, 3] == pytest.approx(4.5)


def test_kaguya_esa1_calibration_download_registers_raw_manifest(
    tmp_path,
    monkeypatch,
) -> None:
    def fake_urlretrieve(url, target):
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"downloaded from {url}\n", encoding="utf-8")

    monkeypatch.setattr(kaguya_files, "urlretrieve", fake_urlretrieve)
    store = Store(tmp_path / "store")
    kg = Kaguya(store=store, download="missing")

    paths = kg.esa1.calibration_files()

    assert len(paths) == 11
    first = paths[0]
    manifest = (first.with_name(f"{first.name}.sopran.json")).read_text(encoding="utf-8")
    assert "kyoto-u-kaguya-pace-calibration" in manifest
    assert "public/FOV_ANGLE_070726/ESAS1/esas1-ch_angle" in manifest
    assert "http://step0ku.kugi.kyoto-u.ac.jp/~haraday/data/kaguya/" in manifest


def test_kaguya_time_filter_handles_string_times_with_subsecond_range() -> None:
    from sopran.missions.kaguya.mission import _filter_frame_by_time

    time = spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:00.000001Z")
    frame = pl.DataFrame({"time": ["2008-01-01T00:00:00Z"], "value": [1.0]})

    assert _filter_frame_by_time(frame, time).to_dicts() == [
        {"time": "2008-01-01T00:00:00Z", "value": 1.0}
    ]


def test_kaguya_time_filter_handles_timezone_aware_polars_datetime() -> None:
    from sopran.missions.kaguya.mission import _filter_frame_by_time

    time = spn.period("2008-01-01T00:00:00Z", "2008-01-01T00:00:01Z")
    frame = pl.DataFrame(
        {
            "time": pl.Series(
                [datetime(2008, 1, 1, 0, 0, tzinfo=UTC)],
                dtype=pl.Datetime("us", "UTC"),
            ),
            "value": [1.0],
        }
    )

    assert _filter_frame_by_time(frame, time).select("value").to_series().to_list() == [
        1.0
    ]


def test_kaguya_time_filter_handles_polars_date_with_subday_range() -> None:
    from datetime import date

    from sopran.missions.kaguya.mission import _filter_frame_by_time

    time = spn.period("2008-01-01T12:00:00Z", "2008-01-01T13:00:00Z")
    frame = pl.DataFrame(
        {
            "time": pl.Series([date(2008, 1, 1), date(2008, 1, 2)], dtype=pl.Date),
            "value": [1.0, 2.0],
        }
    )

    assert _filter_frame_by_time(frame, time).select("value").to_series().to_list() == [
        1.0
    ]


def test_kaguya_lmag_query_builds_nominal_and_optional_paths(tmp_path) -> None:
    kaguya = Kaguya(store=Store(tmp_path / "store"))

    query = kaguya.lmag.select("2008-11-01")

    assert query.remote_files() == [
        "sln-l-lmag-3-mag-ts-v1.0/nominal/20081101/data/MAG_TS20081101.dat",
        "sln-l-lmag-3-mag-ts-v1.0/optional/20081101/data/MAG_TSOP20081101.dat",
    ]


def test_kaguya_query_resolves_existing_files_from_fallback_cache(tmp_path) -> None:
    store = Store(tmp_path / "store")
    fallback = tmp_path / "legacy_public"
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    cached = fallback / remote_file
    cached.parent.mkdir(parents=True)
    cached.write_text("cached", encoding="utf-8")

    kaguya = Kaguya(store=store, fallback_roots=[fallback])

    files = kaguya.esa1.select("2008-01-01").files(download="never")

    assert files == [cached]


def test_kaguya_query_download_never_omits_missing_files(tmp_path) -> None:
    kaguya = Kaguya(store=Store(tmp_path / "store"))

    files = kaguya.esa1.select("2008-01-01").files(download="never")

    assert files == []


def test_kaguya_defaults_to_missing_download_policy(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SOPRAN_DOWNLOAD_MODE", raising=False)
    monkeypatch.delenv("SOPRAN_OFFLINE", raising=False)

    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    assert kg.download == "missing"


def test_period_is_half_open_and_available_from_top_level() -> None:
    time = spn.period("2008-02-01", "2008-02-02")

    assert time.start_iso == "2008-02-01T00:00:00Z"
    assert time.stop_iso == "2008-02-02T00:00:00Z"
    assert time.days() == ["2008-02-01"]


def test_period_iso_preserves_subsecond_precision_when_needed() -> None:
    time = spn.period("2008-02-01T00:00:00Z", "2008-02-01T00:00:00.000001Z")

    assert time.start_iso == "2008-02-01T00:00:00Z"
    assert time.stop_iso == "2008-02-01T00:00:00.000001Z"


def test_day_month_and_year_helpers_return_half_open_periods() -> None:
    assert spn.day("2008-02-01").days() == ["2008-02-01"]

    month = spn.month("2008-02")
    assert month.start_iso == "2008-02-01T00:00:00Z"
    assert month.stop_iso == "2008-03-01T00:00:00Z"

    year = spn.year("2008")
    assert year.start_iso == "2008-01-01T00:00:00Z"
    assert year.stop_iso == "2009-01-01T00:00:00Z"


def test_kaguya_esa1_energy_flux_endpoint_exposes_schema_info_and_plan(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.period("2008-02-01", "2008-02-02")

    endpoint = kg.esa1.energy_flux

    assert kg.esa1.eflux is endpoint
    assert "KAGUYA.ESA1.energy_flux" in str(endpoint.info())
    assert endpoint.schema().name == "energy_flux"

    plan = endpoint.plan(time)

    assert plan.dataset_id == "kaguya.esa1.energy_flux"
    assert plan.time == time
    assert plan.remote_files == [
        "sln-l-pace-3-pbf1-v3.0/20080201/data/IPACE_PBF1_080201_ESA1_V003.dat.gz"
    ]


def test_kaguya_esa1_energy_schema_marks_channel_index_not_physical_ev(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    schema = kg.esa1.energy.schema()

    assert schema.units is None
    assert "channel index" in schema.description
    assert "Physical eV calibration is not applied" in schema.description


def test_kaguya_spectrogram_endpoint_preserves_log_color_option(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.period("2008-02-01", "2008-02-02")

    item = kg.esa1.counts.spectrogram(time, y="energy", log_color=True)

    assert item.log_color is True


def test_kaguya_mission_and_esa1_instrument_are_discoverable(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.period("2008-02-01", "2008-02-02")

    assert "KAGUYA" in str(kg.info())
    assert "esa1" in str(kg.info())

    assert kg.esa1.schema().instrument == "esa1"
    assert kg.esa1.plan(time).dataset_id == "kaguya.esa1"
    assert "energy_flux" in str(kg.esa1.info())


def test_kaguya_pace_ion_instruments_expose_esa_style_spectrum_api(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")
    time = spn.period("2008-02-01", "2008-02-02")
    instruments = {
        "ESA2": kg.esa2,
        "IMA": kg.ima,
        "IEA": kg.iea,
    }

    for sensor, instrument in instruments.items():
        sensor_key = sensor.lower()
        data = instrument.load(time)

        assert instrument.schema().instrument == sensor_key
        assert instrument.counts.schema().dims == ("time", "energy", "look")
        assert instrument.energy_flux.schema().dims == ("time", "energy", "look")
        assert instrument.energy.schema().dims == ("energy",)
        assert instrument.quality.schema().dims == ("time",)
        assert instrument.plan(time).dataset_id == f"kaguya.{sensor_key}"
        assert instrument.counts.plan(time).dataset_id == f"kaguya.{sensor_key}.counts"
        assert instrument.counts.plan(time).remote_files == [
            (
                "sln-l-pace-3-pbf1-v3.0/20080201/data/"
                f"IPACE_PBF1_080201_{sensor}_V003.dat.gz"
            )
        ]
        assert data.instrument == sensor
        assert data.counts.name == "counts"
        assert data.energy_flux.name == "energy_flux"
        assert data.eflux is data.energy_flux
        assert data.to_xarray().attrs["instrument"] == sensor


def test_top_level_load_dispatches_kaguya_pace_spectrum_ids(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.period("2008-02-01", "2008-02-02")

    for sensor in ("esa2", "ima", "iea"):
        data = spn.load(f"kaguya.{sensor}", time, store=store, download="never")
        counts = spn.load(f"kaguya.{sensor}.counts", time, store=store, download="never")

        assert data.instrument == sensor.upper()
        assert counts.name == "counts"
        assert counts.schema.description == f"Raw {sensor.upper()} counts."


def test_kaguya_guides_return_markdown_pages(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    mission_guide = kg.guide()
    esa1_guide = kg.esa1.guide()
    ima_guide = kg.ima.guide()
    energy_flux_guide = kg.esa1.energy_flux.guide()

    assert mission_guide.language == "ja"
    assert "KAGUYA/SELENE" in str(mission_guide)
    assert "KAGUYA/SELENE は SOPRAN" in str(mission_guide)
    assert "PACE ESA1" in str(esa1_guide)
    assert "energy_flux" in energy_flux_guide.to_markdown()
    assert "| name | dims | units | dtype | frame | aliases | description |" in (
        esa1_guide.to_markdown()
    )
    assert "| energy_flux | time, energy, look |" in esa1_guide.to_markdown()
    assert "eflux, differential_energy_flux" in esa1_guide.to_markdown()
    assert "q, quality_flag" in esa1_guide.to_markdown()
    assert kg.guide("esa1") == esa1_guide
    assert kg.guide("ima") == ima_guide
    assert kg.help() == mission_guide
    assert kg.help("esa1") == esa1_guide
    assert kg.help("ima") == ima_guide
    assert kg.esa1.help() == esa1_guide
    assert kg.esa1.energy_flux.help() == energy_flux_guide
    assert energy_flux_guide.source == "sopran.missions.kaguya/ESA1.ja.md"
    assert mission_guide.url == "https://nkzono99.github.io/sopran/missions/kaguya/"
    assert esa1_guide.url == "https://nkzono99.github.io/sopran/missions/kaguya/esa1/"
    assert energy_flux_guide.url == esa1_guide.url
    assert "# KAGUYA/SELENE" in mission_guide._repr_markdown_()


def test_kaguya_guides_can_switch_language(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    mission_ja = kg.guide(language="ja")
    mission_en = kg.guide(language="en")
    esa1_ja = kg.esa1.guide(language="ja")
    energy_flux_ja = kg.esa1.energy_flux.guide(language="ja")

    assert mission_ja.language == "ja"
    assert mission_en.language == "en"
    assert mission_ja.available_languages == ("ja", "en")
    assert mission_ja.language_switcher() == "Lang: 日本語/English"
    assert mission_ja.source == "sopran.missions.kaguya/README.ja.md"
    assert mission_ja.with_language("en").source == "sopran.missions.kaguya/README.md"
    assert mission_ja.with_language("en").url == (
        "https://nkzono99.github.io/sopran/missions/kaguya/"
    )
    assert esa1_ja.with_language("en").url == (
        "https://nkzono99.github.io/sopran/missions/kaguya/esa1/"
    )
    assert "KAGUYA/SELENE は SOPRAN" in mission_ja.to_markdown()
    assert "vertical slice" in mission_en.to_markdown()
    assert "PACE ESA1 は" in esa1_ja.to_markdown()
    assert "| name | dims | units | dtype | frame | aliases | description |" in (
        esa1_ja.to_markdown()
    )
    assert "energy_flux" in energy_flux_ja.to_markdown()
    assert "vertical slice" in mission_ja.to_markdown(language="en")
    assert kg.help(language="ja") == mission_ja
    assert kg.guide("esa1", language="ja") == esa1_ja
    assert kg.help("esa1", language="ja") == esa1_ja
    assert kg.esa1.help(language="ja") == esa1_ja
    assert kg.esa1.energy_flux.help(language="ja") == energy_flux_ja
    with pytest.raises(ValueError, match="language"):
        kg.guide(language="fr")


def test_kaguya_examples_return_markdown_pages(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    mission_example = kg.example().to_markdown()
    instrument_example = kg.esa1.example().to_markdown()
    variable_example = kg.esa1.counts.example().to_markdown()

    assert "kg = spn.Kaguya" in mission_example
    assert "kg.esa1.counts.load(time)" in instrument_example
    assert "kg.esa1.counts.load(time)" in variable_example
    assert "spn.stack" in variable_example


def test_kaguya_esa1_load_returns_typed_data_object_without_downloading(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")
    time = spn.period("2008-02-01", "2008-02-02")

    esa1 = kg.esa1.load(time)

    assert esa1.instrument == "ESA1"
    assert esa1.time == time
    assert esa1.energy_flux.name == "energy_flux"
    assert esa1.eflux is esa1.energy_flux
    with pytest.raises(ValueError, match="energy_flux requires PACE INFO calibration"):
        kg.esa1.energy_flux.load(time)


def test_kaguya_esa1_load_missing_error_rejects_silent_empty_dataset(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")
    time = spn.period("2008-02-01", "2008-02-02")

    with pytest.raises(FileNotFoundError, match="No local KAGUYA ESA1 raw files found"):
        kg.esa1.load(time, missing="error")

    with pytest.raises(FileNotFoundError, match="IPACE_PBF1_080201_ESA1_V003.dat.gz"):
        kg.esa1.counts.load(time, missing="error")


def test_kaguya_esa1_load_missing_warn_records_missing_reason(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")
    time = spn.period("2008-02-01", "2008-02-02")

    with pytest.warns(UserWarning, match="No local KAGUYA ESA1 raw files found"):
        data = kg.esa1.load(time, missing="warn")

    assert data.missing_reason.startswith("No local KAGUYA ESA1 raw files found")
    assert "missing_reason:" in str(data.info())
    assert data.to_xarray().attrs["missing_reason"] == data.missing_reason


def test_kaguya_esa1_loaded_data_info_returns_info_page(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")
    time = spn.period("2008-02-01", "2008-02-02")

    info = kg.esa1.load(time).info()

    assert isinstance(info, spn.InfoPage)
    assert info.title == "KAGUYA.ESA1"
    assert "time: 2008-02-01T00:00:00Z to 2008-02-02T00:00:00Z" in str(info)
    assert "variables: energy_flux, counts, energy, quality" in str(info)
    assert "files: 0" in str(info)


def test_kaguya_uses_mission_default_download_policy(tmp_path) -> None:
    class FakeSource:
        def __init__(self, root):
            self.root = root
            self.downloaded = []

        def local_path(self, remote_file):
            return self.root / remote_file

        def download(self, remote_file, *, overwrite=False):
            self.downloaded.append((remote_file, overwrite))
            path = self.local_path(remote_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"downloaded")
            return path

    source = FakeSource(tmp_path / "raw")
    kg = spn.Kaguya(store=Store(tmp_path / "store"), source=source, download="missing")

    data = kg.esa1.load(spn.day("2008-01-01"))

    assert data.files == (source.local_path(source.downloaded[0][0]),)
    assert source.downloaded[0][1] is False


def test_kaguya_download_registers_raw_file_manifest(tmp_path, monkeypatch) -> None:
    store = Store(tmp_path / "store")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"

    def fake_urlretrieve(url, target):
        Path(target).write_bytes(b"downloaded")
        return target, None

    monkeypatch.setattr(kaguya_files, "urlretrieve", fake_urlretrieve)
    kg = spn.Kaguya(store=store, download="missing")

    data = kg.esa1.load(spn.day("2008-01-01"))

    assert data.files == (store.raw_path("kaguya", "pds3") / remote_file,)
    record = store.raw_file(Path("kaguya") / "pds3" / remote_file)
    manifest = record.manifest()
    assert manifest["mission"] == "kaguya"
    assert manifest["provider"] == "darts-pds3"
    assert manifest["provider_path"] == remote_file
    assert manifest["version"] == "v3.0"
    assert manifest["download_url"] == kg.source.remote_url(remote_file)
    assert manifest["size_bytes"] == len(b"downloaded")
    assert record.verify_checksum()


def test_kaguya_file_source_download_removes_partial_file_on_failure(
    tmp_path,
    monkeypatch,
) -> None:
    source = kaguya_files.KaguyaFileSource(tmp_path / "raw")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    target = source.local_root / remote_file

    def fake_urlretrieve(url, target):
        Path(target).write_bytes(b"partial")
        raise OSError("network interrupted")

    monkeypatch.setattr(kaguya_files, "urlretrieve", fake_urlretrieve)

    with pytest.raises(OSError, match="network interrupted"):
        source.download(remote_file)

    assert not target.exists()
    assert list(target.parent.glob(f"{target.name}.*.tmp")) == []


def test_kaguya_file_source_overwrite_failure_preserves_existing_file(
    tmp_path,
    monkeypatch,
) -> None:
    source = kaguya_files.KaguyaFileSource(tmp_path / "raw")
    remote_file = "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    target = source.local_root / remote_file
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing")

    def fake_urlretrieve(url, target):
        Path(target).write_bytes(b"partial")
        raise OSError("network interrupted")

    monkeypatch.setattr(kaguya_files, "urlretrieve", fake_urlretrieve)

    with pytest.raises(OSError, match="network interrupted"):
        source.download(remote_file, overwrite=True)

    assert target.read_bytes() == b"existing"
    assert list(target.parent.glob(f"{target.name}.*.tmp")) == []


def test_kaguya_reads_default_download_policy_from_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SOPRAN_DOWNLOAD_MODE", "missing")

    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    assert kg.download == "missing"

    monkeypatch.setenv("SOPRAN_OFFLINE", "1")

    offline = spn.Kaguya(store=Store(tmp_path / "store"))

    assert offline.download == "never"


def test_kaguya_esa1_exposes_core_variable_endpoints(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")
    time = spn.period("2008-02-01", "2008-02-02")

    assert kg.esa1.counts.schema().dims == ("time", "energy", "look")
    assert kg.esa1.energy.schema().dims == ("energy",)
    assert kg.esa1.quality.schema().dims == ("time",)
    assert kg.esa1.counts.load(time).name == "counts"


def test_kaguya_endpoint_discovery_does_not_touch_source_io(tmp_path) -> None:
    class ExplodingSource:
        def __init__(self) -> None:
            self.calls = []

        def local_path(self, remote_file):
            self.calls.append(("local_path", remote_file))
            raise AssertionError("local_path should not be called during discovery")

        def remote_url(self, remote_file):
            self.calls.append(("remote_url", remote_file))
            raise AssertionError("remote_url should not be called during discovery")

        def download(self, remote_file, *, overwrite=False):
            self.calls.append(("download", remote_file, overwrite))
            raise AssertionError("download should not be called during discovery")

    source = ExplodingSource()
    kg = spn.Kaguya(store=Store(tmp_path / "store"), source=source, download="never")
    time = spn.day("2008-01-01")

    endpoints = [
        kg.esa1.counts,
        kg.ima.counts,
        kg.lmag.magnetic_field,
        kg.lrs.npw_rx1,
    ]

    assert [endpoint.name for endpoint in endpoints] == [
        "counts",
        "counts",
        "magnetic_field",
        "npw_rx1",
    ]
    assert [endpoint.schema().name for endpoint in endpoints] == [
        "counts",
        "counts",
        "magnetic_field",
        "npw_rx1",
    ]
    assert kg.esa1.counts.plan(time).remote_files == [
        "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz"
    ]
    assert kg.ima.counts.plan(time).remote_files == [
        "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_IMA_V003.dat.gz"
    ]
    assert "KAGUYA.ESA1.counts" in str(kg.esa1.counts.info())
    assert "KAGUYA.IMA.counts" in str(kg.ima.counts.info())
    assert source.calls == []


def test_kaguya_esa1_to_xarray_returns_schema_backed_empty_dataset(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"), download="never")
    time = spn.period("2008-02-01", "2008-02-02")

    ds = kg.esa1.load(time).to_xarray()

    assert ds.attrs["mission"] == "kaguya"
    assert ds.attrs["instrument"] == "ESA1"
    assert set(ds.data_vars) == {"energy_flux", "counts", "quality"}
    assert "energy" in ds.coords
    assert ds["energy"].attrs["description"].startswith("PACE ESA1 energy channel index")
    assert "units" not in ds["energy"].attrs
    assert ds["energy_flux"].attrs["physical_validity"] == "placeholder"
    assert ds["energy_flux"].attrs["calibration_status"] == "not_loaded"


def test_kaguya_esa1_counts_reduce_look_handles_mixed_record_shapes() -> None:
    first_time = datetime(2008, 8, 2, 0, 0, tzinfo=UTC).timestamp()
    second_time = datetime(2008, 8, 2, 0, 1, tzinfo=UTC).timestamp()
    first = PaceRecord(
        type=0x01,
        index=0,
        arrays={"cnt": np.ones((32, 4, 16), dtype=np.uint16)},
    )
    second = PaceRecord(
        type=0x00,
        index=1,
        arrays={"cnt": np.full((32, 16, 64), 2, dtype=np.uint16)},
    )
    pace = PaceData(
        sensor=0,
        headers=(
            {"time": first_time, "data_quality": 0},
            {"time": second_time, "data_quality": 0},
        ),
        records={0x01: (first,), 0x00: (second,)},
        source_files=(),
        record_order=(first, second),
    )
    data = KaguyaESA1Data(time=spn.day("2008-08-02"))
    object.__setattr__(data, "pace", pace)

    frame = data.to_polars("counts", reduce_look="sum")

    assert frame.shape == (64, 3)
    rows = frame.filter(pl.col("energy") == 0).sort("time").to_dicts()
    assert rows[0]["counts"] == 64
    assert rows[1]["counts"] == 2048


def test_kaguya_esa1_counts_masks_pace_fill_value() -> None:
    sample_time = datetime(2008, 8, 2, 0, 0, tzinfo=UTC).timestamp()
    counts = np.ones((32, 4, 16), dtype=np.uint16)
    counts[0, :, :] = 65535
    record = PaceRecord(type=0x01, index=0, arrays={"cnt": counts})
    pace = PaceData(
        sensor=0,
        headers=({"time": sample_time, "data_quality": 0},),
        records={0x01: (record,)},
        source_files=(),
        record_order=(record,),
    )
    data = KaguyaESA1Data(time=spn.day("2008-08-02"))
    object.__setattr__(data, "pace", pace)

    dataset = data.to_xarray()
    frame = data.to_polars("counts", reduce_look="sum")

    assert np.isnan(dataset["counts"].values[0, 0, 0])
    assert np.isnan(frame.filter(pl.col("energy") == 0)["counts"][0])
    assert frame.filter(pl.col("energy") == 1)["counts"][0] == 64


def test_kaguya_esa1_to_xarray_pads_mixed_look_record_shapes() -> None:
    first_time = datetime(2008, 8, 2, 0, 0, tzinfo=UTC).timestamp()
    second_time = datetime(2008, 8, 2, 0, 1, tzinfo=UTC).timestamp()
    first = PaceRecord(
        type=0x01,
        index=0,
        arrays={"cnt": np.ones((32, 4, 16), dtype=np.uint16)},
    )
    second = PaceRecord(
        type=0x00,
        index=1,
        arrays={"cnt": np.full((32, 16, 64), 2, dtype=np.uint16)},
    )
    pace = PaceData(
        sensor=0,
        headers=(
            {"time": first_time, "data_quality": 0},
            {"time": second_time, "data_quality": 0},
        ),
        records={0x01: (first,), 0x00: (second,)},
        source_files=(),
        record_order=(first, second),
    )
    data = KaguyaESA1Data(time=spn.day("2008-08-02"))
    object.__setattr__(data, "pace", pace)

    dataset = data.to_xarray()

    assert dataset["counts"].shape == (2, 32, 1024)
    assert dataset["counts"].values[0, 0, 0] == 1
    assert np.isnan(dataset["counts"].values[0, 0, 64])
    assert dataset["counts"].values[1, 0, 1023] == 2


def test_kaguya_esa1_to_polars_uses_array_layout_for_unreduced_counts() -> None:
    sample_time = datetime(2008, 8, 2, 0, 0, tzinfo=UTC).timestamp()
    record = PaceRecord(
        type=0x01,
        index=0,
        arrays={"cnt": np.ones((32, 4, 16), dtype=np.uint16)},
    )
    pace = PaceData(
        sensor=0,
        headers=({"time": sample_time, "data_quality": 0},),
        records={0x01: (record,)},
        source_files=(),
        record_order=(record,),
    )
    data = KaguyaESA1Data(time=spn.day("2008-08-02"))
    object.__setattr__(data, "pace", pace)

    frame = data.to_polars("counts")

    assert frame.shape == (1, 2)
    assert frame.columns == ["time", "counts"]
    assert frame.schema["counts"] == pl.Array(pl.Float64, shape=(32, 64))


def test_kaguya_esa1_to_polars_rejects_large_long_table_when_requested() -> None:
    sample_time = datetime(2008, 8, 2, 0, 0, tzinfo=UTC).timestamp()
    record = PaceRecord(
        type=0x01,
        index=0,
        arrays={"cnt": np.ones((32, 4, 16), dtype=np.uint16)},
    )
    pace = PaceData(
        sensor=0,
        headers=({"time": sample_time, "data_quality": 0},),
        records={0x01: (record,)},
        source_files=(),
        record_order=(record,),
    )
    data = KaguyaESA1Data(time=spn.day("2008-08-02"))
    object.__setattr__(data, "pace", pace)

    with pytest.raises(ValueError, match="would create 2048 rows"):
        data.to_polars("counts", layout="long", max_rows=100)

    frame = data.to_polars("counts", layout="long", max_rows=100, allow_large=True)

    assert frame.shape == (2048, 4)


def test_kaguya_esa1_variable_typo_suggests_available_endpoint(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    with pytest.raises(AttributeError) as exc:
        _ = kg.esa1.flux

    message = str(exc.value)
    assert "Kaguya.ESA1 has no variable 'flux'" in message
    assert "energy_flux" in message
    assert "kg.esa1.info()" in message


def test_kaguya_esa1_variable_typo_uses_schema_aliases_for_suggestion(
    tmp_path,
) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    with pytest.raises(AttributeError) as exc:
        _ = kg.esa1.qualty

    message = str(exc.value)
    assert "Kaguya.ESA1 has no variable 'qualty'" in message
    assert "Available variables:" in message
    assert "quality" in message
    assert "Did you mean:\n  quality?" in message
    assert "kg.esa1.quality.load(time)" in message


def test_kaguya_esa1_variable_alias_typo_suggests_canonical_variable(
    tmp_path,
) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    with pytest.raises(AttributeError) as exc:
        _ = kg.esa1.quality_flag

    message = str(exc.value)
    assert "Kaguya.ESA1 has no variable 'quality_flag'" in message
    assert "Did you mean:\n  quality?" in message
    assert "kg.esa1.quality.load(time)" in message


def test_kaguya_esa1_load_without_time_explains_required_period(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    with pytest.raises(ValueError) as exc:
        kg.esa1.energy_flux.load()

    message = str(exc.value)
    assert "Time range is required for Kaguya.ESA1.energy_flux" in message
    assert 'time = spn.period("2008-02-01", "2008-02-02")' in message


def test_kaguya_esa1_variable_load_without_time_uses_endpoint_examples(
    tmp_path,
) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    with pytest.raises(ValueError) as exc:
        kg.esa1.quality.load()

    message = str(exc.value)
    assert "Time range is required for Kaguya.ESA1.quality" in message
    assert "kg.esa1.quality.load(time)" in message
    assert "case.kaguya.esa1.quality.load()" in message
    assert "kg.esa1.energy_flux.load(time)" not in message


def test_kaguya_esa1_instrument_load_without_time_uses_instrument_examples(
    tmp_path,
) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))

    with pytest.raises(ValueError) as exc:
        kg.esa1.load()

    message = str(exc.value)
    assert "Time range is required for Kaguya.ESA1" in message
    assert "kg.esa1.load(time)" in message
    assert "case.kaguya.esa1.load()" in message
    assert "kg.esa1.energy_flux.load(time)" not in message


def test_kaguya_esa1_pipeline_records_lazy_stage_plan(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.month("2008-02")

    pipe = (
        kg.esa1.pipeline(time)
        .download()
        .decode()
        .normalize()
        .select_variables("energy_flux", "counts", "quality")
        .quicklook(
            "esa1_counts",
            frame="SSE",
            aggregation={"mode": "native", "note": "pipeline-plan"},
        )
        .write("kaguya.esa1.normalized", layer="normalized")
    )

    plan = pipe.plan()

    assert plan.source == "kaguya.esa1"
    assert plan.time == time
    assert plan.stage_names == (
        "download",
        "decode",
        "normalize",
        "select_variables",
        "quicklook",
        "write",
    )
    assert plan.output_dataset == "kaguya.esa1.normalized"
    assert plan.output_layer == "normalized"
    quicklook_stage = plan.stages[4]
    assert quicklook_stage.parameters["frame"] == "SSE"
    assert quicklook_stage.parameters["aggregation"] == {
        "mode": "native",
        "note": "pipeline-plan",
    }


def test_pipeline_write_accepts_database_product_reference(tmp_path) -> None:
    store = Store(tmp_path / "store")
    kg = spn.Kaguya(store=store)
    product = store.database("wake_events").product("raw_counts")

    pipe = (
        kg.esa1.pipeline(spn.month("2008-02"))
        .decode()
        .select_variables("counts")
        .write(product)
    )

    plan = pipe.plan()

    assert product.dataset_id == "wake_events.raw_counts"
    assert product.layer == "databases"
    assert plan.output_dataset == "wake_events.raw_counts"
    assert plan.output_layer == "databases"


def test_pipeline_scan_reads_stored_normalized_variable(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.day("2008-01-01")
    frame = pl.DataFrame(
        {
            "time": ["2008-01-01T00:00:08Z", "2008-01-02T00:00:08Z"],
            "energy": [0, 0],
            "counts": [64, 128],
        }
    )
    store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=frame,
    )
    kg = spn.Kaguya(store=store)

    lazy = kg.esa1.pipeline(time).from_normalized().select_variables("counts").scan()

    assert lazy.collect().to_dicts() == [
        {"time": "2008-01-01T00:00:08Z", "energy": 0, "counts": 64}
    ]


def test_endpoint_pipeline_scan_reads_default_normalized_variable(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.day("2008-01-01")
    frame = pl.DataFrame(
        {
            "time": ["2008-01-01T00:00:08Z", "2008-01-02T00:00:08Z"],
            "energy": [0, 0],
            "counts": [64, 128],
        }
    )
    store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=frame,
    )
    kg = spn.Kaguya(store=store)

    lazy = kg.esa1.counts.pipeline(time).from_normalized().scan()

    assert lazy.collect().to_dicts() == [
        {"time": "2008-01-01T00:00:08Z", "energy": 0, "counts": 64}
    ]


def test_pipeline_scan_filters_datetime_time_column(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.day("2008-01-01")
    frame = pl.DataFrame(
        {
            "time": [
                datetime(2008, 1, 1, 0, 0, 8),
                datetime(2008, 1, 2, 0, 0, 8),
            ],
            "energy": [0, 0],
            "counts": [64, 128],
        }
    )
    store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=frame,
    )
    kg = spn.Kaguya(store=store)

    rows = (
        kg.esa1.pipeline(time)
        .from_normalized()
        .select_variables("counts")
        .scan()
        .collect()
        .to_dicts()
    )

    assert len(rows) == 1
    assert rows[0]["counts"] == 64


def test_pipeline_collect_materializes_stored_normalized_data(tmp_path) -> None:
    store = Store(tmp_path / "store")
    time = spn.day("2008-01-01")
    frame = pl.DataFrame({"time": ["2008-01-01T00:00:08Z"], "energy": [0], "counts": [64]})
    store.write_parquet_dataset(
        dataset_id="kaguya.esa1.counts",
        layer="normalized",
        mission="kaguya",
        instrument="esa1",
        product="counts",
        schema=KAGUYA_ESA1_SCHEMA,
        time_coverage=time,
        frame=frame,
    )
    kg = spn.Kaguya(store=store)

    collected = kg.esa1.pipeline(time).from_normalized().select_variables("counts").collect()

    assert collected.to_dicts() == frame.to_dicts()


def test_pipeline_dry_run_returns_result_without_executing(tmp_path) -> None:
    kg = spn.Kaguya(store=Store(tmp_path / "store"))
    time = spn.month("2008-02")
    pipe = (
        kg.esa1.pipeline(time)
        .download()
        .decode()
        .select_variables("counts")
        .write(
            "kaguya.esa1.counts",
            layer="normalized",
        )
    )

    result = pipe.run(dry_run=True, download="always")

    assert result.status == "planned"
    assert result.run_parameters == {
        "download": "always",
        "dry_run": True,
        "mode": "create",
        "on_error": "fail",
        "only_failed": False,
        "resume": False,
    }
    assert result.plan.stage_names == ("download", "decode", "select_variables", "write")
    assert result.plan.output_dataset == "kaguya.esa1.counts"
    assert result.plan.to_dict() == {
        "source": "kaguya.esa1",
        "start": "2008-02-01T00:00:00Z",
        "stop": "2008-03-01T00:00:00Z",
        "output_dataset": "kaguya.esa1.counts",
        "output_layer": "normalized",
        "stages": [
            {"name": "download", "parameters": {}},
            {"name": "decode", "parameters": {}},
            {"name": "select_variables", "parameters": {"names": ["counts"]}},
            {
                "name": "write",
                "parameters": {"dataset": "kaguya.esa1.counts", "layer": "normalized"},
            },
        ],
    }
    assert result.to_dict()["run_parameters"] == result.run_parameters
    text = str(result)
    assert "SOPRAN pipeline result" in text
    assert "status: planned" in text
    assert "run: dry_run=True mode='create' download='always'" in text
    assert "source: kaguya.esa1" in text
    assert "time: 2008-02-01T00:00:00Z .. 2008-03-01T00:00:00Z" in text
    assert "output: kaguya.esa1.counts (normalized)" in text
    assert "- select_variables names=['counts']" in text


def test_project_case_supplies_time_to_kaguya_endpoints(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sopran.toml").write_text(
        """
[defaults]
download = "never"

[cases.wake_20080201]
start = "2008-02-01T00:00:00"
stop = "2008-02-02T00:00:00"
""".strip(),
        encoding="utf-8",
    )

    project = spn.Project(project_root, store=Store(tmp_path / "store"))
    case = project.case("wake_20080201")

    esa1 = case.kaguya.esa1.load()
    plan = case.kaguya.esa1.energy_flux.plan()

    assert esa1.time == case.time
    assert plan.time == case.time
    assert plan.remote_files == [
        "sln-l-pace-3-pbf1-v3.0/20080201/data/IPACE_PBF1_080201_ESA1_V003.dat.gz"
    ]
    with pytest.raises(ValueError, match="energy_flux requires PACE INFO calibration"):
        case.kaguya.esa1.energy_flux.load()
