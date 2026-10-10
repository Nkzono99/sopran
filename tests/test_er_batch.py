"""Day-sharded ER batch: export, prepare, resumable run, STOP and Store registration."""

import io
import json
import sqlite3
from dataclasses import replace

import numpy as np
import polars as pl
import pytest

from sopran.core.store import Store
from sopran.experimental.electron_reflection import (
    FiniteBinFitSettings,
    FiniteBinModel,
    FiniteBinObservation,
    FiniteBinParameters,
)
from sopran.experimental.kaguya import er_batch

ENERGY_EDGES = np.geomspace(20, 1500, 9)
PITCH_EDGES = np.linspace(0, 180, 17)
FAST = {"generations": 4, "seeds": 1, "beam_enabled": False}


def _ratio() -> np.ndarray:
    shape = (ENERGY_EDGES.size - 1, 8)
    dummy = FiniteBinObservation(
        ENERGY_EDGES, PITCH_EDGES[:9], np.ones(shape), np.zeros(shape), 5.0
    )
    model = FiniteBinModel(dummy, FiniteBinFitSettings(loss="huber", beam_enabled=False))
    truth = FiniteBinParameters(4.0, 0.15, -40.0, 0.9)
    return 10 ** model.evaluate(truth).fitted_log_ratio_dex


def _blob(rng: np.random.Generator, ratio: np.ndarray) -> bytes:
    energy = np.sqrt(ENERGY_EDGES[:-1] * ENERGY_EDGES[1:])
    expected = np.repeat((300 * (energy / 100) ** -1.0)[:, None], 8, axis=1)
    reference = rng.poisson(expected).astype(float) + 0.25  # redistributed, non-integer
    affected = rng.poisson(expected * ratio).astype(float)
    maps = dict(
        energy_eV=energy,
        energy_edges_eV=ENERGY_EDGES,
        pitch_edges_deg=PITCH_EDGES,
        affected_counts=affected,
        reference_counts=reference,
        affected_exposure=np.ones_like(affected),
        reference_exposure=np.ones_like(affected),
        global_counts=np.zeros((energy.size, 16)),
        global_exposure=np.ones((energy.size, 16)),
        fit_valid=np.ones_like(affected, dtype=bool),
        pair_observed=np.ones_like(affected, dtype=bool),
        observed_log_ratio=np.zeros_like(affected),
    )
    stream = io.BytesIO()
    np.savez(stream, **maps)
    return stream.getvalue()


def _record(sample_id: str, connected: bool = True) -> str:
    return json.dumps(
        dict(
            time=f"{sample_id}Z",
            b_sc_nT=5.0,
            magnetic_direction_max_deviation_deg=5.0,
            field_radial_abs_cosine_min=0.9,
            field_connection_status="model_connected" if connected else "unconnected",
            affected_side="low",
            reason="no_records",
        )
    )


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "catalog.sqlite"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE windows (sample_id TEXT PRIMARY KEY, day TEXT, record TEXT, maps BLOB)"
    )
    db.execute("CREATE TABLE days (day TEXT PRIMARY KEY, status TEXT, record TEXT)")
    rng = np.random.default_rng(5)
    ratio = _ratio()
    for label, windows in (("2008-01-01", 3), ("2008-01-02", 2)):
        db.execute("INSERT INTO days VALUES (?, 'complete', '{}')", (label,))
        for k in range(windows):
            sid = f"{label.replace('-', '')}-00{k}000"
            blob = None if k == 0 else _blob(rng, ratio)
            db.execute(
                "INSERT INTO windows VALUES (?, ?, ?, ?)", (sid, label, _record(sid, k != 2), blob)
            )
    db.execute("INSERT INTO days VALUES ('2008-01-03', 'source_unavailable', '{}')")
    db.commit()
    db.close()
    return path


def _prepared(tmp_path, catalog, *, groups=1):
    store = Store(tmp_path / "store")
    er_batch.export_catalog(catalog, store, "test-input", log=lambda _: None)
    config = er_batch.RunConfig("test-input", "test-run", fit_settings=FAST, profile_points=5)
    root = er_batch.prepare_run(store, config, groups=groups)
    return store, root


def test_export_is_lossless_and_registered(tmp_path, catalog):
    store = Store(tmp_path / "store")
    root = er_batch.export_catalog(catalog, store, "test-input", log=lambda _: None)
    assert er_batch.verify_inputs(store, "test-input")
    days = {e["day"]: e for e in json.loads((root / "days.json").read_text())}
    assert days["2008-01-03"]["windows"] == 0 and days["2008-01-03"]["path"] is None
    assert days["2008-01-01"]["distributions"] == 2
    frame = pl.read_parquet(root / "shards/day=2008-01-01.parquet")
    db = sqlite3.connect(catalog)
    sid, record, blob = db.execute(
        "SELECT sample_id, record, maps FROM windows WHERE maps IS NOT NULL LIMIT 1"
    ).fetchone()
    row = frame.filter(pl.col("sample_id") == sid).row(0, named=True)
    with np.load(io.BytesIO(blob)) as data:
        np.testing.assert_array_equal(
            np.reshape(row["reference_counts"], (8, 8)), data["reference_counts"]
        )
        assert "observed_log_ratio" not in row
    assert row["record_json"] == record
    manifest = store.dataset(
        er_batch.INPUT_DATASET, layer="features", variant_id="test-input"
    ).manifest()
    assert manifest["parameters"]["dropped_arrays"] == list(er_batch.DROPPED_ARRAYS)


def test_run_finalize_and_scan(tmp_path, catalog):
    store, root = _prepared(tmp_path, catalog)
    outcome = er_batch.run_days(store, "test-run", workers=0, log=lambda _: None)
    assert outcome == {"completed": 3, "stopped": 0}
    data = er_batch.scan_run(store, "test-run")
    assert data.height == 5
    counts = dict(data.group_by("status").len().iter_rows())
    assert counts == {"no_saved_distribution": 2, "fitted": 3}
    fitted = data.filter(pl.col("status") == "fitted")
    assert fitted["beff_nT"].is_not_null().all()
    # The unconnected window skips the profile and cannot be a candidate.
    unconnected = fitted.filter(pl.col("connection") != "model_connected")
    assert unconnected["profile_status"].to_list() == ["skipped_geometry"]
    assert not unconnected["candidate"].any()
    er_batch.finalize_run(store, "test-run")
    record = store.dataset(er_batch.FIT_DATASET, layer="models", variant_id="test-run")
    assert record.verify_checksums()
    assert (
        store.scan_dataset(er_batch.FIT_DATASET, layer="models", variant_id="test-run")
        .collect()
        .height
        == 5
    )
    status = er_batch.run_status(store, "test-run")
    assert status["completed_days"] == 3 and status["distributions_in_completed_days"] == 3
    assert er_batch.compare_runs(data, data)["candidate_agree"] == 3


def test_resume_keeps_saved_parts_and_stop_halts(tmp_path, catalog):
    store, root = _prepared(tmp_path, catalog)
    (root / "STOP").touch()
    assert er_batch.run_days(store, "test-run", workers=0, log=lambda _: None) == {
        "completed": 0,
        "stopped": 1,
    }
    (root / "STOP").unlink()
    # A saved part from an interrupted invocation is reused verbatim.
    source = pl.read_parquet(
        er_batch.input_root(store, "test-input") / "shards/day=2008-01-01.parquet"
    ).row(0, named=True)
    er_batch._init_worker(json.loads((root / "run.json").read_text()), False)
    row = er_batch.fit_payload(source)
    row["reason"] = "preseeded"
    er_batch.write_parquet(er_batch.fit_frame([row]), root / "work/2008-01-01/part-0000.parquet")
    er_batch.run_days(
        store, "test-run", days=["2008-01-01"], workers=0, chunk=1, log=lambda _: None
    )
    day = pl.read_parquet(root / "shards/day=2008-01-01.parquet")
    assert day.height == 3
    assert day.filter(pl.col("sample_id") == source["sample_id"])["reason"].item() == "preseeded"
    assert not (root / "work/2008-01-01").exists()


def test_changed_code_identity_or_settings_are_refused(tmp_path, catalog):
    store, root = _prepared(tmp_path, catalog)
    run = json.loads((root / "run.json").read_text())
    run["identity"]["files"]["experimental/kaguya/er_batch.py"] = "0" * 64
    (root / "run.json").write_text(json.dumps(run))
    with pytest.raises(SystemExit, match="code or environment"):
        er_batch.run_days(store, "test-run", workers=0, log=lambda _: None)
    other = er_batch.RunConfig("test-input", "test-run", fit_settings={"generations": 9})
    with pytest.raises(SystemExit, match="different settings"):
        er_batch.prepare_run(store, other)


def test_balanced_groups_cover_every_day_once():
    days = [(f"d{i:02d}", cost) for i, cost in enumerate([9, 7, 6, 5, 4, 3, 2, 1, 1, 1])]
    groups = er_batch.balanced_groups(days, 3)
    assert sorted(d for g in groups for d in g) == sorted(d for d, _ in days)
    loads = [sum(dict(days)[d] for d in g) for g in groups]
    assert max(loads) - min(loads) <= 2


def test_cli_prepare_and_status(tmp_path, catalog, capsys):
    store_root = tmp_path / "store"
    assert (
        er_batch.main(
            [
                "--data-root",
                str(store_root),
                "export-catalog",
                "--catalog",
                str(catalog),
                "--input-variant",
                "cli-input",
            ]
        )
        == 0
    )
    assert (
        er_batch.main(
            [
                "--data-root",
                str(store_root),
                "prepare",
                "--input-variant",
                "cli-input",
                "--run-variant",
                "cli-run",
                "--groups",
                "2",
                "--fit-setting",
                "generations=4",
                "--fit-setting",
                "seeds=1",
            ]
        )
        == 0
    )
    run = json.loads((er_batch.run_root(Store(store_root), "cli-run") / "run.json").read_text())
    assert run["fit_settings"]["generations"] == 4 and len(run["groups"]) == 2
    assert run["fit_settings"]["loss"] == "beta_binomial"
    capsys.readouterr()
    assert (
        er_batch.main(["--data-root", str(store_root), "status", "--run-variant", "cli-run"]) == 0
    )
    assert json.loads(capsys.readouterr().out)["completed_days"] == 0


def test_settings_roundtrip_through_run_json(tmp_path, catalog):
    store, root = _prepared(tmp_path, catalog)
    run = json.loads((root / "run.json").read_text())
    restored = FiniteBinFitSettings(**run["config"]["fit_settings"])
    assert replace(restored, generations=4) == restored


def test_spawned_workers_match_in_process_fits(tmp_path, catalog):
    store, root = _prepared(tmp_path, catalog)
    er_batch.run_days(store, "test-run", days=["2008-01-01"], workers=1, log=lambda _: None)
    spawned = pl.read_parquet(root / "shards/day=2008-01-01.parquet")
    (root / "days/2008-01-01.json").unlink()
    er_batch.run_days(store, "test-run", days=["2008-01-01"], workers=0, log=lambda _: None)
    local = pl.read_parquet(root / "shards/day=2008-01-01.parquet")
    columns = ["sample_id", "status", "beff_nT", "objective_sum", "candidate"]
    assert spawned.select(columns).equals(local.select(columns))
