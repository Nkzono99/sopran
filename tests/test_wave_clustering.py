from __future__ import annotations

import numpy as np
import pytest

from sopran.analysis.waves.clustering import (
    ALGORITHM_VERSION,
    BackgroundResidualClusteringConfig,
    fit_background_residual_clustering,
)


def _synthetic_spectra(*, seed: int = 91) -> np.ndarray:
    random = np.random.default_rng(seed)
    n_windows = 60
    n_frequency = 32
    frequency = np.linspace(-1.0, 1.0, n_frequency)
    spectra = random.normal(0.0, 0.12, size=(n_windows, n_frequency))
    groups = np.arange(n_windows) % 3
    spectra += (groups[:, np.newaxis] - 1.0) * 0.45 * frequency[np.newaxis, :]
    spectra[groups == 0, 5:7] += 2.0
    spectra[groups == 1, 15:18] += 1.5
    spectra[groups == 2, 25:27] += 2.2
    return spectra


def _config(**overrides: object) -> BackgroundResidualClusteringConfig:
    values: dict[str, object] = {
        "n_clusters": 3,
        "seed": 17,
        "n_init": 5,
    }
    values.update(overrides)
    return BackgroundResidualClusteringConfig(**values)  # type: ignore[arg-type]


def test_fit_retains_shapes_transforms_and_run_scoped_cluster_ids() -> None:
    spectra = _synthetic_spectra()

    result = fit_background_residual_clustering(spectra, _config())

    assert result.algorithm_version == ALGORITHM_VERSION
    assert result.input_shape == (60, 32)
    assert result.features.shape == (60, 11)
    assert result.centroids.shape == (3, 11)
    assert result.scaler.mean.shape == (11,)
    assert result.scaler.scale.shape == (11,)
    assert result.background_pca.mean.shape == (32,)
    assert result.background_pca.components.shape == (3, 32)
    assert result.background_pca.explained_variance.shape == (3,)
    assert result.residual_pca.mean.shape == (32,)
    assert result.residual_pca.components.shape == (8, 32)
    assert result.residual_trim.upper_threshold_by_frequency.shape == (32,)
    assert len(result.feature_names) == 11
    assert len(result.config_hash) == 64
    assert result.cluster_run_id == result.assignments.cluster_run_id
    assert result.cluster_run_id.startswith("wave-cluster-")
    assert result.assignments.cluster_id.shape == (60,)
    assert result.assignments.cluster_id.dtype == np.int64
    assert np.all((result.assignments.cluster_id >= 0) & (result.assignments.cluster_id < 3))

    # Cluster numbers are exploratory names in one explicit run namespace, not
    # standalone noise or physical-phenomenon labels.
    assert not hasattr(result, "noise_label")
    assert not hasattr(result, "phenomenon_label")


def test_fit_is_reproducible_for_identical_data_and_config() -> None:
    spectra = _synthetic_spectra()
    config = _config()

    first = fit_background_residual_clustering(spectra, config)
    second = fit_background_residual_clustering(spectra.copy(), config)

    assert first.config_hash == second.config_hash
    assert first.cluster_run_id == second.cluster_run_id
    np.testing.assert_array_equal(first.assignments.cluster_id, second.assignments.cluster_id)
    np.testing.assert_array_equal(first.features, second.features)
    np.testing.assert_array_equal(first.centroids, second.centroids)
    assert first.inertia == second.inertia
    assert first.iterations == second.iterations


def test_cluster_run_id_scopes_ids_to_data_and_complete_fit_config() -> None:
    spectra = _synthetic_spectra()
    baseline = fit_background_residual_clustering(spectra, _config())

    changed_data = spectra.copy()
    changed_data[0, 0] += 0.001
    data_result = fit_background_residual_clustering(changed_data, _config())
    seed_result = fit_background_residual_clustering(spectra, _config(seed=18))

    assert baseline.cluster_run_id != data_result.cluster_run_id
    assert baseline.config_hash == data_result.config_hash
    assert baseline.cluster_run_id != seed_result.cluster_run_id
    assert baseline.config_hash != seed_result.config_hash


def test_non_finite_values_are_imputed_and_recorded() -> None:
    spectra = _synthetic_spectra()
    spectra[2, 4] = np.nan
    spectra[8, 9] = np.inf
    spectra[12, :] = np.nan
    spectra[:, 30] = np.nan

    result = fit_background_residual_clustering(spectra, _config())

    assert result.missing_values.missing_count == 93
    assert result.missing_values.all_missing_frequency.shape == (32,)
    assert result.missing_values.all_missing_frequency[30]
    assert result.missing_values.fill_value_by_frequency[30] == 0.0
    assert np.all(np.isfinite(result.features))
    assert np.all(np.isfinite(result.centroids))
    assert np.all(np.isfinite(result.background_pca.components))
    assert np.all(np.isfinite(result.residual_pca.components))
    assert result.assignments.cluster_id.shape == (60,)


def test_invalid_shapes_and_unusable_values_fail_clearly() -> None:
    with pytest.raises(ValueError, match="shape"):
        fit_background_residual_clustering(np.ones(8), _config())
    with pytest.raises(ValueError, match="at least one window"):
        fit_background_residual_clustering(np.empty((0, 8)), _config())
    with pytest.raises(ValueError, match="at least one finite"):
        fit_background_residual_clustering(np.full((8, 10), np.nan), _config())
    with pytest.raises(ValueError, match="must not exceed"):
        fit_background_residual_clustering(np.ones((2, 10)), _config(n_clusters=3))


def test_configuration_rejects_ambiguous_or_non_deterministic_settings() -> None:
    with pytest.raises(ValueError, match="positive odd"):
        BackgroundResidualClusteringConfig(smoothing_bins=8)
    with pytest.raises(ValueError, match=r"\[0, 1\)"):
        BackgroundResidualClusteringConfig(residual_trim_fraction=1.0)
    with pytest.raises(ValueError, match="seed must be an integer"):
        BackgroundResidualClusteringConfig(seed=True)
