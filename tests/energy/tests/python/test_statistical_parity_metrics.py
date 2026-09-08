from __future__ import annotations
from pathlib import Path
import numpy as np

from scripts import nf_energy_statistical_parity as parity


def test_identical_samples_pass_all_metrics():
    x = np.array([0, 1, 1, 2, 3, 5, 8, 13], dtype=float)
    m = parity.compare_point(x, x)
    assert m.passed
    assert m.pooled_se_z == 0.0
    assert m.paired_se_z == 0.0
    assert m.variance_ratio == 1.0
    assert m.tv == 0.0


def test_large_mean_shift_fails():
    rng = np.random.default_rng(1)
    a = rng.poisson(10, 4096)
    b = rng.poisson(20, 4096)
    m = parity.compare_point(a, b)
    assert not m.passed
    assert m.pooled_se_z > 5


def test_variance_shift_fails_even_with_matched_mean():
    rng = np.random.default_rng(2)
    a = rng.normal(0, 1, 4096)
    b = rng.normal(0, 2, 4096)
    m = parity.compare_point(a, b)
    assert not m.passed
    assert not (0.80 <= m.variance_ratio <= 1.25)


def test_tv_detects_distribution_shape_change():
    a = np.repeat([0, 2], 2048)
    b = np.repeat([1, 1], 2048)
    m = parity.compare_point(a, b)
    assert m.tv > 0.075
    assert not m.passed


def test_zero_variance_equal_is_well_defined():
    a = np.ones(32)
    m = parity.compare_point(a, a)
    assert m.variance_ratio == 1.0
    assert m.pooled_se_z == 0.0


def test_zero_variance_unequal_fails():
    a = np.zeros(32)
    b = np.ones(32)
    m = parity.compare_point(a, b)
    assert not m.passed
    assert np.isinf(m.pooled_se_z)


def test_trajectory_comparison_checks_every_time_and_observable():
    times = [0.0, 1.0, 2.0]
    a = {
        "A": np.array([[1, 2, 3], [1, 2, 3], [1, 2, 3]], float),
        "B": np.array([[0, 1, 1], [0, 1, 1], [0, 1, 1]], float),
    }
    metrics = parity.compare_trajectories(a, a, times)
    assert len(metrics) == 6
    assert all(m.passed for m in metrics)


def test_nonfinite_samples_are_rejected():
    import pytest

    with pytest.raises(ValueError, match="finite"):
        parity.compare_point([1.0, np.nan], [1.0, 2.0])


def test_single_seed_is_rejected_for_distributional_gate():
    import pytest

    with pytest.raises(ValueError, match="two seeds"):
        parity.compare_point([1.0], [1.0])


def test_small_support_uses_tv_shape_gate():
    x = np.tile(np.array([0, 1, 2, 3]), 256)
    m = parity.compare_point(x, x)
    assert m.shape_metric == "tv"
    assert m.tv == 0.0
    assert m.ks == 0.0


def test_broad_support_uses_ks_instead_of_sparse_empirical_tv():
    a = np.arange(1024, dtype=float)
    b = np.arange(1024, dtype=float)
    m = parity.compare_point(a, b)
    assert m.support_size > 32
    assert m.shape_metric == "ks"
    assert m.tv is None
    assert m.ks == 0.0


def test_ks_detects_broad_distribution_shift():
    a = np.arange(1024, dtype=float)
    b = np.arange(1024, dtype=float) + 500
    m = parity.compare_point(a, b)
    assert m.shape_metric == "ks"
    assert m.ks > 0.075
    assert not m.passed
