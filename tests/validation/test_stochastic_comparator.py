"""Regression tests for strict stochastic-ensemble comparison."""

from __future__ import annotations

import numpy as np

from tests.validation.compare import compare_stochastic


def _run(value: float, columns: list[str] | None = None):
    return (
        np.asarray([[0.0, value], [1.0, value]], dtype=float),
        columns or ["time", "A"],
    )


def test_single_reference_trajectory_is_not_an_ensemble():
    diff = compare_stochastic([_run(1.0)], [_run(1.0), _run(1.0)])
    assert not diff.ok
    assert diff.n_points_checked == 0
    assert "insufficient ensemble members" in diff.note


def test_comparator_requires_consistent_members():
    diff = compare_stochastic(
        [_run(1.0), _run(1.0)],
        [_run(1.0), _run(1.0, ["time", "B"])],
    )
    assert not diff.ok
    assert diff.n_points_checked == 0
    assert diff.note == "empty ensemble"


def test_matching_fixed_seed_ensembles_pass():
    reference = [_run(1.0), _run(2.0)]
    test = [_run(1.0), _run(2.0)]
    diff = compare_stochastic(reference, test, min_ref_runs=2, min_test_runs=2)
    assert diff.ok
    assert diff.n_points_checked == 2


def test_independent_ensemble_errors_are_pooled():
    reference = [_run(0.0), _run(0.0)]
    test = [_run(0.0), _run(1.0)]

    diff = compare_stochastic(reference, test, min_ref_runs=2, min_test_runs=2)

    # The reference ensemble has zero variance, but the independent test
    # ensemble supplies the uncertainty for its nonzero sample mean.
    assert diff.ok
