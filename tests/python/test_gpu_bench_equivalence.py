"""Regression coverage for comparing named native observables."""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmarks"))

from gpu.equivalence import compare_runs, moment_test


def test_compare_runs_orders_named_observables_by_reported_names():
    result_a = {
        "observable_names": ["A", "B"],
        "observable_means": {"A": [0.0, 1.0], "B": [10.0, 10.0]},
        "observable_stds": {"A": [0.0, 1.0], "B": [0.0, 0.0]},
        "final_observables": [[0.0, 10.0], [1.0, 10.0], [0.0, 10.0]],
        "batch_size": 3,
        "time": [0.0, 1.0],
    }
    result_b = {
        "observable_names": ["A", "B"],
        "observable_means": {"B": [10.0, 10.0], "A": [0.0, 1.0]},
        "observable_stds": {"B": [0.0, 0.0], "A": [0.0, 1.0]},
        "final_observables": [[0.0, 10.0], [1.0, 10.0], [0.0, 10.0]],
        "batch_size": 3,
        "time": [0.0, 1.0],
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
        "time": [0.0],
    }
    device = {
        "observable_names": ["B", "A"],
        "observable_means": {"B": [10.0], "A": [1.0]},
        "observable_stds": {"B": [0.0], "A": [0.0]},
        "final_observables": [[10.0, 1.0], [20.0, 2.0]],
        "batch_size": 2,
        "time": [0.0],
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
        "time": [0.0, 1.0],
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
        "time": [0.0, 1.0],
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
        "time": [0.0, 1.0],
    }
    malformed = {
        **result,
        "observable_means": {"A": [0.0]},
    }

    report = compare_runs(result, malformed)

    assert not report.passed
    assert "time-grid lengths differ" in report.notes[0]


def test_compare_runs_rejects_different_reported_time_points():
    result = {
        "observable_names": ["A"],
        "observable_means": {"A": [0.0, 1.0, 2.0]},
        "observable_stds": {"A": [0.0, 1.0, 1.2]},
        "final_observables": [[2.0]] * 10,
        "batch_size": 10,
        "time": [0.0, 1.0, 2.0],
    }
    comparison = {**result, "time": [0.0, 0.5, 2.0]}

    report = compare_runs(result, comparison)

    assert not report.passed
    assert "reported time points differ" in report.notes[0]


def test_compare_runs_rejects_distinct_near_zero_time_points():
    result = {
        "observable_names": ["A"],
        "observable_means": {"A": [0.0, 1.0]},
        "observable_stds": {"A": [0.0, 1.0]},
        "final_observables": [[0.0], [1.0]],
        "batch_size": 2,
        "time": [0.0, 1e-10],
    }
    comparison = {**result, "time": [0.0, 1e-9]}

    report = compare_runs(result, comparison)

    assert not report.passed
    assert "reported time points differ" in report.notes[0]


def test_compare_runs_accepts_float32_rounding_in_same_time_grid():
    result = {
        "observable_names": ["A"],
        "observable_means": {"A": [0.0, 1.0, 2.0]},
        "observable_stds": {"A": [0.0, 1.0, 1.2]},
        "final_observables": [[2.0]] * 10,
        "batch_size": 10,
        "time": [0.0, 1.0 / 3.0, 2.0 / 3.0],
    }
    comparison = {
        **result,
        "time": [0.0, float("0.3333333432674408"), float("0.6666666865348816")],
    }

    report = compare_runs(result, comparison)

    assert report.passed


def test_compare_runs_rejects_a_missing_time_grid():
    result = {
        "observable_names": ["A"],
        "observable_means": {"A": [0.0, 1.0]},
        "observable_stds": {"A": [0.0, 1.0]},
        "final_observables": [[0.0], [1.0]],
        "batch_size": 2,
        "time": [0.0, 1.0],
    }
    comparison = {key: value for key, value in result.items() if key != "time"}

    report = compare_runs(result, comparison)

    assert not report.passed
    assert "reported time grid is absent" in report.notes[0]


def test_compare_runs_rejects_a_time_grid_that_does_not_cover_statistics():
    result = {
        "observable_names": ["A"],
        "observable_means": {"A": [0.0, 1.0]},
        "observable_stds": {"A": [0.0, 1.0]},
        "final_observables": [[0.0], [1.0]],
        "batch_size": 2,
        "time": [0.0],
    }

    report = compare_runs(result, result)

    assert not report.passed
    assert (
        "reported time-grid length differs from observable statistics"
        in report.notes[0]
    )


def test_compare_runs_rejects_missing_final_observables_on_both_sides():
    result = {
        "observable_names": ["A"],
        "observable_means": {"A": [0.0, 1.0]},
        "observable_stds": {"A": [0.0, 1.0]},
        "batch_size": 2,
        "time": [0.0, 1.0],
    }

    report = compare_runs(result, result)

    assert not report.passed
    assert "final_observables is absent" in report.notes[0]


def test_compare_runs_rejects_infinite_standard_deviation_hiding_mean_error():
    host = {
        "observable_names": ["A"],
        "observable_means": {"A": [0.0]},
        "observable_stds": {"A": [1.0]},
        "final_observables": [[0.0], [0.0]],
        "batch_size": 2,
        "time": [0.0],
    }
    device = {
        **host,
        "observable_means": {"A": [1e30]},
        "observable_stds": {"A": [float("inf")]},
    }

    report = compare_runs(host, device)

    assert not report.passed
    assert "non-finite" in report.notes[0]


def test_compare_runs_rejects_nonfinite_mean_statistics():
    result = {
        "observable_names": ["A"],
        "observable_means": {"A": [float("nan")]},
        "observable_stds": {"A": [1.0]},
        "final_observables": [[0.0], [0.0]],
        "batch_size": 2,
        "time": [0.0],
    }

    report = compare_runs(result, result)

    assert not report.passed
    assert "non-finite" in report.notes[0]


def test_compare_runs_does_not_overflow_large_standard_errors():
    host = {
        "observable_names": ["A"],
        "observable_means": {"A": [0.0]},
        "observable_stds": {"A": [1e200]},
        "final_observables": [[0.0], [0.0]],
        "batch_size": 2,
        "time": [0.0],
    }
    device = {
        **host,
        "observable_means": {"A": [1e201]},
    }

    report = compare_runs(host, device)

    assert not report.passed
    assert report.max_abs_z > report.z_threshold


def test_compare_runs_does_not_underflow_small_standard_errors():
    host = {
        "observable_names": ["A"],
        "observable_means": {"A": [0.0]},
        "observable_stds": {"A": [1e-200]},
        "final_observables": [[0.0], [0.0]],
        "batch_size": 2,
        "time": [0.0],
    }
    device = {
        **host,
        "observable_means": {"A": [1e-200]},
    }

    report = compare_runs(host, device)

    assert report.passed
    assert report.max_abs_z < report.z_threshold


def test_compare_runs_rejects_negative_standard_deviation():
    result = {
        "observable_names": ["A"],
        "observable_means": {"A": [0.0]},
        "observable_stds": {"A": [-1.0]},
        "final_observables": [[0.0], [0.0]],
        "batch_size": 2,
        "time": [0.0],
    }

    report = compare_runs(result, result)

    assert not report.passed
    assert "negative standard deviation" in report.notes[0]


def test_moment_test_reports_zero_variance_ratio_without_raising():
    report = moment_test([0.0, 2.0], [1.0, 1.0])

    assert report["variance_ratio"] == 0.0
    assert report["shape_flag"] is True


def test_compare_runs_rejects_nan_final_values_without_hanging():
    code = """
import json
from gpu.equivalence import compare_runs
result = {
    'observable_names': ['A'],
    'observable_means': {'A': [0.0]},
    'observable_stds': {'A': [1.0]},
    'final_observables': [[float('nan')], [1.0]],
    'batch_size': 2,
    'time': [0.0],
}
report = compare_runs(result, result)
print('PASS' if report.passed else 'FAIL')
"""
    env = dict(os.environ)
    benchmarks = str(Path(__file__).resolve().parents[2] / "benchmarks")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (benchmarks, env.get("PYTHONPATH", "")) if part
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )

    assert result.stdout.strip() == "FAIL"
