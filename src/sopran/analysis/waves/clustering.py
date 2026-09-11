"""Exploratory clustering of background and narrow-band wave structure.

The integer cluster identifiers produced here are local to one fitted run.  They
are deliberately stored together with ``cluster_run_id`` and must not be treated
as physical-phenomenon or noise labels.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any

import numpy as np

ALGORITHM_VERSION = "sopran.wave.background-residual-clustering.v1"


@dataclass(frozen=True)
class BackgroundResidualClusteringConfig:
    """Configuration for deterministic background-residual clustering."""

    smoothing_bins: int = 9
    background_components: int = 3
    residual_trim_fraction: float = 0.10
    residual_components: int = 8
    n_clusters: int = 8
    seed: int = 0
    n_init: int = 8
    max_iterations: int = 300
    tolerance: float = 1.0e-6

    def __post_init__(self) -> None:
        if self.smoothing_bins < 1 or self.smoothing_bins % 2 == 0:
            raise ValueError("smoothing_bins must be a positive odd integer")
        if self.background_components < 1:
            raise ValueError("background_components must be at least one")
        if not 0.0 <= self.residual_trim_fraction < 1.0:
            raise ValueError("residual_trim_fraction must be in [0, 1)")
        if self.residual_components < 1:
            raise ValueError("residual_components must be at least one")
        if self.n_clusters < 2:
            raise ValueError("n_clusters must be at least two")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise ValueError("seed must be an integer")
        if self.n_init < 1:
            raise ValueError("n_init must be at least one")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least one")
        if not np.isfinite(self.tolerance) or self.tolerance <= 0.0:
            raise ValueError("tolerance must be positive and finite")


@dataclass(frozen=True)
class PcaMetadata:
    """A fitted PCA transform; components are rows in input-feature space."""

    mean: np.ndarray
    components: np.ndarray
    explained_variance: np.ndarray
    explained_variance_ratio: np.ndarray


@dataclass(frozen=True)
class ScalerMetadata:
    """Column-wise standardization applied before K-means."""

    mean: np.ndarray
    scale: np.ndarray


@dataclass(frozen=True)
class MissingValueMetadata:
    """Deterministic fill values used for non-finite input samples."""

    fill_value_by_frequency: np.ndarray
    all_missing_frequency: np.ndarray
    missing_count: int


@dataclass(frozen=True)
class ResidualTrimMetadata:
    """One-sided, per-frequency upper-tail winsorization metadata."""

    fraction: float
    upper_threshold_by_frequency: np.ndarray


@dataclass(frozen=True)
class ClusterAssignments:
    """Run-scoped exploratory identifiers, one per input window.

    ``cluster_id`` has no meaning without ``cluster_run_id``.  In particular,
    its values do not denote noise or a named physical phenomenon.
    """

    cluster_run_id: str
    cluster_id: np.ndarray


@dataclass(frozen=True)
class BackgroundResidualClusteringResult:
    """Fitted transforms, K-means state, and run-scoped assignments."""

    assignments: ClusterAssignments
    config: BackgroundResidualClusteringConfig
    config_hash: str
    algorithm_version: str
    input_shape: tuple[int, int]
    feature_names: tuple[str, ...]
    features: np.ndarray
    centroids: np.ndarray
    scaler: ScalerMetadata
    background_pca: PcaMetadata
    residual_pca: PcaMetadata
    residual_trim: ResidualTrimMetadata
    missing_values: MissingValueMetadata
    inertia: float
    iterations: int

    @property
    def cluster_run_id(self) -> str:
        """Return the namespace of ``assignments.cluster_id``."""

        return self.assignments.cluster_run_id


def clustering_config_hash(config: BackgroundResidualClusteringConfig) -> str:
    """Return the stable SHA-256 hash of the complete fit configuration."""

    payload = json.dumps(
        {
            "algorithm": ALGORITHM_VERSION,
            "configuration": asdict(config),
        },
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def fit_background_residual_clustering(
    normalized_z: np.ndarray,
    config: BackgroundResidualClusteringConfig | None = None,
) -> BackgroundResidualClusteringResult:
    """Fit an exploratory background-residual partition.

    Parameters
    ----------
    normalized_z:
        Two-dimensional ``(windows, frequency)`` normalized-z spectra.  Non-finite
        values are deterministically imputed and the fill metadata is retained.
    config:
        Complete preprocessing, PCA, and deterministic K-means configuration.

    Notes
    -----
    The processing sequence is rolling median, background PCA, residual upper-tail
    trimming, residual PCA, standardization, and K-means.  "Trimming" is implemented
    as one-sided winsorization independently in each frequency bin so that the PCA
    input remains rectangular.
    """

    fit_config = config or BackgroundResidualClusteringConfig()
    values = np.asarray(normalized_z, dtype=np.float64)
    _validate_input(values, fit_config)

    filled, finite_mask, missing_metadata = _impute_non_finite(values)
    smoothed = _rolling_median(filled, fit_config.smoothing_bins)

    background_scores, background_pca = _fit_pca(
        smoothed, fit_config.background_components
    )
    background = background_pca.mean + background_scores @ background_pca.components
    residual = filled - background

    residual_for_pca, residual_trim = _trim_residual_upper_tail(
        residual, fit_config.residual_trim_fraction
    )
    residual_scores, residual_pca = _fit_pca(
        residual_for_pca, fit_config.residual_components
    )

    combined = np.column_stack((background_scores, residual_scores))
    standardized, scaler = _standardize(combined)
    cluster_id, centroids, inertia, iterations = _fit_kmeans(standardized, fit_config)

    config_hash = clustering_config_hash(fit_config)
    cluster_run_id = _cluster_run_id(filled, finite_mask, config_hash)
    feature_names = tuple(
        [f"background_pc_{index + 1}" for index in range(background_scores.shape[1])]
        + [f"residual_pc_{index + 1}" for index in range(residual_scores.shape[1])]
    )

    return BackgroundResidualClusteringResult(
        assignments=ClusterAssignments(
            cluster_run_id=cluster_run_id,
            cluster_id=_read_only(cluster_id, dtype=np.int64),
        ),
        config=fit_config,
        config_hash=config_hash,
        algorithm_version=ALGORITHM_VERSION,
        input_shape=(int(values.shape[0]), int(values.shape[1])),
        feature_names=feature_names,
        features=_read_only(standardized),
        centroids=_read_only(centroids),
        scaler=scaler,
        background_pca=background_pca,
        residual_pca=residual_pca,
        residual_trim=residual_trim,
        missing_values=missing_metadata,
        inertia=float(inertia),
        iterations=int(iterations),
    )


def _validate_input(
    values: np.ndarray, config: BackgroundResidualClusteringConfig
) -> None:
    if values.ndim != 2:
        raise ValueError("normalized_z must have shape (windows, frequency)")
    n_windows, n_frequency = values.shape
    if n_windows == 0 or n_frequency == 0:
        raise ValueError("normalized_z must contain at least one window and frequency bin")
    if config.n_clusters > n_windows:
        raise ValueError("n_clusters must not exceed the number of windows")
    if not np.isfinite(values).any():
        raise ValueError("normalized_z must contain at least one finite value")


def _impute_non_finite(
    values: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, MissingValueMetadata]:
    finite = np.isfinite(values)
    fill_values = np.zeros(values.shape[1], dtype=np.float64)
    all_missing = np.empty(values.shape[1], dtype=bool)
    for frequency_index in range(values.shape[1]):
        column_values = values[finite[:, frequency_index], frequency_index]
        all_missing[frequency_index] = column_values.size == 0
        if column_values.size:
            fill_values[frequency_index] = float(np.median(column_values))

    filled = np.where(finite, values, fill_values[np.newaxis, :])
    metadata = MissingValueMetadata(
        fill_value_by_frequency=_read_only(fill_values),
        all_missing_frequency=_read_only(all_missing, dtype=bool),
        missing_count=int((~finite).sum()),
    )
    return np.ascontiguousarray(filled), finite, metadata


def _rolling_median(values: np.ndarray, width: int) -> np.ndarray:
    half_width = width // 2
    smoothed = np.empty_like(values)
    for frequency_index in range(values.shape[1]):
        start = max(0, frequency_index - half_width)
        stop = min(values.shape[1], frequency_index + half_width + 1)
        smoothed[:, frequency_index] = np.median(values[:, start:stop], axis=1)
    return smoothed


def _fit_pca(values: np.ndarray, requested_components: int) -> tuple[np.ndarray, PcaMetadata]:
    mean = np.mean(values, axis=0)
    centered = values - mean
    _, singular_values, right_vectors = np.linalg.svd(centered, full_matrices=False)
    component_count = min(requested_components, right_vectors.shape[0])
    components = right_vectors[:component_count].copy()

    # SVD vectors have an arbitrary sign.  Fix it at the largest-magnitude loading
    # so serialized metadata and feature scores remain reproducible.
    for component in components:
        pivot = int(np.argmax(np.abs(component)))
        if component[pivot] < 0.0:
            component *= -1.0

    scores = centered @ components.T
    denominator = max(values.shape[0] - 1, 1)
    explained_variance = singular_values[:component_count] ** 2 / denominator
    total_variance = float(np.sum(singular_values**2) / denominator)
    if total_variance > 0.0:
        explained_variance_ratio = explained_variance / total_variance
    else:
        explained_variance_ratio = np.zeros_like(explained_variance)

    metadata = PcaMetadata(
        mean=_read_only(mean),
        components=_read_only(components),
        explained_variance=_read_only(explained_variance),
        explained_variance_ratio=_read_only(explained_variance_ratio),
    )
    return scores, metadata


def _trim_residual_upper_tail(
    residual: np.ndarray, fraction: float
) -> tuple[np.ndarray, ResidualTrimMetadata]:
    if fraction == 0.0:
        upper_threshold = np.max(residual, axis=0)
        trimmed = residual.copy()
    else:
        upper_threshold = np.quantile(residual, 1.0 - fraction, axis=0)
        trimmed = np.minimum(residual, upper_threshold[np.newaxis, :])
    metadata = ResidualTrimMetadata(
        fraction=float(fraction),
        upper_threshold_by_frequency=_read_only(upper_threshold),
    )
    return trimmed, metadata


def _standardize(values: np.ndarray) -> tuple[np.ndarray, ScalerMetadata]:
    mean = np.mean(values, axis=0)
    scale = np.std(values, axis=0)
    scale = np.where(scale > 0.0, scale, 1.0)
    standardized = (values - mean) / scale
    metadata = ScalerMetadata(mean=_read_only(mean), scale=_read_only(scale))
    return standardized, metadata


def _fit_kmeans(
    values: np.ndarray, config: BackgroundResidualClusteringConfig
) -> tuple[np.ndarray, np.ndarray, float, int]:
    random = np.random.default_rng(config.seed)
    best: tuple[np.ndarray, np.ndarray, float, int] | None = None

    for _ in range(config.n_init):
        centroids = _initialize_kmeans_plus_plus(values, config.n_clusters, random)
        labels = np.zeros(values.shape[0], dtype=np.int64)
        iterations = config.max_iterations
        for iteration in range(1, config.max_iterations + 1):
            squared_distance = _squared_distances(values, centroids)
            labels = np.argmin(squared_distance, axis=1).astype(np.int64, copy=False)
            updated = _updated_centroids(values, labels, centroids)
            shift = float(np.max(np.linalg.norm(updated - centroids, axis=1)))
            centroids = updated
            if shift <= config.tolerance:
                iterations = iteration
                break

        squared_distance = _squared_distances(values, centroids)
        labels = np.argmin(squared_distance, axis=1).astype(np.int64, copy=False)
        inertia = float(np.sum(squared_distance[np.arange(values.shape[0]), labels]))
        labels, centroids = _canonicalize_cluster_ids(labels, centroids)
        candidate = (labels, centroids, inertia, iterations)
        if best is None or inertia < best[2]:
            best = candidate

    if best is None:  # pragma: no cover - n_init validation makes this unreachable
        raise RuntimeError("K-means did not run")
    return best


def _initialize_kmeans_plus_plus(
    values: np.ndarray, n_clusters: int, random: np.random.Generator
) -> np.ndarray:
    n_windows, n_features = values.shape
    centroids = np.empty((n_clusters, n_features), dtype=np.float64)
    selected: list[int] = []
    first = int(random.integers(0, n_windows))
    selected.append(first)
    centroids[0] = values[first]
    closest_squared = _squared_distances(values, centroids[:1])[:, 0]

    for cluster_index in range(1, n_clusters):
        total = float(np.sum(closest_squared))
        if total > 0.0 and np.isfinite(total):
            target = float(random.random()) * total
            point_index = int(np.searchsorted(np.cumsum(closest_squared), target, side="right"))
            point_index = min(point_index, n_windows - 1)
        else:
            point_index = next(
                (index for index in range(n_windows) if index not in selected), selected[0]
            )
        selected.append(point_index)
        centroids[cluster_index] = values[point_index]
        new_squared = _squared_distances(values, centroids[cluster_index : cluster_index + 1])[
            :, 0
        ]
        closest_squared = np.minimum(closest_squared, new_squared)
    return centroids


def _updated_centroids(
    values: np.ndarray, labels: np.ndarray, previous: np.ndarray
) -> np.ndarray:
    updated = np.empty_like(previous)
    occupied = np.zeros(previous.shape[0], dtype=bool)
    for cluster_index in range(previous.shape[0]):
        members = labels == cluster_index
        if np.any(members):
            updated[cluster_index] = np.mean(values[members], axis=0)
            occupied[cluster_index] = True

    if np.all(occupied):
        return updated

    occupied_centroids = updated[occupied]
    if occupied_centroids.size:
        distance_to_occupied = np.min(_squared_distances(values, occupied_centroids), axis=1)
    else:  # pragma: no cover - at least one label is always occupied
        distance_to_occupied = np.zeros(values.shape[0], dtype=np.float64)
    available = np.ones(values.shape[0], dtype=bool)
    for empty_index in np.flatnonzero(~occupied):
        cluster_index = int(empty_index)
        candidates = np.where(available, distance_to_occupied, -np.inf)
        point_index = int(np.argmax(candidates))
        updated[cluster_index] = values[point_index]
        available[point_index] = False
    return updated


def _squared_distances(values: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    difference = values[:, np.newaxis, :] - centroids[np.newaxis, :, :]
    squared: np.ndarray = np.sum(difference * difference, axis=2)
    return squared


def _canonicalize_cluster_ids(
    labels: np.ndarray, centroids: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    keys = tuple(centroids[:, index] for index in range(centroids.shape[1] - 1, -1, -1))
    order = np.lexsort(keys)
    old_to_new = np.empty(order.size, dtype=np.int64)
    old_to_new[order] = np.arange(order.size, dtype=np.int64)
    return old_to_new[labels], centroids[order]


def _cluster_run_id(
    filled: np.ndarray, finite_mask: np.ndarray, config_hash: str
) -> str:
    digest = sha256()
    digest.update(ALGORITHM_VERSION.encode("ascii"))
    digest.update(config_hash.encode("ascii"))
    digest.update(np.asarray(filled.shape, dtype="<i8").tobytes())
    digest.update(np.ascontiguousarray(finite_mask, dtype=np.uint8).tobytes())
    digest.update(np.ascontiguousarray(filled, dtype="<f8").tobytes())
    return f"wave-cluster-{digest.hexdigest()[:24]}"


def _read_only(values: Any, *, dtype: Any | None = None) -> np.ndarray:
    array = np.array(values, dtype=dtype, copy=True)
    array.setflags(write=False)
    return array


__all__ = [
    "ALGORITHM_VERSION",
    "BackgroundResidualClusteringConfig",
    "BackgroundResidualClusteringResult",
    "ClusterAssignments",
    "MissingValueMetadata",
    "PcaMetadata",
    "ResidualTrimMetadata",
    "ScalerMetadata",
    "clustering_config_hash",
    "fit_background_residual_clustering",
]
