"""Spacecraft-potential proxies from PACE energy spectra (diagnostic quality).

The proxies are spectral edges, not a plasma-physics solution of the charging
balance. The adoption rules follow the 2026-05 lunarsat trials:

* ESA ``falling`` edge on the day side: the spacecraft photoelectron boundary,
  ``V_sc = +E_edge`` (V).
* ESA ``rising`` edge on the night side: a cold-electron cutoff under the
  negative-spacecraft assumption, ``V_sc = -E_edge``.
* IMA/IEA low-energy ion peaks are diagnostics only. In a five-day comparison
  they kept a systematic offset of about ``-57 V`` relative to the ESA
  proxies, so ``use_ion_proxies`` defaults to ``False``.

Precision is bounded by the ESA energy resolution and by the ``min_*``
thresholds; the estimate has not been validated against an independent
potential measurement over the mission. Treat ``vsc_est_V`` as a correction
candidate with its ``vsc_sigma_V``, never as a measured potential.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]
METHOD_ID = "pace_spectral_edge_potential_v1"
PROXY_SOURCES_DAYSIDE = ("esa2_falling_photoelectron", "esa1_falling_photoelectron")
PROXY_SOURCES_NIGHTSIDE = ("esa2_rising", "esa1_rising", "ima_ion_peak", "iea_ion_peak")


@dataclass(frozen=True)
class CutoffSettings:
    """Thresholds of the electron edge finder (lunarsat defaults)."""

    edge_min_eV: float = 5.0
    edge_max_eV: float = 350.0
    low_reference_max_eV: float = 30.0
    high_reference_min_eV: float = 80.0
    min_positive_bins: int = 5
    min_pair_counts: float = 2.0
    min_edge_contrast_log10: float = 0.25
    min_profile_contrast_log10: float = 0.35
    threshold_fraction: float = 0.5


@dataclass(frozen=True)
class IonPeakSettings:
    """Thresholds of the low-energy ion peak finder (lunarsat defaults)."""

    min_energy_eV: float = 5.0
    max_energy_eV: float = 1000.0
    low_reference_max_eV: float = 120.0
    high_reference_min_eV: float = 400.0
    min_positive_bins: int = 3
    min_total_counts: float = 20.0
    min_low_fraction: float = 0.35
    min_profile_contrast_log10: float = 0.25


@dataclass(frozen=True)
class PotentialEstimateSettings:
    """How proxies are matched to events and gap-filled."""

    direct_tolerance_seconds: float = 60.0
    smooth_window_seconds: float = 1800.0
    gapfill_max_gap_seconds: float = 3600.0
    global_prior_V: float = 0.0
    global_sigma_V: float = 60.0
    use_dayside_photoelectron: bool = True
    use_ion_proxies: bool = False
    dayside_sza_max_deg: float = 80.0
    nightside_sza_min_deg: float = 120.0
    sza_bin_deg: float = 20.0
    prior_min_rows: int = 3

    def metadata(self) -> dict[str, Any]:
        return {"method_id": METHOD_ID, **asdict(self)}


def cutoff_features(
    energy_eV: ArrayLike,
    counts: ArrayLike,
    eflux: ArrayLike | None = None,
    *,
    settings: CutoffSettings | None = None,
) -> dict[str, np.ndarray]:
    """Edge features per spectrum row; ``counts``/``eflux`` are ``(records, energy)``."""

    selected = settings or CutoffSettings()
    energy, count_values, flux_values = _spectrum_matrices(energy_eV, counts, eflux)
    native = _native_module("infer_low_energy_cutoff")
    raw = native.infer_low_energy_cutoff(
        energy,
        count_values,
        flux_values,
        float(selected.edge_min_eV),
        float(selected.edge_max_eV),
        float(selected.low_reference_max_eV),
        float(selected.high_reference_min_eV),
        int(selected.min_positive_bins),
        float(selected.min_pair_counts),
        float(selected.min_edge_contrast_log10),
        float(selected.min_profile_contrast_log10),
        float(selected.threshold_fraction),
    )
    out = {name: np.asarray(values) for name, values in raw.items()}
    out["fit_success"] = out["fit_success"].astype(bool)
    out["quality"] = out["quality"].astype(bool)
    direction = np.where(out["fit_success"], out["direction_code"].astype(int), 0)
    out["edge_direction"] = np.where(
        direction > 0, "rising", np.where(direction < 0, "falling", "none")
    )
    out["signal_units"] = np.where(
        out["signal_units_code"].astype(int) == 1, "energy_flux", "counts"
    )
    return out


def ion_peak_features(
    energy_eV: ArrayLike,
    counts: ArrayLike,
    eflux: ArrayLike | None = None,
    *,
    settings: IonPeakSettings | None = None,
) -> dict[str, np.ndarray]:
    """Low-energy ion peak per spectrum row (diagnostic acceleration proxy)."""

    selected = settings or IonPeakSettings()
    energy, count_values, flux_values = _spectrum_matrices(energy_eV, counts, eflux)
    native = _native_module("infer_ion_energy_peak")
    raw = native.infer_ion_energy_peak(
        energy,
        count_values,
        flux_values,
        float(selected.min_energy_eV),
        float(selected.max_energy_eV),
        float(selected.low_reference_max_eV),
        float(selected.high_reference_min_eV),
        int(selected.min_positive_bins),
        float(selected.min_total_counts),
        float(selected.min_low_fraction),
        float(selected.min_profile_contrast_log10),
    )
    out = {name: np.asarray(values) for name, values in raw.items()}
    out["fit_success"] = out["fit_success"].astype(bool)
    return out


def energy_spectra(dataset: Any) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray | None]:
    """Look-summed ``(times_unix, energy_eV, counts, energy_flux)`` from a PACE xarray dataset."""

    counts = dataset["counts"]
    summed = counts.sum("look", skipna=True) if "look" in counts.dims else counts
    times = (
        np.asarray(summed.coords["time"].values, dtype="datetime64[ns]")
        .astype("int64")
        .astype(float)
        / 1e9
    )
    energy_values = np.asarray(summed.coords["energy"].values, dtype=float)
    energy = np.broadcast_to(energy_values, (times.size, energy_values.size)).astype(float).copy()
    count_matrix = np.asarray(summed.values, dtype=float)
    flux_matrix: FloatArray | None = None
    if "energy_flux" in dataset:
        flux = dataset["energy_flux"]
        if "look" in flux.dims:
            flux = flux.mean("look", skipna=True)
        flux_matrix = np.asarray(flux.values, dtype=float)
    return times, energy, count_matrix, flux_matrix


def cutoff_table(
    times_unix: ArrayLike,
    features: Mapping[str, np.ndarray],
    *,
    sensor: str,
    sza_deg: ArrayLike | None = None,
) -> pl.DataFrame:
    """Polars table of edge features with one row per record (optionally with the SZA)."""

    times = np.asarray(times_unix, dtype=float)
    columns: dict[str, Any] = {
        "time_unix": times,
        "sensor": np.full(times.size, sensor.upper(), dtype=object),
        "method_id": np.full(times.size, METHOD_ID, dtype=object),
    }
    if sza_deg is not None:
        columns["sza_deg"] = np.asarray(sza_deg, dtype=float)
    for name, values in features.items():
        if name in {"direction_code", "signal_units_code"}:
            continue
        columns[name] = values
    return pl.DataFrame(columns)


def proxy_table(
    cutoff: pl.DataFrame,
    *,
    use_dayside_photoelectron: bool = True,
) -> pl.DataFrame:
    """Convert quality ESA edges into potential proxies with the adoption rules."""

    if cutoff.is_empty():
        return _empty_proxies()
    quality = cutoff.filter(pl.col("quality"))
    if quality.is_empty():
        return _empty_proxies()
    sensor = pl.col("sensor").str.to_lowercase()
    energy = pl.col("cutoff_energy_eV").cast(pl.Float64)
    sza = (
        pl.col("sza_deg").cast(pl.Float64)
        if "sza_deg" in quality.columns
        else pl.lit(None, dtype=pl.Float64)
    )
    rising = quality.filter(pl.col("edge_direction") == "rising").select(
        pl.col("time_unix"),
        sza.alias("sza_deg"),
        pl.col("sensor"),
        (sensor + pl.lit("_rising")).alias("source"),
        pl.lit("nightside_negative_spacecraft_cutoff").alias("kind"),
        (-energy).alias("vsc_proxy_V"),
        (pl.lit(8.0) + energy.abs() * 0.20).alias("vsc_proxy_sigma_V"),
        pl.col("quality_score").cast(pl.Float64).alias("vsc_proxy_quality"),
        pl.lit(True).alias("use_for_estimate"),
        pl.lit("nightside").alias("valid_regime"),
    )
    falling = quality.filter(pl.col("edge_direction") == "falling").select(
        pl.col("time_unix"),
        sza.alias("sza_deg"),
        pl.col("sensor"),
        (sensor + pl.lit("_falling_photoelectron")).alias("source"),
        pl.lit("dayside_spacecraft_photoelectron_boundary").alias("kind"),
        energy.alias("vsc_proxy_V"),
        (pl.lit(10.0) + energy.abs() * 0.30).alias("vsc_proxy_sigma_V"),
        pl.col("quality_score").cast(pl.Float64).alias("vsc_proxy_quality"),
        pl.lit(bool(use_dayside_photoelectron)).alias("use_for_estimate"),
        pl.lit("dayside").alias("valid_regime"),
    )
    return pl.concat([rising, falling]).sort("time_unix")


def ion_proxy_table(
    times_unix: ArrayLike,
    features: Mapping[str, np.ndarray],
    *,
    sensor: str,
    use_for_estimate: bool = False,
    sza_deg: ArrayLike | None = None,
) -> pl.DataFrame:
    """Ion-peak proxies ``V_sc = -E_peak``; diagnostic unless explicitly enabled."""

    times = np.asarray(times_unix, dtype=float)
    success = np.asarray(features["fit_success"]).astype(bool)
    if not np.any(success):
        return _empty_proxies()
    peak = np.asarray(features["peak_energy_eV"], dtype=float)[success]
    proxy = -peak
    sza = (
        np.full(proxy.size, np.nan)
        if sza_deg is None
        else np.asarray(sza_deg, dtype=float)[success]
    )
    return pl.DataFrame(
        {
            "time_unix": times[success],
            "sza_deg": sza,
            "sensor": np.full(proxy.size, sensor.upper(), dtype=object),
            "source": np.full(proxy.size, f"{sensor.lower()}_ion_peak", dtype=object),
            "kind": np.full(proxy.size, "ion_energy_peak_diagnostic", dtype=object),
            "vsc_proxy_V": proxy,
            "vsc_proxy_sigma_V": np.maximum(20.0, np.abs(proxy) * 0.35),
            "vsc_proxy_quality": np.asarray(features["quality_score"], dtype=float)[success],
            "use_for_estimate": np.full(proxy.size, bool(use_for_estimate)),
            "valid_regime": np.full(proxy.size, "nightside", dtype=object),
        }
    ).sort("time_unix")


def potential_regime(
    sza_deg: ArrayLike, settings: PotentialEstimateSettings | None = None
) -> NDArray[np.str_]:
    """``dayside`` / ``terminator`` / ``nightside`` / ``unknown`` from the spacecraft SZA."""

    selected = settings or PotentialEstimateSettings()
    sza = np.asarray(sza_deg, dtype=float)
    regime = np.full(sza.shape, "unknown", dtype="<U10")
    regime[np.isfinite(sza) & (sza < selected.dayside_sza_max_deg)] = "dayside"
    regime[np.isfinite(sza) & (sza >= selected.nightside_sza_min_deg)] = "nightside"
    regime[
        np.isfinite(sza)
        & (sza >= selected.dayside_sza_max_deg)
        & (sza < selected.nightside_sza_min_deg)
    ] = "terminator"
    return regime


def estimate_potential(
    events: pl.DataFrame,
    proxies: pl.DataFrame,
    *,
    settings: PotentialEstimateSettings | None = None,
) -> pl.DataFrame:
    """Potential estimate per event from direct, time-smoothed and SZA-bin proxies.

    ``events`` needs ``time_unix`` and ``sza_deg``. The estimate takes the first
    available of: direct proxy within ``direct_tolerance_seconds`` (regime-matched
    sources in priority order), the rolling median of usable proxies within
    ``gapfill_max_gap_seconds``, the per-regime SZA-bin median, then the global
    prior. ``vsc_method`` records which one was used.
    """

    selected = settings or PotentialEstimateSettings()
    if "time_unix" not in events.columns or "sza_deg" not in events.columns:
        raise ValueError("events must have time_unix and sza_deg columns")
    base = events.with_columns(
        pl.Series("potential_regime", potential_regime(events["sza_deg"].to_numpy(), selected)),
        _sza_bin_expr(pl.col("sza_deg"), selected.sza_bin_deg).alias("sza_bin"),
    ).sort("time_unix")
    usable = proxies.filter(pl.col("use_for_estimate")) if not proxies.is_empty() else proxies
    if not selected.use_ion_proxies and not usable.is_empty():
        usable = usable.filter(~pl.col("kind").str.starts_with("ion_energy_peak"))
    if not selected.use_dayside_photoelectron and not usable.is_empty():
        usable = usable.filter(pl.col("valid_regime") != "dayside")
    sources = (*PROXY_SOURCES_DAYSIDE, *PROXY_SOURCES_NIGHTSIDE)
    out = base
    for source in sources:
        sub = usable.filter(pl.col("source") == source) if not usable.is_empty() else usable
        out = _join_direct(out, sub, source, selected.direct_tolerance_seconds)
    out = _join_smoothed(out, _smoothed_series(usable, selected), selected.gapfill_max_gap_seconds)
    out = _join_prior(out, _condition_priors(usable, selected))
    day_v = [f"{s}_proxy_V" for s in PROXY_SOURCES_DAYSIDE]
    night_v = [f"{s}_proxy_V" for s in PROXY_SOURCES_NIGHTSIDE]
    day_s = [f"{s}_sigma_V" for s in PROXY_SOURCES_DAYSIDE]
    night_s = [f"{s}_sigma_V" for s in PROXY_SOURCES_NIGHTSIDE]
    out = out.with_columns(
        pl.when(pl.col("potential_regime") == "dayside")
        .then(pl.coalesce([pl.col(c) for c in day_v]))
        .when(pl.col("potential_regime") == "nightside")
        .then(pl.coalesce([pl.col(c) for c in night_v]))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("vsc_direct_proxy_V"),
        pl.when(pl.col("potential_regime") == "dayside")
        .then(pl.coalesce([pl.col(c) for c in day_s]))
        .when(pl.col("potential_regime") == "nightside")
        .then(pl.coalesce([pl.col(c) for c in night_s]))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("vsc_direct_proxy_sigma_V"),
        pl.when(pl.col("potential_regime") == "dayside")
        .then(_first_source_expr(PROXY_SOURCES_DAYSIDE))
        .when(pl.col("potential_regime") == "nightside")
        .then(_first_source_expr(PROXY_SOURCES_NIGHTSIDE))
        .otherwise(pl.lit(None, dtype=pl.Utf8))
        .alias("vsc_direct_proxy_source"),
    )
    out = out.with_columns(
        pl.coalesce(
            [
                pl.col("vsc_direct_proxy_V"),
                pl.col("vsc_time_smooth_V"),
                pl.col("vsc_condition_prior_V"),
                pl.lit(float(selected.global_prior_V)),
            ]
        ).alias("vsc_est_V"),
        pl.coalesce(
            [
                pl.col("vsc_direct_proxy_sigma_V"),
                pl.col("vsc_time_smooth_sigma_V"),
                pl.col("vsc_condition_prior_sigma_V"),
                pl.lit(float(selected.global_sigma_V)),
            ]
        ).alias("vsc_sigma_V"),
        pl.when(pl.col("vsc_direct_proxy_V").is_not_null())
        .then(pl.lit("direct_proxy"))
        .when(pl.col("vsc_time_smooth_V").is_not_null())
        .then(pl.lit("time_smoothed_proxy"))
        .when(pl.col("vsc_condition_prior_V").is_not_null())
        .then(pl.lit("condition_prior"))
        .otherwise(pl.lit("global_prior"))
        .alias("vsc_method"),
    )
    return out


def _join_direct(
    events: pl.DataFrame, sub: pl.DataFrame, source: str, tolerance: float
) -> pl.DataFrame:
    if sub.is_empty():
        return events.with_columns(
            pl.lit(None, dtype=pl.Float64).alias(f"{source}_proxy_V"),
            pl.lit(None, dtype=pl.Float64).alias(f"{source}_sigma_V"),
            pl.lit(None, dtype=pl.Float64).alias(f"{source}_dt_seconds"),
        )
    columns = sub.sort("time_unix").select(
        pl.col("time_unix").alias(f"{source}_time_unix"),
        pl.col("vsc_proxy_V").alias(f"{source}_proxy_V"),
        pl.col("vsc_proxy_sigma_V").alias(f"{source}_sigma_V"),
    )
    return (
        events.sort("time_unix")
        .join_asof(
            columns,
            left_on="time_unix",
            right_on=f"{source}_time_unix",
            strategy="nearest",
            tolerance=float(tolerance),
        )
        .with_columns(
            (pl.col("time_unix") - pl.col(f"{source}_time_unix"))
            .abs()
            .alias(f"{source}_dt_seconds")
        )
        .drop(f"{source}_time_unix")
    )


def _smoothed_series(usable: pl.DataFrame, settings: PotentialEstimateSettings) -> pl.DataFrame:
    schema = {
        "potential_regime": pl.Utf8,
        "time_unix": pl.Float64,
        "vsc_time_smooth_V": pl.Float64,
        "vsc_time_smooth_sigma_V": pl.Float64,
    }
    if usable.is_empty():
        return pl.DataFrame(schema=schema)
    import pandas as pd

    pdf = usable.select(
        ["time_unix", "valid_regime", "vsc_proxy_V", "vsc_proxy_sigma_V"]
    ).to_pandas()
    rows: list[dict[str, Any]] = []
    window = f"{max(1, int(round(settings.smooth_window_seconds)))}s"
    for regime, group in pdf.sort_values("time_unix").groupby("valid_regime"):
        index = pd.to_datetime(group["time_unix"].to_numpy(dtype=float), unit="s", utc=True)
        values = pd.Series(group["vsc_proxy_V"].to_numpy(dtype=float), index=index)
        sigmas = pd.Series(group["vsc_proxy_sigma_V"].to_numpy(dtype=float), index=index)
        medians = values.rolling(window, center=True, min_periods=1).median().to_numpy(dtype=float)
        local = sigmas.rolling(window, center=True, min_periods=1).median().to_numpy(dtype=float)
        for t, median, sigma in zip(
            group["time_unix"].to_numpy(dtype=float), medians, local, strict=True
        ):
            if np.isfinite(median):
                rows.append(
                    {
                        "potential_regime": str(regime),
                        "time_unix": float(t),
                        "vsc_time_smooth_V": float(median),
                        "vsc_time_smooth_sigma_V": float(
                            max(10.0, sigma if np.isfinite(sigma) else 60.0)
                        ),
                    }
                )
    return pl.DataFrame(rows, schema=schema) if rows else pl.DataFrame(schema=schema)


def _join_smoothed(events: pl.DataFrame, smoothed: pl.DataFrame, tolerance: float) -> pl.DataFrame:
    if smoothed.is_empty():
        return events.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("vsc_time_smooth_V"),
            pl.lit(None, dtype=pl.Float64).alias("vsc_time_smooth_sigma_V"),
            pl.lit(None, dtype=pl.Float64).alias("vsc_time_smooth_dt_seconds"),
        )
    joined = (
        events.sort(["potential_regime", "time_unix"])
        .join_asof(
            smoothed.sort(["potential_regime", "time_unix"]).select(
                "potential_regime",
                pl.col("time_unix").alias("vsc_time_smooth_time_unix"),
                "vsc_time_smooth_V",
                "vsc_time_smooth_sigma_V",
            ),
            left_on="time_unix",
            right_on="vsc_time_smooth_time_unix",
            by="potential_regime",
            strategy="nearest",
            tolerance=float(tolerance),
        )
        .with_columns(
            (pl.col("time_unix") - pl.col("vsc_time_smooth_time_unix"))
            .abs()
            .alias("vsc_time_smooth_dt_seconds")
        )
        .drop("vsc_time_smooth_time_unix")
    )
    return joined.sort("time_unix")


def _condition_priors(usable: pl.DataFrame, settings: PotentialEstimateSettings) -> pl.DataFrame:
    schema = {
        "potential_regime": pl.Utf8,
        "sza_bin": pl.Utf8,
        "vsc_condition_prior_V": pl.Float64,
        "vsc_condition_prior_sigma_V": pl.Float64,
        "vsc_condition_prior_rows": pl.Int64,
    }
    if usable.is_empty() or "sza_deg" not in usable.columns:
        return pl.DataFrame(schema=schema)
    with_bins = usable.filter(pl.col("vsc_proxy_V").is_finite()).with_columns(
        _sza_bin_expr(pl.col("sza_deg"), settings.sza_bin_deg).alias("sza_bin"),
        pl.col("valid_regime").alias("potential_regime"),
    )
    if with_bins.is_empty():
        return pl.DataFrame(schema=schema)
    grouped = (
        with_bins.group_by(["potential_regime", "sza_bin"])
        .agg(
            pl.col("vsc_proxy_V").median().alias("vsc_condition_prior_V"),
            (
                1.4826 * (pl.col("vsc_proxy_V") - pl.col("vsc_proxy_V").median()).abs().median()
            ).alias("vsc_condition_prior_sigma_V"),
            pl.len().cast(pl.Int64).alias("vsc_condition_prior_rows"),
        )
        .filter(pl.col("vsc_condition_prior_rows") >= int(settings.prior_min_rows))
    )
    return grouped.select([pl.col(name).cast(dtype) for name, dtype in schema.items()])


def _join_prior(events: pl.DataFrame, priors: pl.DataFrame) -> pl.DataFrame:
    if priors.is_empty():
        return events.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("vsc_condition_prior_V"),
            pl.lit(None, dtype=pl.Float64).alias("vsc_condition_prior_sigma_V"),
            pl.lit(None, dtype=pl.Int64).alias("vsc_condition_prior_rows"),
        )
    return events.join(priors, on=["potential_regime", "sza_bin"], how="left")


def _first_source_expr(sources: Sequence[str]) -> pl.Expr:
    expr = pl.lit(None, dtype=pl.Utf8)
    for source in reversed(sources):
        expr = (
            pl.when(pl.col(f"{source}_proxy_V").is_not_null()).then(pl.lit(source)).otherwise(expr)
        )
    return expr


def _sza_bin_expr(value: pl.Expr, bin_deg: float) -> pl.Expr:
    width = float(bin_deg)
    lower = (value / width).floor() * width
    return (
        pl.when(value.is_null() | value.is_nan())
        .then(pl.lit("unknown"))
        .otherwise(
            lower.cast(pl.Int64).cast(pl.Utf8)
            + pl.lit("-")
            + (lower + width).cast(pl.Int64).cast(pl.Utf8)
        )
    )


def _empty_proxies() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "time_unix": pl.Float64,
            "sza_deg": pl.Float64,
            "sensor": pl.Utf8,
            "source": pl.Utf8,
            "kind": pl.Utf8,
            "vsc_proxy_V": pl.Float64,
            "vsc_proxy_sigma_V": pl.Float64,
            "vsc_proxy_quality": pl.Float64,
            "use_for_estimate": pl.Boolean,
            "valid_regime": pl.Utf8,
        }
    )


def _spectrum_matrices(
    energy_eV: ArrayLike, counts: ArrayLike, eflux: ArrayLike | None
) -> tuple[FloatArray, FloatArray, FloatArray]:
    count_values = np.ascontiguousarray(np.asarray(counts, dtype=float))
    if count_values.ndim == 1:
        count_values = count_values[None, :]
    if count_values.ndim != 2:
        raise ValueError("counts must have shape (records, energy)")
    energy = np.asarray(energy_eV, dtype=float)
    if energy.ndim == 1:
        energy = np.broadcast_to(energy, count_values.shape)
    energy = np.ascontiguousarray(energy, dtype=float)
    if energy.shape != count_values.shape:
        raise ValueError("energy_eV must be (energy,) or match the counts shape")
    if eflux is None:
        flux_values = np.full(count_values.shape, np.nan)
    else:
        flux_values = np.ascontiguousarray(np.asarray(eflux, dtype=float))
        if flux_values.ndim == 1:
            flux_values = flux_values[None, :]
        if flux_values.shape != count_values.shape:
            raise ValueError("eflux must match the counts shape")
    return energy, count_values, flux_values


def _native_module(function: str) -> Any:
    try:
        module = importlib.import_module("sopran._native")
    except ImportError as exc:
        raise RuntimeError(
            "The SOPRAN native extension is required for spectral edge features"
        ) from exc
    if not hasattr(module, function):
        raise RuntimeError(f"The installed SOPRAN native extension does not provide {function}")
    return module


__all__ = [
    "CutoffSettings",
    "IonPeakSettings",
    "METHOD_ID",
    "PotentialEstimateSettings",
    "cutoff_features",
    "cutoff_table",
    "energy_spectra",
    "estimate_potential",
    "ion_peak_features",
    "ion_proxy_table",
    "potential_regime",
    "proxy_table",
]
