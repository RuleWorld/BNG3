"""Regression coverage for comparing named native observables."""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "benchmarks")
)

from gpu.equivalence import compare_runs


def test_compare_runs_orders_named_observables_by_reported_names():
    result_a = {
        "observable_names": ["A", "B"],
        "observable_means": {"A": [0.0, 1.0], "B": [10.0, 10.0]},
        "observable_stds": {"A": [0.0, 1.0], "B": [0.0, 0.0]},
        "final_observables": [[0.0, 10.0], [1.0, 10.0], [0.0, 10.0]],
        "batch_size": 3,
    }
    result_b = {
        "observable_names": ["A", "B"],
        "observable_means": {"B": [10.0, 10.0], "A": [0.0, 1.0]},
        "observable_stds": {"B": [0.0, 0.0], "A": [0.0, 1.0]},
        "final_observables": [[0.0, 10.0], [1.0, 10.0], [0.0, 10.0]],
        "batch_size": 3,
    }

    report = compare_runs(result_a, result_b)

    assert report.passed
    assert report.z_cells == 4
    assert [item["observable"] for item in report.ks_results] == ["A", "B"]


def test_compare_runs_aligns_final_columns_by_observable_name():
    host = {
        "observable_names": ["A", "B"],
        "observable_means": {"A": [1.0], "B": [10.0]},
        "observable_stds": {"A": [0.0], "B": [0.0]},
        "final_observables": [[1.0, 10.0], [2.0, 20.0]],
        "batch_size": 2,
    }
    device = {
        "observable_names": ["B", "A"],
        "observable_means": {"B": [10.0], "A": [1.0]},
        "observable_stds": {"B": [0.0], "A": [0.0]},
        "final_observables": [[10.0, 1.0], [20.0, 2.0]],
        "batch_size": 2,
    }

    report = compare_runs(host, device)

    assert report.passed
    assert [item["observable"] for item in report.ks_results] == ["A", "B"]
    assert all(item["statistic"] == 0.0 for item in report.ks_results)


def test_compare_runs_rejects_final_observable_batch_shape_mismatch():
    result = {
        "observable_names": ["A"],
        "observable_means": {"A": [0.0, 1.0]},
        "observable_stds": {"A": [0.0, 1.0]},
        "final_observables": [[0.0], [1.0]],
        "batch_size": 2,
    }
    malformed = {**result, "final_observables": [[0.0]], "batch_size": 2}

    report = compare_runs(result, malformed)

    assert not report.passed
    assert "final_observables has 1 rows for batch_size=2" in report.notes[0]


def test_compare_runs_rejects_missing_named_observable():
    result = {
        "observable_names": ["A", "B"],
        "observable_means": {"A": [0.0], "B": [1.0]},
        "observable_stds": {"A": [0.0], "B": [0.0]},
        "final_observables": [[0.0, 1.0], [0.0, 1.0]],
        "batch_size": 2,
    }
    malformed = {
        **result,
        "observable_means": {"A": [0.0]},
    }

    report = compare_runs(result, malformed)

    assert not report.passed
    assert "missing observables: ['B']" in report.notes[0]


def test_compare_runs_rejects_inconsistent_time_grid_shapes():
    result = {
        "observable_names": ["A"],
        "observable_means": {"A": [0.0, 1.0]},
        "observable_stds": {"A": [0.0, 1.0]},
        "final_observables": [[0.0], [1.0]],
        "batch_size": 2,
    }
    malformed = {
        **result,
        "observable_means": {"A": [0.0]},
    }

    report = compare_runs(result, malformed)

    assert not report.passed
    assert "time-grid lengths differ" in report.notes[0]
