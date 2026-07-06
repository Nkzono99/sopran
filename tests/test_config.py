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
