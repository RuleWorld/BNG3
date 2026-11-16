import numpy as np

from scripts.ci import validate_sbml_test_suite as suite


def test_mismatch_samples_preserve_times_values_and_bound():
    times = np.arange(20, dtype=float)
    samples = suite._mismatch_samples(times, times + 1, times, tolerance=0.5)
    assert len(samples) == 16
    assert samples[0] == {"index": 0, "time": 0.0, "bng3": 1.0, "libroadrunner": 0.0}
    assert samples[-1]["index"] == 15


def test_mismatch_samples_distinguish_nonfinite_classes():
    samples = suite._mismatch_samples(
        np.array([0.0, 1.0, 2.0]),
        np.array([np.nan, np.inf, -np.inf]),
        np.array([np.nan, -np.inf, 2.0]),
        tolerance=0.0,
    )
    assert samples == [
        {"index": 1, "time": 1.0, "bng3": "+inf", "libroadrunner": "-inf"},
        {"index": 2, "time": 2.0, "bng3": "-inf", "libroadrunner": 2.0},
    ]
