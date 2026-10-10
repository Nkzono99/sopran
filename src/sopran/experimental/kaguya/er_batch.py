"""Day-sharded full-period KAGUYA ER fitting for a workstation or a Slurm cluster.

Two Store datasets carry the work:

- ``kaguya.er.paired_distributions`` (layer ``features``): one Parquet shard per UTC
  day with the folded paired counts, exposures and window record of every 16 s
  window, exported from a frozen paired-distribution SQLite catalog.
- ``kaguya.er.finite_bin_fits`` (layer ``models``): one Parquet shard per day of
  finite-bin fits and Rm profiles, keyed by a run variant.

``prepare`` freezes the fit settings, the input catalog and the code/environment
identity in ``run.json``. Each ``run`` invocation processes whole days, spreading the
windows of a day over a process pool; it writes only its own day files, so many
invocations (e.g. a Slurm array) can run at once. Partial days are kept in
``work/<day>/part-*.parquet`` and resumed. Creating ``STOP`` in the run directory stops
all invocations after their current window. ``finalize`` registers the day shards
in the Store catalog from one process.

Run ``python -m sopran.experimental.kaguya.er_batch --help`` for the commands.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import multiprocessing
import os
import shutil
import sqlite3
import sys
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from sopran.core.schema import InstrumentSchema, VariableSchema
from sopran.core.store import Store
from sopran.core.time import TimeRange, day

INPUT_DATASET = "kaguya.er.paired_distributions"
INPUT_LAYER = "features"
FIT_DATASET = "kaguya.er.finite_bin_fits"
FIT_LAYER = "models"
INPUT_FORMAT = "er_paired_distribution_day_v1"
FIT_FORMAT = "er_finite_bin_fit_day_v1"
PROFILE_THRESHOLD = 3.841458820694124
NO_PROFILE_FLAGS = frozenset({"no_contrast", "barrier_unobserved"})
THREAD_VARIABLES = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")

# Arrays kept from the catalog's per-window npz blob; flattened row-major.
FLOAT_ARRAYS = (
    "energy_eV",
    "energy_edges_eV",
    "pitch_edges_deg",
    "affected_counts",
    "reference_counts",
    "affected_exposure",
    "reference_exposure",
    "global_counts",
    "global_exposure",
)
BOOL_ARRAYS = ("fit_valid", "pair_observed")
# Products of earlier fits in the catalog blobs; not ER inputs.
DROPPED_ARRAYS = ("observed_log_ratio", "fitted_log_ratio", "beam_ratio")

INPUT_SCHEMA: dict[str, Any] = {
    "sample_id": pl.String,
    "day": pl.String,
    "time": pl.String,
    "has_distribution": pl.Boolean,
    "record_json": pl.String,
    "source_sha256": pl.String,
    "b_sc_nT": pl.Float64,
    "n_energy": pl.Int64,
    "n_pitch_folded": pl.Int64,
    "n_pitch_full": pl.Int64,
    **{name: pl.List(pl.Float64) for name in FLOAT_ARRAYS},
    **{name: pl.List(pl.Boolean) for name in BOOL_ARRAYS},
}

# (name, polars dtype, units, description) of each fit row.
FIT_COLUMNS: tuple[tuple[str, Any, str | None, str], ...] = (
    ("sample_id", pl.String, None, "16 s window id"),
    ("day", pl.String, None, "UTC day"),
    ("time", pl.String, None, "window centre time"),
    ("status", pl.String, None, "fitted/insufficient_support/no_saved_distribution/fit_error"),
    ("reason", pl.String, None, "why a window was not fitted"),
    ("source_sha256", pl.String, None, "sha256 of the source record and distribution"),
    ("b_sc_nT", pl.Float64, "nT", "spacecraft field magnitude"),
    ("mag_deviation_deg", pl.Float64, "deg", "maximum field-direction deviation in the window"),
    ("radial_angle_deg", pl.Float64, "deg", "angle between field and radial direction"),
    ("connection", pl.String, None, "field-line connection status"),
    ("affected_side", pl.String, None, "outgoing pitch hemisphere"),
    ("total_counts", pl.Float64, "count", "affected + reference counts in fitted cells"),
    ("cells", pl.Int64, None, "fitted cells"),
    ("energy_rows", pl.Int64, None, "energy rows with >= 3 fitted cells"),
    ("zero_affected_cells", pl.Int64, None, "fitted cells with zero affected counts"),
    ("beff_nT", pl.Float64, "nT", "effective barrier field Rm * Bsc"),
    ("rm", pl.Float64, None, "mirror ratio"),
    ("rho", pl.Float64, None, "inside-to-outside reflectance"),
    ("delta_u_eV", pl.Float64, "eV", "surface minus spacecraft potential energy"),
    ("scale", pl.Float64, None, "outside level"),
    ("concentration", pl.Float64, None, "beta-binomial concentration"),
    ("beam_template", pl.Int64, None, "0 none, 1-4 beam shape"),
    ("beam_amplitude", pl.Float64, None, "continuous beam amplitude"),
    ("objective_sum", pl.Float64, None, "deviance (count losses)"),
    ("objective_mean", pl.Float64, None, "deviance per fitted cell"),
    ("rmse_dex", pl.Float64, "dex", "RMSE of log10 affected/reference"),
    ("local_converged", pl.Boolean, None, "Nelder-Mead termination"),
    ("evaluations", pl.Int64, None, "objective evaluations of the fit"),
    ("boundary_rows", pl.Int64, None, "rows with cells on both sides of the boundary"),
    ("loss_cone_delta_objective", pl.Float64, None, "row-level fit without minus with loss cone"),
    ("loss_cone_delta_bic", pl.Float64, None, "loss_cone_delta_objective - k ln N"),
    ("field_flags", pl.String, None, "';'-joined field flags"),
    ("at_bounds", pl.String, None, "';'-joined parameters at search bounds"),
    ("field_unconstrained", pl.Boolean, None, "any field flag set"),
    ("initial_beff_nT", pl.Float64, "nT", "fit solution before the profile"),
    ("initial_objective_sum", pl.Float64, None, "fit objective before the profile"),
    ("profile_status", pl.String, None, "complete/skipped_*/not_run"),
    ("profile_low_nT", pl.Float64, "nT", "95% profile interval lower end"),
    ("profile_high_nT", pl.Float64, "nT", "95% profile interval upper end"),
    ("profile_bounded", pl.Boolean, None, "interval closed inside the grid"),
    ("profile_improved", pl.Boolean, None, "profile found a lower objective than the fit"),
    ("profile_beff_grid_nT", pl.List(pl.Float64), "nT", "profile grid"),
    ("profile_delta_objective", pl.List(pl.Float64), None, "profile objective minus minimum"),
    ("geometry_ok", pl.Boolean, None, "Bsc>0, deviation<=20 deg, radial<80 deg, connected"),
    ("candidate", pl.Boolean, None, "geometry_ok, no field flag and bounded profile"),
    ("candidate_rm_gt1", pl.Boolean, None, "candidate with Rm > 1"),
    ("fit_seconds", pl.Float64, "s", "fit wall time"),
    ("profile_seconds", pl.Float64, "s", "profile wall time"),
)
FIT_SCHEMA: dict[str, Any] = {name: dtype for name, dtype, _, _ in FIT_COLUMNS}


@dataclass(frozen=True)
class RunConfig:
    """Frozen settings of one fit run; ``fit_settings`` overrides FiniteBinFitSettings."""

    input_variant: str
    run_variant: str
    fit_settings: dict[str, Any] = field(default_factory=dict)
    selection: str = "total"
    min_counts: float = 1.0
    round_counts: bool = True
    min_cells: int = 12
    min_energy_rows: int = 4
    profile_points: int = 13
    profile_half_width_dex: float = 1.0


# ----------------------------------------------------------------------------
# Small helpers


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def shard_checksum(path: Path) -> str:
    """Checksum in the Store catalog format."""
    return f"sha256:{sha256_file(path)}"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_parquet(frame: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    frame.write_parquet(tmp, compression="zstd")
    os.replace(tmp, path)


def available_cpus() -> int:
    """CPUs this process may use (the Slurm/cgroup allocation on Linux)."""
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def lower_priority() -> None:
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
        kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x00004000)
    else:
        os.nice(10)


def input_root(store: Store, input_variant: str) -> Path:
    return store.dataset_path(INPUT_DATASET, layer=INPUT_LAYER, variant_id=input_variant)


def run_root(store: Store, run_variant: str) -> Path:
    return store.dataset_path(FIT_DATASET, layer=FIT_LAYER, variant_id=run_variant)


def day_range(days: Sequence[str]) -> TimeRange:
    ordered = sorted(days)
    return TimeRange(day(ordered[0]).start, day(ordered[-1]).start + timedelta(days=1))


# ----------------------------------------------------------------------------
# Input export: SQLite catalog -> day-sharded Store dataset


def _connect(catalog: Path) -> sqlite3.Connection:
    # A frozen catalog; immutable read-only avoids locks and WAL checks.
    return sqlite3.connect(f"file:{catalog.as_posix()}?mode=ro&immutable=1", uri=True)


def input_row(sample_id: str, day_label: str, record_text: str, blob: bytes | None) -> dict:
    """One input row; raises if an array cannot be represented without loss."""
    record = json.loads(record_text)
    row: dict[str, Any] = dict.fromkeys(INPUT_SCHEMA)
    row.update(
        sample_id=sample_id,
        day=day_label,
        time=record.get("time"),
        has_distribution=blob is not None,
        record_json=record_text,
        source_sha256=hashlib.sha256(record_text.encode() + (blob or b"")).hexdigest(),
        b_sc_nT=record.get("b_sc_nT"),
    )
    if blob is None:
        return row
    with np.load(io.BytesIO(blob), allow_pickle=False) as data:
        maps = {name: data[name] for name in data.files}
    folded = maps["affected_counts"].shape
    row.update(
        n_energy=int(folded[0]),
        n_pitch_folded=int(folded[1]),
        n_pitch_full=int(maps["global_counts"].shape[1]) if "global_counts" in maps else None,
    )
    for name in (*FLOAT_ARRAYS, *BOOL_ARRAYS):
        if name not in maps:
            continue
        original = maps[name]
        kind = bool if name in BOOL_ARRAYS else float
        converted = np.asarray(original, dtype=kind)
        if not np.array_equal(converted, original, equal_nan=kind is float):
            raise ValueError(f"{sample_id}: {name} is not representable as {kind.__name__}")
        row[name] = converted.ravel().tolist()
    return row


def export_day(catalog: Path, root: Path, day_label: str) -> dict:
    db = _connect(catalog)
    try:
        query = "SELECT sample_id, record, maps FROM windows WHERE day = ? ORDER BY sample_id"
        rows = [
            input_row(sid, day_label, rec, blob)
            for sid, rec, blob in db.execute(query, (day_label,))
        ]
    finally:
        db.close()
    frame = pl.DataFrame(rows, schema=INPUT_SCHEMA, orient="row")
    relative = f"shards/day={day_label}.parquet"
    write_parquet(frame, root / relative)
    return dict(
        day=day_label,
        path=relative,
        windows=frame.height,
        distributions=int(frame["has_distribution"].sum()),
        checksum=shard_checksum(root / relative),
    )


def _export_task(task: tuple[str, str, str]) -> dict:
    catalog, root, day_label = task
    return export_day(Path(catalog), Path(root), day_label)


def _input_instrument_schema() -> InstrumentSchema:
    variables = [
        VariableSchema("record_json", ("window",), description="source window record (JSON)"),
        VariableSchema("b_sc_nT", ("window",), units="nT"),
        VariableSchema("energy_eV", ("window", "energy"), units="eV"),
        VariableSchema("energy_edges_eV", ("window", "energy_edge"), units="eV"),
        VariableSchema("pitch_edges_deg", ("window", "pitch_edge"), units="deg"),
    ]
    for name in ("affected_counts", "reference_counts"):
        variables.append(VariableSchema(name, ("window", "energy", "pitch_folded"), units="count"))
    for name in ("affected_exposure", "reference_exposure"):
        variables.append(VariableSchema(name, ("window", "energy", "pitch_folded")))
    variables += [
        VariableSchema("global_counts", ("window", "energy", "pitch"), units="count"),
        VariableSchema("global_exposure", ("window", "energy", "pitch")),
        VariableSchema("fit_valid", ("window", "energy", "pitch_folded")),
        VariableSchema("pair_observed", ("window", "energy", "pitch_folded")),
    ]
    return InstrumentSchema(mission="kaguya", instrument="esa", variables=tuple(variables))


def export_catalog(
    catalog: Path,
    store: Store,
    input_variant: str,
    *,
    days: Sequence[str] | None = None,
    workers: int = 1,
    log: Any = print,
) -> Path:
    """Export a paired-distribution SQLite catalog to day shards; existing days are kept."""
    root = input_root(store, input_variant)
    (root / "shards").mkdir(parents=True, exist_ok=True)
    db = _connect(catalog)
    try:
        statuses = dict(db.execute("SELECT day, status FROM days").fetchall())
        counts = {
            d: (int(n), int(m))
            for d, n, m in db.execute("SELECT day, count(*), count(maps) FROM windows GROUP BY day")
        }
    finally:
        db.close()
    selected = sorted(days) if days else sorted(statuses)
    todo = [
        d
        for d in selected
        if counts.get(d, (0, 0))[0] and not (root / f"shards/day={d}.parquet").exists()
    ]
    log(f"{now()} export days={len(selected)} todo={len(todo)} workers={workers}")
    tasks = [(str(catalog), str(root), d) for d in todo]
    if workers <= 1:
        for task in tasks:
            log(f"{now()} exported {_export_task(task)['day']}")
    else:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
            for result in pool.map(_export_task, tasks):
                log(f"{now()} exported {result['day']} windows={result['windows']}")
    index: list[dict[str, Any]] = []
    for d in selected:
        windows, distributions = counts.get(d, (0, 0))
        path = root / f"shards/day={d}.parquet"
        entry = dict(
            day=d,
            source_status=statuses.get(d),
            windows=windows,
            distributions=distributions,
            path=f"shards/day={d}.parquet" if windows else None,
            checksum=shard_checksum(path) if windows else None,
        )
        index.append(entry)
    write_json(root / "days.json", index)
    stat = catalog.stat()
    shards = tuple(
        dict(
            path=e["path"],
            start=day(e["day"]).start_iso,
            stop=day(e["day"]).stop_iso,
            row_count=e["windows"],
            checksum=e["checksum"],
            status="complete",
        )
        for e in index
        if e["path"]
    )
    store.register_dataset(
        dataset_id=INPUT_DATASET,
        layer=INPUT_LAYER,
        variant_id=input_variant,
        mission="kaguya",
        instrument="esa",
        product="paired_distributions",
        schema=_input_instrument_schema(),
        time_coverage=day_range([e["day"] for e in index]),
        shards=shards,
        producer="sopran.experimental.kaguya.er_batch.export_catalog",
        provenance=dict(
            catalog=dict(path=str(catalog), bytes=stat.st_size, mtime_ns=stat.st_mtime_ns),
            days_sha256=sha256_file(root / "days.json"),
        ),
        parameters=dict(
            format=INPUT_FORMAT,
            float_arrays=list(FLOAT_ARRAYS),
            bool_arrays=list(BOOL_ARRAYS),
            dropped_arrays=list(DROPPED_ARRAYS),
            layout="row-major flattened (n_energy, n_pitch_folded|n_pitch_full)",
        ),
    )
    log(f"{now()} registered {INPUT_DATASET} variant={input_variant} shards={len(shards)}")
    return root


def verify_inputs(store: Store, input_variant: str) -> bool:
    record = store.dataset(INPUT_DATASET, layer=INPUT_LAYER, variant_id=input_variant)
    return record.verify_checksums()


# ----------------------------------------------------------------------------
# Run preparation and identity


def code_identity() -> dict:
    """Hashes of the fit code and native extension plus the numerical stack versions."""
    import scipy  # type: ignore[import-untyped,unused-ignore]

    import sopran

    package = Path(sopran.__file__).resolve().parent
    files = [
        package / "experimental/electron_reflection/finite_bin.py",
        package / "experimental/electron_reflection/common.py",
        package / "experimental/kaguya/er_batch.py",
        *sorted(package.glob("_native*")),
    ]
    files = [f for f in files if f.suffix in {".py", ".pyd", ".so"}]
    try:
        sopran_version = version("sopran")
    except PackageNotFoundError:
        sopran_version = "unknown"
    return dict(
        sopran=sopran_version,
        files={f.relative_to(package).as_posix(): sha256_file(f) for f in files},
        python=sys.version.split()[0],
        platform=sys.platform,
        packages=dict(numpy=np.__version__, scipy=scipy.__version__, polars=pl.__version__),
    )


def balanced_groups(days: Sequence[tuple[str, int]], groups: int) -> list[list[str]]:
    """Longest-first assignment of (day, cost) to the currently lightest group."""
    loads = [0] * groups
    members: list[list[str]] = [[] for _ in range(groups)]
    for label, cost in sorted(days, key=lambda item: (-item[1], item[0])):
        index = min(range(groups), key=lambda i: (loads[i], i))
        loads[index] += cost
        members[index].append(label)
    return [sorted(group) for group in members]


def prepare_run(
    store: Store,
    config: RunConfig,
    *,
    groups: int = 1,
    days: Sequence[str] | None = None,
) -> Path:
    """Write ``run.json``; an identical existing run is accepted, a different one refused."""
    from sopran.experimental.electron_reflection import FiniteBinFitSettings

    settings = asdict(FiniteBinFitSettings(**config.fit_settings))
    inputs = store.dataset(INPUT_DATASET, layer=INPUT_LAYER, variant_id=config.input_variant)
    index = read_json(inputs.root / "days.json")
    if days:
        wanted = set(days)
        index = [e for e in index if e["day"] in wanted]
    plan = [
        dict(day=e["day"], distributions=e["distributions"], windows=e["windows"]) for e in index
    ]
    cost = [(e["day"], max(e["distributions"], 1)) for e in plan]
    run = dict(
        format=FIT_FORMAT,
        config=asdict(config),
        fit_settings=settings,
        profile_threshold=PROFILE_THRESHOLD,
        input=dict(
            dataset=INPUT_DATASET,
            variant=config.input_variant,
            catalog_sha256=sha256_file(inputs.catalog_path),
        ),
        identity=code_identity(),
        plan=plan,
        groups=balanced_groups(cost, max(1, min(groups, len(cost)))),
    )
    root = run_root(store, config.run_variant)
    path = root / "run.json"
    if path.exists():
        previous = read_json(path)
        if json.dumps(previous, sort_keys=True) != json.dumps(run, sort_keys=True, default=str):
            raise SystemExit(f"{path} exists with different settings; choose a new run variant")
        return root
    write_json(path, run)
    return root


def load_run(store: Store, run_variant: str) -> tuple[Path, dict]:
    root = run_root(store, run_variant)
    path = root / "run.json"
    if not path.exists():
        raise SystemExit(f"no prepared run at {path}; run 'prepare' first")
    return root, read_json(path)


# ----------------------------------------------------------------------------
# Per-window fit (runs in worker processes)

_WORKER: dict[str, Any] = {}


def _init_worker(run: dict, low: bool) -> None:
    from sopran.experimental.electron_reflection import FiniteBinFitSettings

    if low:
        lower_priority()
    _WORKER["run"] = run
    _WORKER["settings"] = FiniteBinFitSettings(**run["config"]["fit_settings"])


def _record_row(payload: dict) -> dict:
    record = json.loads(payload["record_json"])
    cosine = record.get("field_radial_abs_cosine_min")
    bsc = record.get("b_sc_nT")
    mag = record.get("magnetic_direction_max_deviation_deg")
    radial = float(np.degrees(np.arccos(cosine))) if cosine is not None else None
    connection = record.get("field_connection_status")
    row: dict[str, Any] = dict.fromkeys(FIT_SCHEMA)
    row.update(
        sample_id=payload["sample_id"],
        day=payload["day"],
        time=payload["time"],
        source_sha256=payload["source_sha256"],
        b_sc_nT=bsc,
        mag_deviation_deg=mag,
        radial_angle_deg=radial,
        connection=connection,
        affected_side=record.get("affected_side"),
        geometry_ok=bool(
            bsc is not None
            and bsc > 0
            and mag is not None
            and mag <= 20
            and radial is not None
            and radial < 80
            and connection == "model_connected"
        ),
        candidate=False,
        candidate_rm_gt1=False,
        profile_status="not_run",
    )
    if not payload["has_distribution"]:
        row.update(status="no_saved_distribution", reason=record.get("reason"))
    return row


def fit_payload(payload: dict) -> dict:
    """Fit one window; failures become ``fit_error`` rows instead of exceptions."""
    try:
        return _fit_payload(payload)
    except Exception as exc:  # keep the day running; record the failure per window
        row = _record_row(payload)
        row.update(status="fit_error", reason=f"{type(exc).__name__}: {exc}"[:500])
        return row


def _fit_payload(payload: dict) -> dict:
    from sopran.experimental.electron_reflection import (
        ElectronReflectionCounts,
        FiniteBinObservation,
        fit_finite_bin_distribution,
        profile_mirror_ratio,
    )

    run = _WORKER["run"]
    config = run["config"]
    row = _record_row(payload)
    if not payload["has_distribution"]:
        return row
    shape = (payload["n_energy"], payload["n_pitch_folded"])

    def array(name: str, dtype: Any = float) -> np.ndarray:
        return np.asarray(payload[name], dtype=dtype).reshape(shape)

    fit_valid = array("fit_valid", bool)
    affected, reference = array("affected_counts"), array("reference_counts")
    if config["round_counts"]:
        # Catalog counts were redistributed across bins; round to count-equivalents.
        affected, reference = np.rint(affected), np.rint(reference)
    affected = np.where(fit_valid, affected, np.nan)
    reference = np.where(fit_valid, reference, np.nan)
    xa = np.where(fit_valid, array("affected_exposure"), 1.0)
    xr = np.where(fit_valid, array("reference_exposure"), 1.0)
    xa = np.where(np.isfinite(xa) & (xa > 0), xa, 1.0)
    xr = np.where(np.isfinite(xr) & (xr > 0), xr, 1.0)
    pitch_edges = np.asarray(payload["pitch_edges_deg"], dtype=float)[: shape[1] + 1]
    pitch = (pitch_edges[:-1] + pitch_edges[1:]) / 2
    bsc = row["b_sc_nT"]
    if bsc is None or not np.isfinite(bsc) or bsc <= 0:
        row.update(status="insufficient_support", reason="spacecraft_field")
        return row
    energy = np.asarray(payload["energy_eV"], dtype=float)
    counts = ElectronReflectionCounts(energy, pitch, affected, reference, bsc, xa, xr)
    try:
        observation = FiniteBinObservation.from_counts(
            counts,
            energy_edges_eV=np.asarray(payload["energy_edges_eV"], dtype=float),
            pitch_edges_deg=pitch_edges,
            selection=config["selection"],
            min_counts=config["min_counts"],
        )
        valid = np.asarray(observation.fit_valid)
    except ValueError:
        valid = np.zeros(shape, dtype=bool)
    cells, rows = int(valid.sum()), int((valid.sum(axis=1) >= 3).sum())
    row.update(cells=cells, energy_rows=rows)
    if cells < config["min_cells"] or rows < config["min_energy_rows"]:
        row.update(status="insufficient_support", reason="cells_or_energy_rows")
        return row
    a = np.asarray(observation.affected_counts)[valid]
    r = np.asarray(observation.reference_counts)[valid]
    row.update(total_counts=float(a.sum() + r.sum()), zero_affected_cells=int((a == 0).sum()))
    started = time.perf_counter()
    fit = fit_finite_bin_distribution(observation, settings=_WORKER["settings"])
    row["fit_seconds"] = time.perf_counter() - started
    row.update(initial_beff_nT=fit.effective_field_nT, initial_objective_sum=fit.objective_sum)
    best = fit
    if set(fit.field_flags) & NO_PROFILE_FLAGS:
        row["profile_status"] = "skipped_no_boundary"
    elif not row["geometry_ok"]:
        row["profile_status"] = "skipped_geometry"
    elif fit.field_unconstrained:
        row["profile_status"] = "skipped_field_flags"
    else:
        started = time.perf_counter()
        profile = profile_mirror_ratio(
            observation,
            fit,
            points=config["profile_points"],
            half_width_dex=config["profile_half_width_dex"],
            threshold=PROFILE_THRESHOLD,
        )
        row["profile_seconds"] = time.perf_counter() - started
        best = profile.minimum_fit
        low, high = profile.interval_nT if profile.interval_nT else (None, None)
        row.update(
            profile_status="complete",
            profile_low_nT=low,
            profile_high_nT=high,
            profile_bounded=profile.interval_bounded,
            profile_improved=profile.improved_minimum,
            profile_beff_grid_nT=profile.effective_field_nT.tolist(),
            profile_delta_objective=profile.delta_objective.tolist(),
        )
    p = best.parameters
    flags = tuple(best.field_flags)
    row.update(
        status="fitted",
        beff_nT=best.effective_field_nT,
        rm=p.mirror_ratio,
        rho=p.bottom_ratio,
        delta_u_eV=p.delta_u_eV,
        scale=p.scale,
        concentration=p.concentration,
        beam_template=best.beam_template,
        beam_amplitude=best.beam_amplitude,
        objective_sum=best.objective_sum,
        objective_mean=best.objective_mean,
        rmse_dex=best.root_mean_square_error_dex,
        local_converged=best.local_converged,
        evaluations=fit.evaluations,
        boundary_rows=best.boundary_rows,
        loss_cone_delta_objective=best.loss_cone_delta_objective,
        loss_cone_delta_bic=best.loss_cone_delta_bic,
        field_flags=";".join(flags),
        at_bounds=";".join(best.at_bounds),
        field_unconstrained=best.field_unconstrained,
    )
    candidate = bool(row["geometry_ok"] and not flags and row["profile_bounded"])
    row.update(candidate=candidate, candidate_rm_gt1=candidate and p.mirror_ratio > 1)
    return row


# ----------------------------------------------------------------------------
# Day tasks


def fit_frame(rows: list[dict]) -> pl.DataFrame:
    return (
        pl.DataFrame(rows, schema=FIT_SCHEMA, orient="row")
        if rows
        else pl.DataFrame(schema=FIT_SCHEMA)
    )


def _payloads(path: Path) -> Iterator[dict]:
    yield from pl.read_parquet(path).iter_rows(named=True)


class Stopped(Exception):
    """Raised when the run directory contains STOP."""


def run_day(
    root: Path,
    run: dict,
    entry: dict,
    inputs: Path,
    *,
    pool: ProcessPoolExecutor | None,
    chunk: int,
    heartbeat: int,
    log: Any,
) -> dict:
    """Fit one day; resumes saved parts and writes the day shard and sidecar."""
    label = entry["day"]
    sidecar = root / "days" / f"{label}.json"
    shard = f"shards/day={label}.parquet"
    work = root / "work" / label
    work.mkdir(parents=True, exist_ok=True)
    done: set[str] = set()
    for part in sorted(work.glob("part-*.parquet")):
        done.update(pl.read_parquet(part, columns=["sample_id"])["sample_id"].to_list())
    source = inputs / f"shards/day={label}.parquet"
    payloads = (
        [p for p in _payloads(source) if p["sample_id"] not in done] if entry["windows"] else []
    )
    total = entry["windows"]
    log(f"{now()} start day={label} windows={total} resumed={len(done)} pid={os.getpid()}")
    started = time.perf_counter()
    results = (
        map(fit_payload, payloads) if pool is None else pool.map(fit_payload, payloads, chunksize=2)
    )
    buffer: list[dict] = []
    processed = len(done)
    part_index = len(list(work.glob("part-*.parquet")))

    def flush() -> None:
        nonlocal buffer, part_index
        if buffer:
            write_parquet(fit_frame(buffer), work / f"part-{part_index:04d}.parquet")
            part_index += 1
            buffer = []

    for row in results:
        buffer.append(row)
        processed += 1
        if processed % heartbeat == 0:
            log(
                f"{now()} heartbeat day={label} processed={processed}/{total} "
                f"elapsed={time.perf_counter() - started:.0f}s"
            )
        if len(buffer) >= chunk:
            flush()
        if (root / "STOP").exists():
            flush()
            log(f"{now()} stopped day={label} processed={processed}/{total}")
            raise Stopped(label)
    flush()
    parts = sorted(work.glob("part-*.parquet"))
    data = pl.concat([pl.read_parquet(p) for p in parts]) if parts else fit_frame([])
    data = data.sort("sample_id")
    if data.height != total or data["sample_id"].n_unique() != total:
        raise RuntimeError(
            f"{label}: {data.height} rows ({data['sample_id'].n_unique()} unique), {total} expected"
        )
    summary: dict[str, Any] = dict(day=label, status="complete", windows=total, completed_utc=now())
    if total:
        write_parquet(data, root / shard)
        summary.update(
            path=shard,
            checksum=shard_checksum(root / shard),
            counts=dict(data.group_by("status").len().iter_rows()),
            candidates=int(data["candidate"].sum()),
        )
    summary.update(
        elapsed_seconds=time.perf_counter() - started, identity_sha256=_identity_hash(run)
    )
    write_json(sidecar, summary)
    shutil.rmtree(work)
    log(
        f"{now()} done day={label} {json.dumps(summary.get('counts', {}))} "
        f"elapsed={summary['elapsed_seconds']:.0f}s"
    )
    return summary


def _identity_hash(run: dict) -> str:
    return hashlib.sha256(json.dumps(run["identity"], sort_keys=True).encode()).hexdigest()


def select_days(run: dict, *, days: Sequence[str] | None, group: int | None) -> list[dict]:
    plan = {e["day"]: e for e in run["plan"]}
    if days:
        missing = sorted(set(days) - set(plan))
        if missing:
            raise SystemExit(f"days not in the run plan: {missing[:5]}")
        labels = list(days)
    elif group is not None:
        if not 0 <= group < len(run["groups"]):
            raise SystemExit(f"group {group} outside 0..{len(run['groups']) - 1}")
        labels = run["groups"][group]
    else:
        labels = sorted(plan)
    # Heavy days first shortens the tail when several invocations share the plan.
    return sorted((plan[d] for d in labels), key=lambda e: (-e["distributions"], e["day"]))


def run_days(
    store: Store,
    run_variant: str,
    *,
    days: Sequence[str] | None = None,
    group: int | None = None,
    workers: int | None = None,
    chunk: int = 256,
    heartbeat: int = 100,
    low: bool = False,
    log: Any = print,
) -> dict:
    """Process the selected days of a prepared run; returns counts by outcome."""
    root, run = load_run(store, run_variant)
    identity = code_identity()
    if identity != run["identity"]:
        raise SystemExit(
            "code or environment differs from run.json; prepare a new run variant\n"
            f"run: {json.dumps(run['identity'], sort_keys=True)}\n"
            f"now: {json.dumps(identity, sort_keys=True)}"
        )
    inputs = input_root(store, run["config"]["input_variant"])
    workers = available_cpus() if workers is None else workers
    entries = [
        e
        for e in select_days(run, days=days, group=group)
        if not _day_complete(root / "days" / f"{e['day']}.json", run)
    ]
    log(f"{now()} run={run_variant} days={len(entries)} workers={workers} pid={os.getpid()}")
    outcome = dict(completed=0, stopped=0)
    for name in THREAD_VARIABLES:
        os.environ[name] = "1"  # inherited by spawned workers before they import numpy
    pool = None
    if workers > 0:
        context = multiprocessing.get_context("spawn")
        pool = ProcessPoolExecutor(
            max_workers=workers, mp_context=context, initializer=_init_worker, initargs=(run, low)
        )
    else:
        _init_worker(run, low)
    try:
        for entry in entries:
            if (root / "STOP").exists():
                outcome["stopped"] += 1
                break
            try:
                run_day(
                    root, run, entry, inputs, pool=pool, chunk=chunk, heartbeat=heartbeat, log=log
                )
                outcome["completed"] += 1
            except Stopped:
                outcome["stopped"] += 1
                break
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
    log(f"{now()} finished run={run_variant} {json.dumps(outcome)}")
    return outcome


def _day_complete(sidecar: Path, run: dict) -> bool:
    if not sidecar.exists():
        return False
    summary = read_json(sidecar)
    return bool(
        summary.get("status") == "complete"
        and summary.get("identity_sha256") == _identity_hash(run)
    )


# ----------------------------------------------------------------------------
# Status, registration and comparison


def run_status(store: Store, run_variant: str) -> dict:
    root, run = load_run(store, run_variant)
    complete = {
        e["day"] for e in run["plan"] if _day_complete(root / "days" / f"{e['day']}.json", run)
    }
    total = sum(e["distributions"] for e in run["plan"])
    done = sum(e["distributions"] for e in run["plan"] if e["day"] in complete)
    running = {}
    for log_path in (root / "logs").glob("*.log"):
        for line in log_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1] == "heartbeat":
                label = parts[2].split("=", 1)[1]
                if label not in complete:
                    processed, windows = parts[3].split("=", 1)[1].split("/")
                    running[label] = dict(
                        processed=int(processed), windows=int(windows), at=parts[0]
                    )
    return dict(
        run_variant=run_variant,
        days=len(run["plan"]),
        completed_days=len(complete),
        distributions=total,
        distributions_in_completed_days=done,
        running=running,
        stop_requested=(root / "STOP").exists(),
    )


def finalize_run(store: Store, run_variant: str) -> Path:
    """Register complete day shards (checksums re-verified) in the Store catalog."""
    root, run = load_run(store, run_variant)
    shards = []
    for entry in run["plan"]:
        label = entry["day"]
        sidecar = root / "days" / f"{label}.json"
        base = dict(start=day(label).start_iso, stop=day(label).stop_iso)
        if _day_complete(sidecar, run):
            summary = read_json(sidecar)
            if not summary.get("path"):
                continue
            checksum = shard_checksum(root / summary["path"])
            if checksum != summary["checksum"]:
                raise RuntimeError(f"{label}: shard checksum differs from its sidecar")
            shards.append(
                dict(
                    base,
                    path=summary["path"],
                    row_count=summary["windows"],
                    checksum=checksum,
                    status="complete",
                )
            )
        elif entry["windows"]:
            shards.append(
                dict(
                    base,
                    path=f"shards/day={label}.parquet",
                    row_count=0,
                    checksum="",
                    status="pending",
                )
            )
    variables = tuple(
        VariableSchema(name, ("window",), units=units, description=text)
        for name, _, units, text in FIT_COLUMNS
    )
    store.register_dataset(
        dataset_id=FIT_DATASET,
        layer=FIT_LAYER,
        variant_id=run_variant,
        variant=dict(fit_settings=run["fit_settings"], config=run["config"]),
        mission="kaguya",
        instrument="esa",
        product="finite_bin_fits",
        schema=InstrumentSchema(mission="kaguya", instrument="esa", variables=variables),
        time_coverage=day_range([e["day"] for e in run["plan"]]),
        source_datasets=(f"{INPUT_DATASET}@{run['config']['input_variant']}",),
        shards=tuple(shards),
        producer="sopran.experimental.kaguya.er_batch",
        provenance=dict(
            identity=run["identity"],
            input=run["input"],
            run_json_sha256=sha256_file(root / "run.json"),
        ),
        parameters=dict(format=FIT_FORMAT, profile_threshold=run["profile_threshold"]),
    )
    return root


def compare_runs(frame: pl.DataFrame, reference: pl.DataFrame) -> dict:
    """Agreement of two fit tables on their common fitted windows."""
    joined = frame.join(reference, on="sample_id", suffix="_ref").filter(
        (pl.col("status") == "fitted") & (pl.col("status_ref") == "fitted")
    )
    if joined.is_empty():
        return dict(common_fitted=0)
    objective = (joined["objective_sum"] - joined["objective_sum_ref"]).abs() / joined[
        "objective_sum_ref"
    ].abs().clip(lower_bound=1.0)
    beff = (joined["beff_nT"] / joined["beff_nT_ref"]).log10().abs()
    unflagged = joined.filter(pl.col("field_flags_ref") == "")
    unflagged_beff = (unflagged["beff_nT"] / unflagged["beff_nT_ref"]).log10().abs()
    return dict(
        common_fitted=joined.height,
        objective_rel_diff_max=float(objective.max()),  # type: ignore[arg-type]
        objective_rel_diff_gt_1e6=int((objective > 1e-6).sum()),
        beff_log_diff_gt_0p01=int((beff > 0.01).sum()),
        unflagged=unflagged.height,
        unflagged_beff_log_diff_gt_0p01=int((unflagged_beff > 0.01).sum()),
        candidate_agree=int((joined["candidate"] == joined["candidate_ref"]).sum()),
        flags_agree=int((joined["field_flags"] == joined["field_flags_ref"]).sum()),
    )


def scan_run(store: Store, run_variant: str) -> pl.DataFrame:
    root, run = load_run(store, run_variant)
    paths = [
        root / read_json(root / "days" / f"{e['day']}.json")["path"]
        for e in run["plan"]
        if _day_complete(root / "days" / f"{e['day']}.json", run)
        and read_json(root / "days" / f"{e['day']}.json").get("path")
    ]
    if not paths:
        return fit_frame([])
    return pl.concat([pl.read_parquet(p) for p in paths])


# ----------------------------------------------------------------------------
# Command line


def _store(args: argparse.Namespace) -> Store:
    return Store(args.data_root) if args.data_root else Store()


def _logger(path: Path | None) -> Any:
    stream = None
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = path.open("a", encoding="utf-8")

    def log(message: str) -> None:
        print(message, flush=True)
        if stream is not None:
            print(message, file=stream, flush=True)

    return log


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sopran.experimental.kaguya.er_batch",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data-root", help="Store root (default: SOPRAN_DATA_ROOT or config)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("export-catalog", help="SQLite catalog -> day-sharded input dataset")
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--input-variant", required=True)
    p.add_argument("--days", nargs="*")
    p.add_argument("--workers", type=int, default=1)

    p = sub.add_parser("verify-inputs", help="re-hash input shards against the catalog")
    p.add_argument("--input-variant", required=True)

    p = sub.add_parser("prepare", help="freeze settings, inputs and code identity in run.json")
    p.add_argument("--input-variant", required=True)
    p.add_argument("--run-variant", required=True)
    p.add_argument("--groups", type=int, default=1, help="balanced day groups for array jobs")
    p.add_argument("--days", nargs="*", help="restrict the plan (tests, pilots)")
    p.add_argument(
        "--fit-setting",
        action="append",
        default=[],
        metavar="NAME=JSON",
        help="override a FiniteBinFitSettings field, e.g. generations=80",
    )
    p.add_argument("--profile-points", type=int, default=13)

    p = sub.add_parser("run", help="fit days of a prepared run (resumable)")
    p.add_argument("--run-variant", required=True)
    p.add_argument("--days", nargs="*")
    p.add_argument(
        "--group", type=int, help="index into run.json groups (e.g. SLURM_ARRAY_TASK_ID)"
    )
    p.add_argument(
        "--workers", type=int, help="worker processes (default: allocated CPUs; 0 = in-process)"
    )
    p.add_argument("--chunk", type=int, default=256)
    p.add_argument("--heartbeat", type=int, default=100)
    p.add_argument("--low-priority", action="store_true", help="nice / BelowNormal workers")

    p = sub.add_parser("status", help="completed days and heartbeats")
    p.add_argument("--run-variant", required=True)

    p = sub.add_parser("finalize", help="register complete day shards in the Store catalog")
    p.add_argument("--run-variant", required=True)

    p = sub.add_parser("compare", help="compare a run with a reference fit table (Parquet)")
    p.add_argument("--run-variant", required=True)
    p.add_argument("--reference", type=Path, nargs="+", required=True)

    args = parser.parse_args(argv)
    store = _store(args)
    if args.command == "export-catalog":
        export_catalog(
            args.catalog, store, args.input_variant, days=args.days, workers=args.workers
        )
    elif args.command == "verify-inputs":
        ok = verify_inputs(store, args.input_variant)
        print("inputs verified" if ok else "CHECKSUM MISMATCH")
        return 0 if ok else 1
    elif args.command == "prepare":
        overrides = {}
        for item in args.fit_setting:
            name, _, value = item.partition("=")
            overrides[name] = json.loads(value)
        config = RunConfig(
            input_variant=args.input_variant,
            run_variant=args.run_variant,
            fit_settings=overrides,
            profile_points=args.profile_points,
        )
        root = prepare_run(store, config, groups=args.groups, days=args.days)
        print(root / "run.json")
    elif args.command == "run":
        root = run_root(store, args.run_variant)
        task = os.environ.get("SLURM_ARRAY_TASK_ID") or os.environ.get("SLURM_JOB_ID") or "local"
        log = _logger(root / "logs" / f"run-{task}-{os.getpid()}.log")
        outcome = run_days(
            store,
            args.run_variant,
            days=args.days,
            group=args.group,
            workers=args.workers,
            chunk=args.chunk,
            heartbeat=args.heartbeat,
            low=args.low_priority,
            log=log,
        )
        return 3 if outcome["stopped"] else 0
    elif args.command == "status":
        print(json.dumps(run_status(store, args.run_variant), indent=1))
    elif args.command == "finalize":
        print(finalize_run(store, args.run_variant))
    elif args.command == "compare":
        frame = scan_run(store, args.run_variant)
        reference = pl.concat([pl.read_parquet(p) for p in args.reference])
        print(json.dumps(compare_runs(frame, reference), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
