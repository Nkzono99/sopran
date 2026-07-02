from __future__ import annotations

from sopran import Store
from sopran.missions.kaguya import Kaguya, normalize_sensors


def test_normalize_sensors_accepts_spedas_ids_and_names() -> None:
    assert normalize_sensors([0, "ESA-S2", "lmag", "esa1"]) == ["ESA1", "ESA2", "LMAG"]


def test_kaguya_esa1_query_builds_public_pbf_paths(tmp_path) -> None:
    kaguya = Kaguya(store=Store(tmp_path / "store"))

    query = kaguya.esa1.select("2008-01-01", "2008-01-02")

    assert query.remote_files() == [
        "sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz",
        "sln-l-pace-3-pbf1-v3.0/20080102/data/IPACE_PBF1_080102_ESA1_V003.dat.gz",
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
