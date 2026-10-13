from __future__ import annotations

import tomllib

import pytest

import sopran as spn


def test_session_config_use_sets_default_store_for_shortcuts(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SOPRAN_CONFIG", str(tmp_path / "missing-config.toml"))
    monkeypatch.delenv("SOPRAN_DATA_ROOT", raising=False)
    monkeypatch.delenv("SOPRAN_CACHE_ROOT", raising=False)
    session_store = tmp_path / "session_data"
    session_cache = tmp_path / "session_cache"

    spn.config.use(store=session_store, cache_root=session_cache, download="never")
    try:
        current = spn.config.current()

        assert current.store_root == session_store
        assert current.cache_root == session_cache
        assert current.download == "never"
        assert spn.Store().root == session_store
        assert spn.Store().cache_root == session_cache
        assert spn.Project.default().store.root == session_store
        assert spn.view().metadata()["store"]["root"] == str(session_store)
        assert spn.Project.default().view().context.download == "never"
    finally:
        spn.config.reset()


def test_session_config_using_restores_previous_defaults(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOPRAN_CONFIG", str(tmp_path / "missing-config.toml"))
    monkeypatch.delenv("SOPRAN_DATA_ROOT", raising=False)
    monkeypatch.delenv("SOPRAN_CACHE_ROOT", raising=False)
    first_store = tmp_path / "first"
    second_store = tmp_path / "second"

    spn.config.use(store=first_store)
    try:
        with spn.config.using(store=second_store, download="missing"):
            assert spn.Store().root == second_store
            assert spn.Project.default().view().context.download == "missing"

        assert spn.Store().root == first_store
        assert spn.config.current().download is None
    finally:
        spn.config.reset()


def test_explicit_store_roots_override_session_config(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOPRAN_CONFIG", str(tmp_path / "missing-config.toml"))
    monkeypatch.delenv("SOPRAN_DATA_ROOT", raising=False)
    monkeypatch.delenv("SOPRAN_CACHE_ROOT", raising=False)
    explicit_store = spn.Store(tmp_path / "explicit", cache_root=tmp_path / "explicit_cache")

    spn.config.use(store=tmp_path / "session", cache_root=tmp_path / "session_cache")
    try:
        assert explicit_store.root == tmp_path / "explicit"
        assert explicit_store.cache_root == tmp_path / "explicit_cache"
        assert spn.Project.default(store=explicit_store).store.root == tmp_path / "explicit"
    finally:
        spn.config.reset()


def test_save_user_config_writes_store_and_defaults(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("SOPRAN_CONFIG", str(config_path))
    monkeypatch.delenv("SOPRAN_DATA_ROOT", raising=False)
    monkeypatch.delenv("SOPRAN_CACHE_ROOT", raising=False)

    written = spn.config.save_user(
        store=tmp_path / "saved_store",
        cache_root=tmp_path / "saved_cache",
        download="never",
    )

    assert written == config_path
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config["store"]["data_root"] == str(tmp_path / "saved_store")
    assert config["store"]["cache_root"] == str(tmp_path / "saved_cache")
    assert config["defaults"]["download"] == "never"
    assert spn.Store().root == tmp_path / "saved_store"
    assert spn.Store().cache_root == tmp_path / "saved_cache"


def _isolate_config(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SOPRAN_CONFIG", str(tmp_path / "missing-config.toml"))
    for name in (
        "SOPRAN_DATA_ROOT",
        "SOPRAN_CACHE_ROOT",
        "SOPRAN_OFFLINE",
        "SOPRAN_DOWNLOAD_MODE",
    ):
        monkeypatch.delenv(name, raising=False)
    spn.config.reset()


def test_every_entry_point_defaults_to_the_same_store(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config(tmp_path, monkeypatch)
    expected = tmp_path / "sopran_data"

    assert spn.Store().root.resolve() == expected.resolve()
    assert spn.Store().cache_root.resolve() == (expected / "cache").resolve()
    assert spn.Kaguya().store.root.resolve() == expected.resolve()
    assert spn.Project.default().store.root.resolve() == expected.resolve()
    assert spn.kaguya.store.root.resolve() == expected.resolve()


def test_store_uses_the_discovered_project_store(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config(tmp_path, monkeypatch)
    (tmp_path / "sopran.toml").write_text(
        '[store]\ndata_root = "data"\ncache_root = "cache"\n',
        encoding="utf-8",
    )
    nested = tmp_path / "notebooks"
    nested.mkdir()
    monkeypatch.chdir(nested)

    assert spn.Store().root.resolve() == (tmp_path / "data").resolve()
    assert spn.Store().cache_root.resolve() == (tmp_path / "cache").resolve()
    assert spn.Kaguya().store.root == spn.kaguya.store.root


def test_environment_download_policy_outranks_file_defaults(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config(tmp_path, monkeypatch)
    user_config = tmp_path / "user.toml"
    user_config.write_text('[defaults]\ndownload = "always"\n', encoding="utf-8")
    monkeypatch.setenv("SOPRAN_CONFIG", str(user_config))
    (tmp_path / "sopran.toml").write_text(
        '[defaults]\ndownload = "missing"\n\n'
        '[cases.c]\nstart = "2008-02-01"\nstop = "2008-02-02"\ndownload = "always"\n',
        encoding="utf-8",
    )

    project = spn.Project(tmp_path)
    assert spn.Kaguya().download == "missing"
    assert spn.kaguya.download == "missing"
    assert project.case("c").kaguya.download == "always"

    monkeypatch.setenv("SOPRAN_OFFLINE", "1")
    assert spn.Kaguya().download == "never"
    assert spn.kaguya.download == "never"
    assert spn.view().context.download == "never"
    assert project.case("c").kaguya.download == "never"
    assert spn.Kaguya(download="missing").download == "missing"

    with spn.config.using(download="always"):
        assert spn.kaguya.download == "always"
        assert project.case("c").kaguya.download == "always"
