from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from sopran.bodies.moon.svm import read_tsunakawa_svm_npy
from sopran.bodies.moon.svm3d import SVM3DShellGrid, SVM3DTraceResult, SVM3DTraceSettings
from sopran.missions.kaguya.er_selection_validation import (
    validate_effective_field_selection,
)

ACCEPTED_GRADES = ("good", "review")
MOON_MEAN_RADIUS_KM = 1737.4


@dataclass(frozen=True)
class EffectiveFieldArchiveValidation:
    """Read-only validation result for a day-sharded KAGUYA ER catalog."""

    variant_path: Path
    summary: dict[str, Any]
    tables: dict[str, pd.DataFrame]
    violations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.violations

    def write(
        self,
        output: Path | str,
        *,
        figure_output: Path | str | None = None,
    ) -> None:
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        (target / "summary.json").write_text(
            json.dumps(_jsonable(self.summary), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for name, frame in self.tables.items():
            frame.to_csv(target / f"{name}.csv", index=False)
        if figure_output is not None:
            figures = Path(figure_output)
            figures.mkdir(parents=True, exist_ok=True)
            _write_figures(self.tables, figures)


def validate_effective_field_archive(
    variant_path: Path | str,
    *,
    svm_path: Path | str | None = None,
    svm3d_shell_path: Path | str | None = None,
    svm3d_source_path: Path | str | None = None,
    svm3d_accuracy_samples: int = 64,
    svm3d_trace_settings: SVM3DTraceSettings | None = None,
    audit_path: Path | str | None = None,
    spatial_bin_degrees: float = 20.0,
    strict: bool = True,
) -> EffectiveFieldArchiveValidation:
    """Validate catalog integrity and summarize its scientific selection function."""

    variant = Path(variant_path)
    state = _read_json(variant / "build-state.json")
    dataset = _read_json(variant / "dataset.json")
    shard_catalog = pd.read_parquet(variant / "catalog.parquet")
    frame, shard_rows, checksum_failures = _load_shards(variant, shard_catalog)
    _require_columns(frame)
    frame = frame.copy()
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame["accepted"] = frame["quality_grade"].isin(ACCEPTED_GRADES)

    violations = _integrity_violations(
        frame,
        state=state,
        dataset=dataset,
        shard_catalog=shard_catalog,
        shard_rows=shard_rows,
        checksum_failures=checksum_failures,
    )
    tables = _summary_tables(
        frame,
        state=state,
        dataset=dataset,
        spatial_bin_degrees=spatial_bin_degrees,
    )
    selection_validation = validate_effective_field_selection(frame)
    if not selection_validation.performance.empty:
        tables["selection_model_performance"] = selection_validation.performance
        tables["selection_model_coefficients"] = selection_validation.coefficients
        tables["selection_model_calibration"] = selection_validation.calibration

    svm_summary: dict[str, Any] | None = None
    if svm_path is not None:
        resolved_svm_path = Path(svm_path).resolve()
        radial_svm, footpoint_svm, footpoints = _sample_svm(
            frame,
            resolved_svm_path,
        )
        frame["svm_surface_field_nT"] = radial_svm
        frame["svm_straight_footpoint_field_nT"] = footpoint_svm
        for column in footpoints.columns:
            frame[column] = footpoints[column].to_numpy()
        svm_tables, svm_summary = _svm_tables(
            frame,
            spatial_bin_degrees=spatial_bin_degrees,
            source=resolved_svm_path,
        )
        tables.update(svm_tables)

    svm3d_summary: dict[str, Any] | None = None
    if svm3d_shell_path is not None:
        shell = SVM3DShellGrid.load(svm3d_shell_path)
        curved_tables, svm3d_summary = _curved_svm3d_tables(
            frame,
            shell=shell,
            source_path=None if svm3d_source_path is None else Path(svm3d_source_path),
            accuracy_samples=svm3d_accuracy_samples,
            settings=svm3d_trace_settings,
        )
        tables.update(curved_tables)

    audit_summary: dict[str, Any] | None = None
    if audit_path is not None:
        audit_table, audit_summary = _audit_table(frame, Path(audit_path))
        tables["visual_audit"] = audit_table
        if audit_summary["catalog_time_matches"] != audit_summary["rows"]:
            violations.append("visual_audit_unmatched_times")
        if audit_summary["catalog_grade_mismatches"]:
            violations.append("visual_audit_quality_mismatch")

    summary = _archive_summary(
        frame,
        state=state,
        dataset=dataset,
        shard_catalog=shard_catalog,
        tables=tables,
        violations=violations,
        svm_summary=svm_summary,
        svm3d_summary=svm3d_summary,
        audit_summary=audit_summary,
    )
    summary["selection_function_models"] = selection_validation.summary
    result = EffectiveFieldArchiveValidation(
        variant_path=variant,
        summary=summary,
        tables=tables,
        violations=tuple(violations),
    )
    if strict and not result.passed:
        raise ValueError("KAGUYA ER archive validation failed: " + "; ".join(violations))
    return result


def wilson_interval(
    successes: int,
    total: int,
    *,
    z: float = 1.959963984540054,
) -> tuple[float, float]:
    """Return a two-sided Wilson score interval for a binomial proportion."""

    if total < 0 or successes < 0 or successes > total:
        raise ValueError("successes and total must satisfy 0 <= successes <= total")
    if total == 0:
        return float("nan"), float("nan")
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    spread = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return center - spread, center + spread


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _load_shards(
    variant: Path,
    shard_catalog: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int], list[str]]:
    frames: list[pd.DataFrame] = []
    row_counts: dict[str, int] = {}
    checksum_failures: list[str] = []
    for row in shard_catalog.itertuples(index=False):
        if str(row.status) != "complete":
            continue
        path = variant.joinpath(*str(row.path).split("/"))
        if not path.exists():
            checksum_failures.append(f"missing:{row.path}")
            continue
        frame = pd.read_parquet(path)
        frames.append(frame)
        row_counts[str(row.path)] = len(frame)
        expected = str(row.checksum)
        actual = "sha256:" + _sha256(path)
        if expected != actual:
            checksum_failures.append(f"checksum:{row.path}")
    if not frames:
        raise FileNotFoundError(f"No complete ER shards under {variant}")
    return pd.concat(frames, ignore_index=True), row_counts, checksum_failures


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_columns(frame: pd.DataFrame) -> None:
    required = {
        "time",
        "source_day",
        "success",
        "reason",
        "selected_model",
        "edge_supported",
        "quality_grade",
        "mirror_ratio",
        "effective_field",
        "b_sc_nT",
        "magnetic_field_x",
        "magnetic_field_y",
        "magnetic_field_z",
        "position_x",
        "position_y",
        "position_z",
        "radial_distance",
        "altitude",
        "longitude",
        "latitude",
        "sza",
        "total_counts",
        "energy_ratio_step_supported",
        "exposure_mode",
        "sampling_cadence_seconds",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("ER catalog is missing required columns: " + ", ".join(missing))


def _integrity_violations(
    frame: pd.DataFrame,
    *,
    state: dict[str, Any],
    dataset: dict[str, Any],
    shard_catalog: pd.DataFrame,
    shard_rows: dict[str, int],
    checksum_failures: list[str],
) -> list[str]:
    violations: list[str] = list(checksum_failures)
    requested = state.get("requested_time", {})
    expected_days = _expected_days(requested)
    state_days = state.get("days", {})
    if not isinstance(state_days, dict):
        return [*violations, "invalid_state_days"]
    recorded_days = set(state_days)
    pending = sorted(expected_days - recorded_days)
    extra = sorted(recorded_days - expected_days)
    failed = sorted(
        label
        for label, value in state_days.items()
        if isinstance(value, dict) and value.get("status") == "failed"
    )
    if pending:
        violations.append(f"pending_days:{len(pending)}")
    if extra:
        violations.append(f"extra_days:{len(extra)}")
    if failed:
        violations.append(f"failed_days:{len(failed)}")

    complete_rows = shard_catalog[shard_catalog["status"] == "complete"]
    catalog_paths = set(complete_rows["path"].astype(str))
    state_complete = {
        f"shards/date={label}/part-000.parquet"
        for label, value in state_days.items()
        if isinstance(value, dict) and value.get("status") == "complete"
    }
    if catalog_paths != state_complete:
        violations.append("state_catalog_shard_set_mismatch")
    for row in complete_rows.itertuples(index=False):
        path = str(row.path)
        if path in shard_rows and int(str(row.row_count)) != shard_rows[path]:
            violations.append(f"catalog_row_count:{path}")
    state_row_count = sum(
        int(value.get("row_count") or 0)
        for value in state_days.values()
        if isinstance(value, dict) and value.get("status") == "complete"
    )
    if state_row_count != len(frame):
        violations.append("state_total_row_count")

    time = pd.to_datetime(frame["time"], utc=True)
    if int(time.duplicated().sum()):
        violations.append("duplicate_times")
    source_day = frame["source_day"].astype(str)
    if int((time.dt.strftime("%Y-%m-%d") != source_day).sum()):
        violations.append("source_day_time_mismatch")
    cadence = _cadence_seconds(dataset)
    if not np.allclose(
        frame["sampling_cadence_seconds"].to_numpy(dtype=float),
        cadence,
    ):
        violations.append("sampling_cadence_mismatch")
    if set(frame["exposure_mode"].dropna().astype(str)) != {"calibrated"}:
        violations.append("non_calibrated_exposure")

    magnetic = frame[["magnetic_field_x", "magnetic_field_y", "magnetic_field_z"]].to_numpy(
        dtype=float
    )
    position = frame[["position_x", "position_y", "position_z"]].to_numpy(dtype=float)
    geometry = frame[["radial_distance", "altitude", "longitude", "latitude", "sza"]].to_numpy(
        dtype=float
    )
    if not np.all(np.isfinite(magnetic)) or not np.all(np.isfinite(position)):
        violations.append("nonfinite_vectors")
    if not np.all(np.isfinite(geometry)):
        violations.append("nonfinite_geometry")
    b_norm = np.linalg.norm(magnetic, axis=1)
    r_norm = np.linalg.norm(position, axis=1)
    if _max_abs(b_norm - frame["b_sc_nT"].to_numpy(dtype=float)) > 1.0e-9:
        violations.append("b_sc_vector_norm")
    if _max_abs(r_norm - frame["radial_distance"].to_numpy(dtype=float)) > 1.0e-9:
        violations.append("radial_distance_vector_norm")
    altitude = frame["altitude"].to_numpy(dtype=float)
    if _max_abs(altitude - (r_norm - MOON_MEAN_RADIUS_KM)) > 1.0e-9:
        violations.append("altitude_radius_relation")

    accepted = frame["quality_grade"].isin(ACCEPTED_GRADES)
    edge = frame["edge_supported"].fillna(False).to_numpy(dtype=bool)
    if int(np.count_nonzero(accepted.to_numpy() & ~edge)):
        violations.append("accepted_without_edge")
    selected = frame["selected_model"].astype(str)
    if int((accepted & ~selected.isin(("mirror_only", "electrostatic"))).sum()):
        violations.append("accepted_non_edge_model")
    expected_field = frame["mirror_ratio"].to_numpy(dtype=float) * frame["b_sc_nT"].to_numpy(
        dtype=float
    )
    observed_field = frame["effective_field"].to_numpy(dtype=float)
    accepted_values = accepted.to_numpy()
    if _max_abs(expected_field[accepted_values] - observed_field[accepted_values]) > 1.0e-9:
        violations.append("effective_field_product")
    rejected = ~edge
    if np.any(np.isfinite(observed_field[rejected])):
        violations.append("field_present_without_edge")

    if str(dataset.get("dataset_id")) != "kaguya.er.effective_field":
        violations.append("dataset_id")
    return violations


def _summary_tables(
    frame: pd.DataFrame,
    *,
    state: dict[str, Any],
    dataset: dict[str, Any],
    spatial_bin_degrees: float,
) -> dict[str, pd.DataFrame]:
    accepted = frame["accepted"].to_numpy(dtype=bool)
    tables = {
        "quality": _count_table(frame["quality_grade"], len(frame)),
        "reasons": _count_table(frame["reason"], len(frame)),
        "models": _model_table(frame),
        "monthly": _monthly_table(frame, state=state, dataset=dataset),
        "sza": _fixed_bin_rate_table(
            frame,
            column="sza",
            edges=np.arange(0.0, 181.0, 30.0),
            accepted=accepted,
        ),
        "altitude": _fixed_bin_rate_table(
            frame,
            column="altitude",
            edges=np.asarray((-np.inf, 30.0, 60.0, 90.0, 120.0, 200.0, np.inf)),
            accepted=accepted,
        ),
        "total_counts": _quantile_rate_table(
            frame,
            column="total_counts",
            accepted=accepted,
        ),
        "b_sc": _quantile_rate_table(
            frame,
            column="b_sc_nT",
            accepted=accepted,
        ),
        "spatial_cells": _spatial_cells(
            frame,
            bin_degrees=spatial_bin_degrees,
        ),
    }
    return tables


def _count_table(values: pd.Series, total: int) -> pd.DataFrame:
    counts = values.fillna("<missing>").astype(str).value_counts(dropna=False)
    return pd.DataFrame(
        {
            "value": counts.index.astype(str),
            "count": counts.to_numpy(dtype=int),
            "fraction": counts.to_numpy(dtype=float) / total,
        }
    )


def _model_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model in ("no_edge", "mirror_only", "electrostatic"):
        mask = frame["selected_model"].astype(str).eq(model)
        accepted = mask & frame["accepted"]
        rows.append(
            {
                "model": model,
                "rows": int(mask.sum()),
                "accepted": int(accepted.sum()),
                "accepted_fraction_within_model": (
                    float(accepted.sum() / mask.sum()) if mask.any() else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows)


def _monthly_table(
    frame: pd.DataFrame,
    *,
    state: dict[str, Any],
    dataset: dict[str, Any],
) -> pd.DataFrame:
    requested = state["requested_time"]
    expected = pd.date_range(
        pd.Timestamp(requested["start"]),
        pd.Timestamp(requested["stop"]),
        freq="D",
        inclusive="left",
    )
    days = state["days"]
    day_frame = pd.DataFrame(
        {
            "day": expected,
            "status": [str(days[value.strftime("%Y-%m-%d")]["status"]) for value in expected],
        }
    )
    day_frame["month"] = day_frame["day"].dt.strftime("%Y-%m")
    day_counts = (
        day_frame.groupby("month", sort=True)["status"].value_counts().unstack(fill_value=0)
    )
    observed = frame.copy()
    observed["month"] = observed["time"].dt.strftime("%Y-%m")
    rates = _rate_rows(observed.groupby("month", sort=True), "month")
    result = day_counts.reset_index().merge(rates, on="month", how="outer")
    for status in ("complete", "missing", "no_data", "failed"):
        if status not in result:
            result[status] = 0
    cadence = _cadence_seconds(dataset)
    slots = int(round(86400.0 / cadence))
    result["requested_days"] = result[["complete", "missing", "no_data", "failed"]].sum(axis=1)
    result["requested_slots"] = result["requested_days"] * slots
    result["complete_day_slots"] = result["complete"] * slots
    result["coverage_of_requested_slots"] = result["attempts"] / result["requested_slots"]
    result["coverage_within_complete_days"] = result["attempts"] / result["complete_day_slots"]
    return result.sort_values("month", ignore_index=True)


def _fixed_bin_rate_table(
    frame: pd.DataFrame,
    *,
    column: str,
    edges: np.ndarray,
    accepted: np.ndarray,
) -> pd.DataFrame:
    values = frame[column].to_numpy(dtype=float)
    rows: list[dict[str, Any]] = []
    for index, (lower, upper) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
        if index == len(edges) - 2:
            mask = np.isfinite(values) & (values >= lower) & (values <= upper)
        else:
            mask = np.isfinite(values) & (values >= lower) & (values < upper)
        if not np.any(mask):
            continue
        label = f"[{lower:g}, {upper:g}{']' if index == len(edges) - 2 else ')'}"
        row = _rate_record(label, accepted[mask])
        row.update(
            {
                "lower": float(lower),
                "upper": float(upper),
                "value_median": float(np.nanmedian(values[mask])),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _quantile_rate_table(
    frame: pd.DataFrame,
    *,
    column: str,
    accepted: np.ndarray,
    quantiles: int = 5,
) -> pd.DataFrame:
    values = frame[column].to_numpy(dtype=float)
    valid = np.isfinite(values)
    groups = pd.qcut(values[valid], quantiles, labels=False, duplicates="drop")
    work = pd.DataFrame(
        {
            "group": groups,
            "accepted": accepted[valid],
            "value": values[valid],
        }
    )
    rows: list[dict[str, Any]] = []
    for group, subset in work.groupby("group", sort=True):
        group_index = int(str(group))
        row = _rate_record(
            f"Q{group_index + 1}",
            subset["accepted"].to_numpy(dtype=bool),
        )
        row.update(
            {
                "lower": float(subset["value"].min()),
                "upper": float(subset["value"].max()),
                "value_median": float(subset["value"].median()),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _rate_rows(groups: Any, group_name: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for group, subset in groups:
        record = _rate_record(
            str(group),
            subset["accepted"].to_numpy(dtype=bool),
        )
        record[group_name] = str(group)
        rows.append(record)
    return pd.DataFrame(rows).drop(columns=["group"])


def _rate_record(group: str, accepted: np.ndarray) -> dict[str, Any]:
    total = int(accepted.size)
    successes = int(np.count_nonzero(accepted))
    low, high = wilson_interval(successes, total)
    return {
        "group": group,
        "attempts": total,
        "accepted": successes,
        "accepted_fraction": successes / total if total else float("nan"),
        "wilson95_low": low,
        "wilson95_high": high,
    }


def _spatial_cells(frame: pd.DataFrame, *, bin_degrees: float) -> pd.DataFrame:
    if (
        not np.isfinite(bin_degrees)
        or bin_degrees <= 0.0
        or not np.isclose(360.0 % bin_degrees, 0.0)
        or not np.isclose(180.0 % bin_degrees, 0.0)
    ):
        raise ValueError("spatial_bin_degrees must divide 180 and 360")
    work = frame.copy()
    work["longitude_wrapped"] = ((work["longitude"] + 180.0) % 360.0) - 180.0
    work["lon_index"] = np.minimum(
        np.floor((work["longitude_wrapped"] + 180.0) / bin_degrees),
        360.0 / bin_degrees - 1,
    ).astype(int)
    work["lat_index"] = np.minimum(
        np.floor((work["latitude"] + 90.0) / bin_degrees),
        180.0 / bin_degrees - 1,
    ).astype(int)
    rows: list[dict[str, Any]] = []
    for raw_key, subset in work.groupby(["lon_index", "lat_index"], sort=True):
        lon_key, lat_key = cast(tuple[Any, Any], raw_key)
        lon_index = int(str(lon_key))
        lat_index = int(str(lat_key))
        accepted = subset["accepted"].to_numpy(dtype=bool)
        edge = subset["edge_supported"].fillna(False).to_numpy(dtype=bool)
        good = subset["quality_grade"].astype(str).eq("good").to_numpy()
        fields = subset.loc[accepted, "effective_field"].to_numpy(dtype=float)
        rows.append(
            {
                "lon_center": -180.0 + (lon_index + 0.5) * bin_degrees,
                "lat_center": -90.0 + (lat_index + 0.5) * bin_degrees,
                "attempts": len(subset),
                "edge_supported": int(np.count_nonzero(edge)),
                "accepted": int(np.count_nonzero(accepted)),
                "good": int(np.count_nonzero(good)),
                "accepted_fraction": float(np.mean(accepted)),
                "median_effective_field_nT": _finite_percentile(fields, 50.0),
            }
        )
    return pd.DataFrame(rows)


def _sample_svm(
    frame: pd.DataFrame,
    path: Path,
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    layer = read_tsunakawa_svm_npy(
        path,
        source="kaguya.lmag.svm_tsunakawa2015",
    )
    radial = np.asarray(
        layer.sample(
            lat=frame["latitude"].to_numpy(dtype=float),
            lon=frame["longitude"].to_numpy(dtype=float),
        ),
        dtype=float,
    )
    footpoints = _straight_local_footpoints(frame)
    connected = footpoints["straight_local_connected"].to_numpy(dtype=bool)
    footpoint = np.full(len(frame), np.nan, dtype=float)
    footpoint[connected] = np.asarray(
        layer.sample(
            lat=footpoints.loc[connected, "straight_footpoint_latitude"].to_numpy(dtype=float),
            lon=footpoints.loc[connected, "straight_footpoint_longitude"].to_numpy(dtype=float),
        ),
        dtype=float,
    )
    return radial, footpoint, footpoints


def _straight_local_footpoints(frame: pd.DataFrame) -> pd.DataFrame:
    position = frame[["position_x", "position_y", "position_z"]].to_numpy(dtype=float)
    magnetic = frame[["magnetic_field_x", "magnetic_field_y", "magnetic_field_z"]].to_numpy(
        dtype=float
    )
    b_norm = np.linalg.norm(magnetic, axis=1)
    radial_dot = np.sum(position * magnetic, axis=1)
    valid = (
        np.all(np.isfinite(position), axis=1)
        & np.all(np.isfinite(magnetic), axis=1)
        & np.isfinite(b_norm)
        & (b_norm > 0.0)
        & np.isfinite(radial_dot)
        & (radial_dot != 0.0)
    )
    direction = np.full_like(magnetic, np.nan, dtype=float)
    direction[valid] = -np.sign(radial_dot[valid, None]) * magnetic[valid] / b_norm[valid, None]
    linear = 2.0 * np.sum(position * direction, axis=1)
    constant = np.sum(position * position, axis=1) - MOON_MEAN_RADIUS_KM**2
    discriminant = linear * linear - 4.0 * constant
    connected = valid & np.isfinite(discriminant) & (discriminant >= 0.0)
    distance = np.full(len(frame), np.nan, dtype=float)
    distance[connected] = (-linear[connected] - np.sqrt(discriminant[connected])) / 2.0
    connected &= np.isfinite(distance) & (distance >= 0.0)

    footpoint = np.full_like(position, np.nan, dtype=float)
    footpoint[connected] = position[connected] + distance[connected, None] * direction[connected]
    radius = np.linalg.norm(footpoint, axis=1)
    longitude = np.full(len(frame), np.nan, dtype=float)
    latitude = np.full(len(frame), np.nan, dtype=float)
    separation = np.full(len(frame), np.nan, dtype=float)
    longitude[connected] = np.degrees(np.arctan2(footpoint[connected, 1], footpoint[connected, 0]))
    latitude[connected] = np.degrees(
        np.arcsin(
            np.clip(
                footpoint[connected, 2] / radius[connected],
                -1.0,
                1.0,
            )
        )
    )
    position_norm = np.linalg.norm(position, axis=1)
    cosine = np.sum(position * footpoint, axis=1) / (position_norm * radius)
    separation[connected] = np.degrees(np.arccos(np.clip(cosine[connected], -1.0, 1.0)))
    return pd.DataFrame(
        {
            "straight_local_connected": connected,
            "straight_footpoint_longitude": longitude,
            "straight_footpoint_latitude": latitude,
            "straight_footpoint_distance_km": distance,
            "straight_footpoint_separation_deg": separation,
        }
    )


def _svm_tables(
    frame: pd.DataFrame,
    *,
    spatial_bin_degrees: float,
    source: Path,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    accepted = frame["accepted"].to_numpy(dtype=bool)
    svm_bins = _quantile_rate_table(
        frame,
        column="svm_surface_field_nT",
        accepted=accepted,
    )
    footpoint_svm_bins = _quantile_rate_table(
        frame,
        column="svm_straight_footpoint_field_nT",
        accepted=accepted,
    )
    cells = _spatial_cells(frame, bin_degrees=spatial_bin_degrees)
    work = frame.copy()
    work["longitude_wrapped"] = ((work["longitude"] + 180.0) % 360.0) - 180.0
    work["lon_index"] = np.minimum(
        np.floor((work["longitude_wrapped"] + 180.0) / spatial_bin_degrees),
        360.0 / spatial_bin_degrees - 1,
    ).astype(int)
    work["lat_index"] = np.minimum(
        np.floor((work["latitude"] + 90.0) / spatial_bin_degrees),
        180.0 / spatial_bin_degrees - 1,
    ).astype(int)
    cell_svm = (
        work.groupby(["lon_index", "lat_index"], sort=True)["svm_surface_field_nT"]
        .median()
        .to_numpy(dtype=float)
    )
    cells["median_svm_surface_field_nT"] = cell_svm

    correlation_rows: list[dict[str, Any]] = []
    conditions = {
        "good": frame["quality_grade"].astype(str).eq("good").to_numpy(),
        "good + review": accepted,
        "good + review, no energy step": (
            accepted & ~frame["energy_ratio_step_supported"].fillna(False).to_numpy(dtype=bool)
        ),
        "all edge-supported": frame["edge_supported"].fillna(False).to_numpy(dtype=bool),
    }
    for name, mask in conditions.items():
        y = frame.loc[mask, "effective_field"].to_numpy(dtype=float)
        for location, column in (
            ("radial_subpoint", "svm_surface_field_nT"),
            ("straight_local_footpoint", "svm_straight_footpoint_field_nT"),
        ):
            x = frame.loc[mask, column].to_numpy(dtype=float)
            correlation_rows.append(
                _correlation_record(
                    name,
                    "row_b_eff",
                    x,
                    y,
                    location=location,
                )
            )
    cell_mask = cells["attempts"].to_numpy(dtype=int) >= 30
    correlation_rows.append(
        _correlation_record(
            "20-degree cells, attempts >= 30",
            "accepted_fraction",
            cells.loc[cell_mask, "median_svm_surface_field_nT"].to_numpy(dtype=float),
            cells.loc[cell_mask, "accepted_fraction"].to_numpy(dtype=float),
            location="radial_subpoint",
        )
    )
    field_cell_mask = cells["accepted"].to_numpy(dtype=int) >= 3
    correlation_rows.append(
        _correlation_record(
            "20-degree cells, accepted >= 3",
            "median_b_eff",
            cells.loc[field_cell_mask, "median_svm_surface_field_nT"].to_numpy(dtype=float),
            cells.loc[field_cell_mask, "median_effective_field_nT"].to_numpy(dtype=float),
            location="radial_subpoint",
        )
    )

    footpoint_frame = frame.loc[frame["straight_local_connected"].to_numpy(dtype=bool)].copy()
    footpoint_frame["longitude"] = footpoint_frame["straight_footpoint_longitude"]
    footpoint_frame["latitude"] = footpoint_frame["straight_footpoint_latitude"]
    footpoint_cells = _spatial_cells(
        footpoint_frame,
        bin_degrees=spatial_bin_degrees,
    )
    footpoint_work = footpoint_frame.copy()
    footpoint_work["longitude_wrapped"] = ((footpoint_work["longitude"] + 180.0) % 360.0) - 180.0
    footpoint_work["lon_index"] = np.minimum(
        np.floor((footpoint_work["longitude_wrapped"] + 180.0) / spatial_bin_degrees),
        360.0 / spatial_bin_degrees - 1,
    ).astype(int)
    footpoint_work["lat_index"] = np.minimum(
        np.floor((footpoint_work["latitude"] + 90.0) / spatial_bin_degrees),
        180.0 / spatial_bin_degrees - 1,
    ).astype(int)
    footpoint_cells["median_svm_surface_field_nT"] = (
        footpoint_work.groupby(["lon_index", "lat_index"], sort=True)[
            "svm_straight_footpoint_field_nT"
        ]
        .median()
        .to_numpy(dtype=float)
    )
    footpoint_cell_mask = footpoint_cells["attempts"].to_numpy(dtype=int) >= 30
    correlation_rows.append(
        _correlation_record(
            "20-degree cells, attempts >= 30",
            "accepted_fraction",
            footpoint_cells.loc[footpoint_cell_mask, "median_svm_surface_field_nT"].to_numpy(
                dtype=float
            ),
            footpoint_cells.loc[footpoint_cell_mask, "accepted_fraction"].to_numpy(dtype=float),
            location="straight_local_footpoint",
        )
    )
    footpoint_field_mask = footpoint_cells["accepted"].to_numpy(dtype=int) >= 3
    correlation_rows.append(
        _correlation_record(
            "20-degree cells, accepted >= 3",
            "median_b_eff",
            footpoint_cells.loc[footpoint_field_mask, "median_svm_surface_field_nT"].to_numpy(
                dtype=float
            ),
            footpoint_cells.loc[footpoint_field_mask, "median_effective_field_nT"].to_numpy(
                dtype=float
            ),
            location="straight_local_footpoint",
        )
    )
    connection = _straight_connection_table(frame)
    correlations = pd.DataFrame(correlation_rows)
    connected_accepted = frame["straight_local_connected"].to_numpy(dtype=bool) & accepted
    summary = {
        "source": str(source),
        "radial_subpoint": {
            "accepted_rate_lowest_quintile": float(svm_bins.iloc[0]["accepted_fraction"]),
            "accepted_rate_highest_quintile": float(svm_bins.iloc[-1]["accepted_fraction"]),
            "correlations": correlations.loc[correlations["location"] == "radial_subpoint"].to_dict(
                "records"
            ),
        },
        "straight_local_footpoint": {
            "field_model": "straight_local_field_line",
            "surface_radius_km": MOON_MEAN_RADIUS_KM,
            "accepted_footpoint_distance_km": _distribution(
                frame.loc[connected_accepted, "straight_footpoint_distance_km"].to_numpy(
                    dtype=float
                )
            ),
            "accepted_radial_separation_deg": _distribution(
                frame.loc[connected_accepted, "straight_footpoint_separation_deg"].to_numpy(
                    dtype=float
                )
            ),
            "accepted_rate_lowest_quintile": float(footpoint_svm_bins.iloc[0]["accepted_fraction"]),
            "accepted_rate_highest_quintile": float(
                footpoint_svm_bins.iloc[-1]["accepted_fraction"]
            ),
            "connection": connection.to_dict("records"),
            "correlations": correlations.loc[
                correlations["location"] == "straight_local_footpoint"
            ].to_dict("records"),
        },
    }
    return {
        "svm_bins": svm_bins,
        "svm_straight_footpoint_bins": footpoint_svm_bins,
        "svm_correlations": correlations,
        "straight_local_connection": connection,
        "spatial_cells": cells,
        "straight_footpoint_spatial_cells": footpoint_cells,
    }, summary


def _curved_svm3d_tables(
    frame: pd.DataFrame,
    *,
    shell: SVM3DShellGrid,
    source_path: Path | None,
    accuracy_samples: int,
    settings: SVM3DTraceSettings | None,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    positions = frame[["position_x", "position_y", "position_z"]].to_numpy(dtype=float)
    measured = frame[
        ["magnetic_field_x", "magnetic_field_y", "magnetic_field_z"]
    ].to_numpy(dtype=float)
    svm_spacecraft = shell.field_at(positions)
    external = measured - svm_spacecraft
    target = frame["effective_field"].to_numpy(dtype=float)
    selected_settings = settings or SVM3DTraceSettings(
        stop_altitude_km=float(shell.altitude_km[0])
    )
    plus = shell.trace(
        positions,
        external,
        np.ones(len(frame), dtype=np.int32),
        target_field_nT=target,
        settings=selected_settings,
    )
    minus = shell.trace(
        positions,
        external,
        -np.ones(len(frame), dtype=np.int32),
        target_field_nT=target,
        settings=selected_settings,
    )
    affected = frame["affected_side"].astype(str).str.lower().to_numpy()
    expected_sign = np.where(affected == "high", 1, -1).astype(np.int32)
    trace_table = _curved_trace_table(
        frame,
        plus=plus,
        minus=minus,
        expected_sign=expected_sign,
    )
    connections = _curved_connection_table(frame, trace_table)
    correlations = _curved_correlation_table(frame, trace_table)
    accuracy = None
    accuracy_by_altitude: list[dict[str, Any]] = []
    if source_path is not None:
        accuracy = shell.accuracy_report(
            source_path,
            samples=accuracy_samples,
            seed=20260823,
        )
        interval_samples = max(32, math.ceil(accuracy_samples / (shell.altitude_km.size - 1)))
        for index, (lower, upper) in enumerate(
            zip(shell.altitude_km[:-1], shell.altitude_km[1:], strict=True)
        ):
            accuracy_by_altitude.append(
                shell.accuracy_report(
                    source_path,
                    samples=interval_samples,
                    seed=20260824 + index,
                    min_altitude_km=float(lower),
                    max_altitude_km=float(upper),
                )
            )
    accepted = frame["accepted"].to_numpy(dtype=bool)
    both_connected = (
        trace_table["plus_valid"].to_numpy(dtype=bool)
        & trace_table["minus_valid"].to_numpy(dtype=bool)
    )
    separation = _angular_separation_deg(
        trace_table["plus_footpoint_longitude_deg"].to_numpy(dtype=float),
        trace_table["plus_footpoint_latitude_deg"].to_numpy(dtype=float),
        trace_table["minus_footpoint_longitude_deg"].to_numpy(dtype=float),
        trace_table["minus_footpoint_latitude_deg"].to_numpy(dtype=float),
    )
    fail_codes = {
        "preferred": _value_counts(trace_table["preferred_fail_code"]),
        "opposite": _value_counts(trace_table["opposite_fail_code"]),
        "plus": _value_counts(trace_table["plus_fail_code"]),
        "minus": _value_counts(trace_table["minus_fail_code"]),
    }
    summary = {
        "field_model": {
            "crustal_field": "Tsunakawa SVM3D shell interpolation",
            "external_field": "uniform LMAG residual at each spacecraft sample",
            "equation": "B_total(r) = B_LMAG(sc) - B_SVM3D(sc) + B_SVM3D(r)",
            "integrator": "fixed-step RK4 in arc length",
            "branch_convention": (
                "low-pitch velocity is backtraced along -B; high-pitch velocity along +B"
            ),
            "branch_caveat": (
                "Both signs are retained because detector look-direction conventions can invert "
                "the velocity backtrace assignment."
            ),
            "target_point_definition": (
                "first traced point whose model |B_total| reaches fitted B_eff; this point is "
                "derived from B_eff and is not an independent validation target"
            ),
            "trace_fail_codes": {
                "0": "connected to the configured lower shell",
                "1": "invalid input or branch sign",
                "2": "non-finite field or position outside the shell grid",
                "3": "escaped above the highest shell",
                "4": "maximum trace steps reached",
            },
            "settings": {
                "step_km": selected_settings.step_km,
                "max_steps": selected_settings.max_steps,
                "stop_altitude_km": selected_settings.stop_altitude_km,
            },
        },
        "shell": shell.provenance(),
        "direct_accuracy": accuracy,
        "direct_accuracy_by_altitude": accuracy_by_altitude,
        "connections": connections.to_dict("records"),
        "fail_codes": fail_codes,
        "correlations": correlations.to_dict("records"),
        "accepted": {
            "rows": int(np.count_nonzero(accepted)),
            "preferred_connected": int(
                np.count_nonzero(accepted & trace_table["preferred_valid"].to_numpy(dtype=bool))
            ),
            "preferred_target_crossed_before_trace_end": int(
                np.count_nonzero(
                    accepted & trace_table["preferred_target_crossed"].to_numpy(dtype=bool)
                )
            ),
            "preferred_target_crossed_on_connected_trace": int(
                np.count_nonzero(
                    accepted
                    & trace_table["preferred_valid"].to_numpy(dtype=bool)
                    & trace_table["preferred_target_crossed"].to_numpy(dtype=bool)
                )
            ),
            "opposite_connected": int(
                np.count_nonzero(accepted & trace_table["opposite_valid"].to_numpy(dtype=bool))
            ),
            "opposite_target_crossed_before_trace_end": int(
                np.count_nonzero(
                    accepted & trace_table["opposite_target_crossed"].to_numpy(dtype=bool)
                )
            ),
            "opposite_target_crossed_on_connected_trace": int(
                np.count_nonzero(
                    accepted
                    & trace_table["opposite_valid"].to_numpy(dtype=bool)
                    & trace_table["opposite_target_crossed"].to_numpy(dtype=bool)
                )
            ),
            "preferred_model_to_observed": _distribution(
                trace_table.loc[accepted, "preferred_model_to_observed"].to_numpy(dtype=float)
            ),
            "opposite_model_to_observed": _distribution(
                trace_table.loc[accepted, "opposite_model_to_observed"].to_numpy(dtype=float)
            ),
            "preferred_target_altitude_km": _distribution(
                trace_table.loc[accepted, "preferred_target_altitude_km"].to_numpy(dtype=float)
            ),
            "opposite_target_altitude_km": _distribution(
                trace_table.loc[accepted, "opposite_target_altitude_km"].to_numpy(dtype=float)
            ),
        },
        "both_branches": {
            "connected_rows": int(np.count_nonzero(both_connected)),
            "accepted_connected_rows": int(np.count_nonzero(accepted & both_connected)),
            "footpoint_separation_deg": _distribution(separation[both_connected]),
        },
    }
    return {
        "svm3d_curved_traces": trace_table,
        "svm3d_connections": connections,
        "svm3d_correlations": correlations,
    }, summary


def _curved_trace_table(
    frame: pd.DataFrame,
    *,
    plus: SVM3DTraceResult,
    minus: SVM3DTraceResult,
    expected_sign: np.ndarray,
) -> pd.DataFrame:
    table = frame[
        [
            "time",
            "source_day",
            "quality_grade",
            "affected_side",
            "edge_supported",
            "energy_ratio_step_supported",
            "b_sc_nT",
            "mirror_ratio",
            "effective_field",
        ]
    ].copy()
    table["expected_connection_sign"] = expected_sign
    compact_columns = (
        "valid",
        "fail_code",
        "steps",
        "path_km",
        "footpoint_longitude_deg",
        "footpoint_latitude_deg",
        "footpoint_altitude_km",
        "maximum_svm_nT",
        "maximum_svm_longitude_deg",
        "maximum_svm_latitude_deg",
        "maximum_svm_altitude_km",
        "maximum_total_nT",
        "maximum_total_longitude_deg",
        "maximum_total_latitude_deg",
        "maximum_total_altitude_km",
        "target_crossed",
        "target_longitude_deg",
        "target_latitude_deg",
        "target_altitude_km",
        "target_path_km",
        "target_svm_nT",
    )
    for name in compact_columns:
        plus_values = plus.arrays[name]
        minus_values = minus.arrays[name]
        table[f"plus_{name}"] = plus_values
        table[f"minus_{name}"] = minus_values
        table[f"preferred_{name}"] = np.where(expected_sign == 1, plus_values, minus_values)
        table[f"opposite_{name}"] = np.where(expected_sign == 1, minus_values, plus_values)
    b_sc = table["b_sc_nT"].to_numpy(dtype=float)
    observed = table["effective_field"].to_numpy(dtype=float)
    for branch in ("preferred", "opposite", "plus", "minus"):
        maximum = table[f"{branch}_maximum_total_nT"].to_numpy(dtype=float)
        table[f"{branch}_model_mirror_ratio"] = maximum / b_sc
        table[f"{branch}_model_excess_nT"] = maximum - b_sc
        table[f"{branch}_model_to_observed"] = maximum / observed
    return table


def _curved_connection_table(
    frame: pd.DataFrame,
    traces: pd.DataFrame,
) -> pd.DataFrame:
    accepted = frame["accepted"].to_numpy(dtype=bool)
    effective_field = frame["effective_field"].to_numpy(dtype=float)
    selections = {
        "all fit rows": np.ones(len(frame), dtype=bool),
        "good": frame["quality_grade"].astype(str).eq("good").to_numpy(),
        "review": frame["quality_grade"].astype(str).eq("review").to_numpy(),
        "good + review": accepted,
        "good + review, no energy step": (
            accepted & ~frame["energy_ratio_step_supported"].fillna(False).to_numpy(dtype=bool)
        ),
        "poor": frame["quality_grade"].astype(str).eq("poor").to_numpy(),
        "reject": frame["quality_grade"].astype(str).eq("reject").to_numpy(),
        "all edge-supported": frame["edge_supported"].fillna(False).to_numpy(dtype=bool),
    }
    rows: list[dict[str, Any]] = []
    for branch in ("preferred", "opposite", "plus", "minus"):
        connected = traces[f"{branch}_valid"].to_numpy(dtype=bool)
        crossed = traces[f"{branch}_target_crossed"].to_numpy(dtype=bool)
        for selection, mask in selections.items():
            total = int(np.count_nonzero(mask))
            connected_count = int(np.count_nonzero(mask & connected))
            target_rows = int(np.count_nonzero(mask & np.isfinite(effective_field)))
            crossed_before_trace_end = int(np.count_nonzero(mask & crossed))
            crossed_on_connected_trace = int(np.count_nonzero(mask & connected & crossed))
            low, high = wilson_interval(connected_count, total)
            rows.append(
                {
                    "branch": branch,
                    "selection": selection,
                    "rows": total,
                    "connected": connected_count,
                    "connected_fraction": connected_count / total if total else float("nan"),
                    "connected_wilson95_low": low,
                    "connected_wilson95_high": high,
                    "target_rows": target_rows,
                    "target_crossed_before_trace_end": crossed_before_trace_end,
                    "target_crossed_before_trace_end_fraction": (
                        crossed_before_trace_end / target_rows if target_rows else float("nan")
                    ),
                    "target_crossed_on_connected_trace": crossed_on_connected_trace,
                    "target_crossed_on_connected_trace_fraction": (
                        crossed_on_connected_trace / target_rows
                        if target_rows
                        else float("nan")
                    ),
                }
            )
    return pd.DataFrame(rows)


def _curved_correlation_table(
    frame: pd.DataFrame,
    traces: pd.DataFrame,
) -> pd.DataFrame:
    accepted = frame["accepted"].to_numpy(dtype=bool)
    selections = {
        "good": frame["quality_grade"].astype(str).eq("good").to_numpy(),
        "good + review": accepted,
        "good + review, no energy step": (
            accepted & ~frame["energy_ratio_step_supported"].fillna(False).to_numpy(dtype=bool)
        ),
        "all edge-supported": frame["edge_supported"].fillna(False).to_numpy(dtype=bool),
    }
    observed_field = frame["effective_field"].to_numpy(dtype=float)
    observed_ratio = frame["mirror_ratio"].to_numpy(dtype=float)
    b_sc = frame["b_sc_nT"].to_numpy(dtype=float)
    rows: list[dict[str, Any]] = []
    for branch in ("preferred", "opposite", "plus", "minus"):
        maximum_total = traces[f"{branch}_maximum_total_nT"].to_numpy(dtype=float)
        maximum_svm = traces[f"{branch}_maximum_svm_nT"].to_numpy(dtype=float)
        model_ratio = traces[f"{branch}_model_mirror_ratio"].to_numpy(dtype=float)
        for selection, mask in selections.items():
            location = f"curved_svm3d_{branch}"
            rows.extend(
                [
                    _correlation_record(
                        selection,
                        "effective_field_vs_path_total_max",
                        maximum_total[mask],
                        observed_field[mask],
                        location=location,
                    ),
                    _correlation_record(
                        selection,
                        "mirror_ratio_vs_path_total_max_over_b_sc",
                        model_ratio[mask],
                        observed_ratio[mask],
                        location=location,
                    ),
                    _correlation_record(
                        selection,
                        "effective_field_excess_vs_path_total_excess",
                        (maximum_total - b_sc)[mask],
                        (observed_field - b_sc)[mask],
                        location=location,
                    ),
                    _correlation_record(
                        selection,
                        "effective_field_vs_path_svm_max",
                        maximum_svm[mask],
                        observed_field[mask],
                        location=location,
                    ),
                    _partial_rank_correlation_record(
                        selection,
                        "effective_field_vs_path_total_max_given_b_sc",
                        maximum_total[mask],
                        observed_field[mask],
                        b_sc[mask],
                        location=location,
                    ),
                ]
            )
    return pd.DataFrame(rows)


def _partial_rank_correlation_record(
    selection: str,
    target: str,
    x: np.ndarray,
    y: np.ndarray,
    control: np.ndarray,
    *,
    location: str,
) -> dict[str, Any]:
    from scipy.stats import rankdata  # type: ignore[import-untyped]

    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(control)
    count = int(np.count_nonzero(valid))
    coefficient = float("nan")
    if count >= 4:
        ranked_x = rankdata(x[valid])
        ranked_y = rankdata(y[valid])
        ranked_control = rankdata(control[valid])
        design = np.column_stack((np.ones(count), ranked_control))
        residual_x = ranked_x - design @ np.linalg.lstsq(design, ranked_x, rcond=None)[0]
        residual_y = ranked_y - design @ np.linalg.lstsq(design, ranked_y, rcond=None)[0]
        if np.std(residual_x) > 0.0 and np.std(residual_y) > 0.0:
            coefficient = float(np.corrcoef(residual_x, residual_y)[0, 1])
    return {
        "location": location,
        "selection": selection,
        "target": target,
        "n": count,
        "spearman_rho": coefficient,
    }


def _angular_separation_deg(
    lon_a_deg: np.ndarray,
    lat_a_deg: np.ndarray,
    lon_b_deg: np.ndarray,
    lat_b_deg: np.ndarray,
) -> np.ndarray:
    lon_a = np.radians(lon_a_deg)
    lat_a = np.radians(lat_a_deg)
    lon_b = np.radians(lon_b_deg)
    lat_b = np.radians(lat_b_deg)
    cosine = (
        np.sin(lat_a) * np.sin(lat_b)
        + np.cos(lat_a) * np.cos(lat_b) * np.cos(lon_a - lon_b)
    )
    return cast(np.ndarray, np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def _value_counts(values: pd.Series) -> dict[str, int]:
    return {
        str(key): int(value)
        for key, value in values.value_counts(dropna=False).sort_index().items()
    }


def _straight_connection_table(frame: pd.DataFrame) -> pd.DataFrame:
    connected = frame["straight_local_connected"].to_numpy(dtype=bool)
    accepted = frame["accepted"].to_numpy(dtype=bool)
    selections = {
        "all fit rows": np.ones(len(frame), dtype=bool),
        "good": frame["quality_grade"].astype(str).eq("good").to_numpy(),
        "review": frame["quality_grade"].astype(str).eq("review").to_numpy(),
        "good + review": accepted,
        "good + review, no energy step": (
            accepted & ~frame["energy_ratio_step_supported"].fillna(False).to_numpy(dtype=bool)
        ),
        "poor": frame["quality_grade"].astype(str).eq("poor").to_numpy(),
        "reject": frame["quality_grade"].astype(str).eq("reject").to_numpy(),
        "all edge-supported": frame["edge_supported"].fillna(False).to_numpy(dtype=bool),
    }
    rows: list[dict[str, Any]] = []
    for selection, mask in selections.items():
        total = int(np.count_nonzero(mask))
        count = int(np.count_nonzero(mask & connected))
        low, high = wilson_interval(count, total)
        rows.append(
            {
                "selection": selection,
                "rows": total,
                "connected": count,
                "connected_fraction": count / total if total else float("nan"),
                "wilson95_low": low,
                "wilson95_high": high,
            }
        )
    return pd.DataFrame(rows)


def _correlation_record(
    selection: str,
    target: str,
    x: np.ndarray,
    y: np.ndarray,
    *,
    location: str,
) -> dict[str, Any]:
    from scipy.stats import spearmanr

    valid = np.isfinite(x) & np.isfinite(y)
    if np.count_nonzero(valid) < 3:
        rho = float("nan")
    else:
        rho = float(spearmanr(x[valid], y[valid]).statistic)
    return {
        "location": location,
        "selection": selection,
        "target": target,
        "n": int(np.count_nonzero(valid)),
        "spearman_rho": rho,
    }


def _audit_table(
    catalog: pd.DataFrame,
    audit_path: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    audit = pd.read_csv(audit_path)
    required = {"time", "quality_grade", "manual_grade"}
    missing = sorted(required - set(audit.columns))
    if missing:
        raise ValueError("Visual audit is missing columns: " + ", ".join(missing))
    audit = audit.copy()
    audit["time"] = pd.to_datetime(audit["time"], utc=True)
    audit["manual_success"] = audit["manual_grade"].isin(("clear", "plausible"))
    catalog_grades = catalog[["time", "quality_grade"]].rename(
        columns={"quality_grade": "catalog_quality_grade"}
    )
    matched = audit.merge(catalog_grades, on="time", how="left", validate="many_to_one")
    matched_count = int(matched["catalog_quality_grade"].notna().sum())
    mismatch_count = int(
        (
            matched["catalog_quality_grade"].notna()
            & (matched["catalog_quality_grade"].astype(str) != matched["quality_grade"].astype(str))
        ).sum()
    )
    rows: list[dict[str, Any]] = []
    selections = {
        "good": audit["quality_grade"].astype(str).eq("good"),
        "review": audit["quality_grade"].astype(str).eq("review"),
        "good + review": audit["quality_grade"].isin(ACCEPTED_GRADES),
        "poor": audit["quality_grade"].astype(str).eq("poor"),
    }
    for name, mask in selections.items():
        subset = audit.loc[mask]
        total = len(subset)
        successes = int(subset["manual_success"].sum())
        low, high = wilson_interval(successes, total)
        rows.append(
            {
                "selection": name,
                "n": total,
                "visual_success": successes,
                "visual_failed": total - successes,
                "visual_success_fraction": successes / total if total else float("nan"),
                "wilson95_low": low,
                "wilson95_high": high,
            }
        )
    table = pd.DataFrame(rows)
    summary = {
        "rows": len(audit),
        "days": sorted(audit.get("audit_day", pd.Series(dtype=str)).astype(str).unique()),
        "manual_grade_counts": {
            str(key): int(value) for key, value in audit["manual_grade"].value_counts().items()
        },
        "catalog_time_matches": matched_count,
        "catalog_grade_mismatches": mismatch_count,
        "selection": table.to_dict("records"),
    }
    return table, summary


def _archive_summary(
    frame: pd.DataFrame,
    *,
    state: dict[str, Any],
    dataset: dict[str, Any],
    shard_catalog: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    violations: list[str],
    svm_summary: dict[str, Any] | None,
    svm3d_summary: dict[str, Any] | None,
    audit_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    statuses = Counter(
        str(value.get("status")) for value in state["days"].values() if isinstance(value, dict)
    )
    cadence = _cadence_seconds(dataset)
    slots_per_day = int(round(86400.0 / cadence))
    requested_days = len(state["days"])
    complete_days = statuses.get("complete", 0)
    accepted = frame["accepted"].to_numpy(dtype=bool)
    edge = frame["edge_supported"].fillna(False).to_numpy(dtype=bool)
    fields = frame.loc[accepted, "effective_field"].to_numpy(dtype=float)
    ratios = frame.loc[accepted, "mirror_ratio"].to_numpy(dtype=float)
    ci_values = pd.to_numeric(
        frame.get("mirror_ratio_ci95_low", pd.Series(dtype=float)),
        errors="coerce",
    )
    energy_step = frame["energy_ratio_step_supported"].fillna(False).to_numpy(dtype=bool)
    missing_categories = Counter(
        _missing_category(str(value.get("message", "")))
        for value in state["days"].values()
        if isinstance(value, dict) and value.get("status") == "missing"
    )
    return {
        "validation_passed": not violations,
        "violations": violations,
        "dataset_id": dataset.get("dataset_id"),
        "variant": dataset.get("variant"),
        "requested_time": state.get("requested_time"),
        "cadence_seconds": cadence,
        "pitch_bins": dataset.get("parameters", {}).get("pitch_bins"),
        "profile_likelihood_enabled": dataset.get("parameters", {})
        .get("effective_field_fit", {})
        .get("profile_likelihood"),
        "profile_interval_rows": int(ci_values.notna().sum()),
        "days": {
            "requested": requested_days,
            "complete": complete_days,
            "missing": statuses.get("missing", 0),
            "no_data": statuses.get("no_data", 0),
            "failed": statuses.get("failed", 0),
            "terminal_fraction": sum(statuses.values()) / requested_days,
            "complete_fraction": complete_days / requested_days,
            "missing_categories": dict(sorted(missing_categories.items())),
        },
        "shards": int((shard_catalog["status"] == "complete").sum()),
        "fit_attempts": len(frame),
        "fit_success": int(frame["success"].fillna(False).sum()),
        "coverage": {
            "requested_slots": requested_days * slots_per_day,
            "complete_day_slots": complete_days * slots_per_day,
            "fraction_of_requested_slots": len(frame) / (requested_days * slots_per_day),
            "fraction_within_complete_days": len(frame) / (complete_days * slots_per_day),
        },
        "selection": {
            "edge_supported": int(np.count_nonzero(edge)),
            "edge_supported_fraction": float(np.mean(edge)),
            "good": int(frame["quality_grade"].astype(str).eq("good").sum()),
            "review": int(frame["quality_grade"].astype(str).eq("review").sum()),
            "poor": int(frame["quality_grade"].astype(str).eq("poor").sum()),
            "reject": int(frame["quality_grade"].astype(str).eq("reject").sum()),
            "accepted": int(np.count_nonzero(accepted)),
            "accepted_fraction": float(np.mean(accepted)),
            "accepted_without_energy_step": int(np.count_nonzero(accepted & ~energy_step)),
            "accepted_with_energy_step": int(np.count_nonzero(accepted & energy_step)),
        },
        "effective_field_nT": _distribution(fields),
        "mirror_ratio": _distribution(ratios),
        "monthly": tables["monthly"].to_dict("records"),
        "svm": svm_summary,
        "svm3d": svm3d_summary,
        "visual_audit": audit_summary,
    }


def _distribution(values: np.ndarray) -> dict[str, Any]:
    finite = values[np.isfinite(values)]
    return {
        "n": int(finite.size),
        "p10": _finite_percentile(finite, 10.0),
        "median": _finite_percentile(finite, 50.0),
        "p90": _finite_percentile(finite, 90.0),
        "p99": _finite_percentile(finite, 99.0),
    }


def _expected_days(requested: dict[str, Any]) -> set[str]:
    return {
        value.strftime("%Y-%m-%d")
        for value in pd.date_range(
            pd.Timestamp(requested["start"]),
            pd.Timestamp(requested["stop"]),
            freq="D",
            inclusive="left",
        )
    }


def _cadence_seconds(dataset: dict[str, Any]) -> float:
    value = dataset.get("parameters", {}).get("sampling_cadence_seconds")
    cadence = float(value)
    if not np.isfinite(cadence) or cadence <= 0.0:
        raise ValueError("Dataset sampling cadence must be finite and positive")
    return cadence


def _missing_category(message: str) -> str:
    if "ESA1" in message or "PACE" in message:
        return "pace"
    if "LMAG" in message or "MAG_TS" in message:
        return "lmag"
    if "SPICE" in message or "kernel" in message:
        return "spice"
    return "other"


def _finite_percentile(values: np.ndarray, percentile: float) -> float:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    return float(np.percentile(finite, percentile)) if finite.size else float("nan")


def _max_abs(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    return float(np.max(np.abs(finite))) if finite.size else 0.0


def _write_figures(tables: dict[str, pd.DataFrame], output: Path) -> None:
    import matplotlib.pyplot as plt

    monthly = tables["monthly"]
    x = np.arange(len(monthly))
    fig, left = plt.subplots(figsize=(11.5, 4.8), constrained_layout=True)
    left.bar(x, monthly["attempts"], color="#7b8794", label="fit attempts")
    left.set_ylabel("Fit attempts")
    left.set_xticks(x, monthly["month"], rotation=55, ha="right")
    right = left.twinx()
    right.plot(
        x,
        100.0 * monthly["accepted_fraction"],
        color="#b23a48",
        marker="o",
        linewidth=1.8,
        label="good + review",
    )
    right.fill_between(
        x,
        100.0 * monthly["wilson95_low"],
        100.0 * monthly["wilson95_high"],
        color="#b23a48",
        alpha=0.18,
    )
    right.set_ylabel("Accepted fraction [%]")
    left.set_title("KAGUYA ER full-period coverage and accepted fraction")
    fig.savefig(output / "monthly-coverage-and-selection.png", dpi=170)
    plt.close(fig)

    panels = [("sza", "SZA bin"), ("total_counts", "Count quantile stratum")]
    if "svm_bins" in tables:
        panels.append(("svm_bins", "Tsunakawa SVM quintile"))
    fig, axes = plt.subplots(
        1,
        len(panels),
        figsize=(4.6 * len(panels), 4.2),
        constrained_layout=True,
    )
    axes_array = np.atleast_1d(axes)
    for axis, (name, title) in zip(axes_array, panels, strict=True):
        table = tables[name]
        labels = table["group"].astype(str)
        positions = np.arange(len(table))
        rate = 100.0 * table["accepted_fraction"]
        lower = rate - 100.0 * table["wilson95_low"]
        upper = 100.0 * table["wilson95_high"] - rate
        axis.errorbar(
            positions,
            rate,
            yerr=np.vstack((lower, upper)),
            color="#176b87",
            marker="o",
            capsize=3,
        )
        axis.set_xticks(positions, labels, rotation=35, ha="right")
        axis.set_ylabel("Accepted fraction [%]")
        axis.set_title(title)
        axis.grid(axis="y", alpha=0.25)
    fig.suptitle("KAGUYA ER selection function")
    fig.savefig(output / "selection-function.png", dpi=170)
    plt.close(fig)

    if "svm_correlations" in tables:
        _write_svm_cell_figure(
            tables["spatial_cells"],
            output / "svm-comparison.png",
            title="Radial-subpoint SVM comparison (descriptive, not a footpoint match)",
        )
        if "straight_footpoint_spatial_cells" in tables:
            _write_svm_cell_figure(
                tables["straight_footpoint_spatial_cells"],
                output / "svm-straight-footpoint-comparison.png",
                title="Straight-local-footpoint SVM comparison (spherical surface)",
            )
    if "svm3d_curved_traces" in tables:
        _write_svm3d_curved_figure(
            tables["svm3d_curved_traces"],
            output / "svm3d-curved-field-validation.png",
        )


def _write_svm_cell_figure(
    cells: pd.DataFrame,
    path: Path,
    *,
    title: str,
) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.5), constrained_layout=True)
    coverage = cells["attempts"].to_numpy(dtype=float)
    axes[0].scatter(
        cells["median_svm_surface_field_nT"],
        100.0 * cells["accepted_fraction"],
        s=np.clip(np.sqrt(coverage) * 3.0, 8.0, 80.0),
        alpha=0.65,
        color="#287271",
    )
    axes[0].set_xscale("symlog", linthresh=1.0)
    axes[0].set_xlabel("Median Tsunakawa SVM field [nT]")
    axes[0].set_ylabel("Accepted fraction [%]")
    axes[0].set_title("20-degree cells: selection")
    field_mask = cells["accepted"].to_numpy(dtype=int) >= 3
    axes[1].scatter(
        cells.loc[field_mask, "median_svm_surface_field_nT"],
        cells.loc[field_mask, "median_effective_field_nT"],
        s=np.clip(
            np.sqrt(cells.loc[field_mask, "accepted"].to_numpy(dtype=float)) * 8.0,
            10.0,
            90.0,
        ),
        alpha=0.65,
        color="#b45f06",
    )
    axes[1].set_xscale("symlog", linthresh=1.0)
    axes[1].set_yscale("log")
    axes[1].set_xlabel("Median Tsunakawa SVM field [nT]")
    axes[1].set_ylabel("Median effective field [nT]")
    axes[1].set_title("20-degree cells: field magnitude")
    fig.suptitle(title)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def _write_svm3d_curved_figure(traces: pd.DataFrame, path: Path) -> None:
    import matplotlib.pyplot as plt

    accepted = traces["quality_grade"].astype(str).isin(ACCEPTED_GRADES).to_numpy()
    observed = traces["mirror_ratio"].to_numpy(dtype=float)
    predicted = traces["preferred_model_mirror_ratio"].to_numpy(dtype=float)
    valid = accepted & np.isfinite(observed) & np.isfinite(predicted) & (observed > 0.0) & (
        predicted > 0.0
    )
    preferred_altitude = traces.loc[
        accepted & traces["preferred_target_crossed"].to_numpy(dtype=bool),
        "preferred_target_altitude_km",
    ].to_numpy(dtype=float)
    opposite_altitude = traces.loc[
        accepted & traces["opposite_target_crossed"].to_numpy(dtype=bool),
        "opposite_target_altitude_km",
    ].to_numpy(dtype=float)
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.6), constrained_layout=True)
    if np.any(valid):
        axes[0].hexbin(
            observed[valid],
            predicted[valid],
            xscale="log",
            yscale="log",
            bins="log",
            gridsize=45,
            mincnt=1,
            cmap="viridis",
        )
        limits = [
            min(float(np.min(observed[valid])), float(np.min(predicted[valid]))),
            max(float(np.max(observed[valid])), float(np.max(predicted[valid]))),
        ]
        axes[0].plot(limits, limits, color="#b23a48", linestyle="--", linewidth=1.2)
    axes[0].set_xlabel("Fitted mirror ratio B_eff / B_sc")
    axes[0].set_ylabel("SVM3D path maximum / B_sc")
    axes[0].set_title("Preferred backtrace branch")
    finite_altitude = np.concatenate(
        (
            preferred_altitude[np.isfinite(preferred_altitude)],
            opposite_altitude[np.isfinite(opposite_altitude)],
        )
    )
    if finite_altitude.size:
        lower = max(0.0, float(np.floor(np.min(finite_altitude) / 5.0) * 5.0))
        upper = max(lower + 5.0, float(np.ceil(np.max(finite_altitude) / 5.0) * 5.0))
    else:
        lower, upper = 0.0, 200.0
    bins = np.linspace(lower, upper, 41)
    if np.any(np.isfinite(preferred_altitude)):
        axes[1].hist(
            preferred_altitude[np.isfinite(preferred_altitude)],
            bins=bins,
            histtype="step",
            linewidth=1.8,
            label="preferred branch",
            color="#176b87",
        )
    if np.any(np.isfinite(opposite_altitude)):
        axes[1].hist(
            opposite_altitude[np.isfinite(opposite_altitude)],
            bins=bins,
            histtype="step",
            linewidth=1.5,
            label="opposite branch",
            color="#b45f06",
        )
    axes[1].set_xlabel("Derived B_eff crossing altitude [km]")
    axes[1].set_ylabel("Accepted rows")
    axes[1].set_title("Target-derived candidate mirror points")
    if finite_altitude.size:
        axes[1].legend()
    fig.suptitle("KAGUYA ER curved SVM3D field-line diagnostic")
    fig.savefig(path, dpi=170)
    plt.close(fig)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a complete KAGUYA electron-reflectometry archive",
    )
    parser.add_argument("variant", type=Path)
    parser.add_argument("--svm", type=Path)
    parser.add_argument("--svm3d-shell", type=Path)
    parser.add_argument("--svm3d-source", type=Path)
    parser.add_argument("--svm3d-accuracy-samples", type=int, default=64)
    parser.add_argument("--svm3d-step-km", type=float, default=1.0)
    parser.add_argument("--svm3d-max-steps", type=int, default=1000)
    parser.add_argument("--svm3d-stop-altitude-km", type=float, default=6.05)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--figure-output", type=Path)
    parser.add_argument("--spatial-bin-degrees", type=float, default=20.0)
    parser.add_argument("--allow-violations", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = validate_effective_field_archive(
        args.variant,
        svm_path=args.svm,
        svm3d_shell_path=args.svm3d_shell,
        svm3d_source_path=args.svm3d_source,
        svm3d_accuracy_samples=args.svm3d_accuracy_samples,
        svm3d_trace_settings=SVM3DTraceSettings(
            step_km=args.svm3d_step_km,
            max_steps=args.svm3d_max_steps,
            stop_altitude_km=args.svm3d_stop_altitude_km,
        ),
        audit_path=args.audit,
        spatial_bin_degrees=args.spatial_bin_degrees,
        strict=not args.allow_violations,
    )
    result.write(args.output, figure_output=args.figure_output)
    print(json.dumps(_jsonable(result.summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
