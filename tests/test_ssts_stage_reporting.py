"""Keep conversion, round-trip and numerical evidence independently visible."""

import numpy as np

from scripts.ci import validate_sbml_test_suite as runner


def test_later_numerical_failure_does_not_erase_successful_conversion():
    record = {
        "status": "failed",
        "generated_network": {"species": 2, "reactions": 1},
        "native_reader": {"success": True},
        "roundtrip_passed": True,
        "simulation_comparison": {"passed": False, "error": "mismatch"},
        "official_conformance": {"status": "failed"},
    }
    stages = runner._stage_summary([record])
    assert stages["conversion"] == {"passed": 1}
    assert stages["roundtrip_structure"] == {"passed": 1}
    assert stages["independent_comparison"] == {"failed": 1}
    assert stages["official_reference"] == {"failed": 1}


def test_declined_conversion_does_not_count_downstream_as_executed():
    record = {
        "status": "unsupported",
        "simulation_comparison": {"passed": False, "skipped": True},
        "official_conformance": {"status": "unsupported"},
    }
    stages = runner._stage_summary([record])
    assert stages["conversion"] == {"unsupported": 1}
    assert stages["roundtrip_structure"] == {"not-tested": 1}
    assert stages["independent_comparison"] == {"not-tested": 1}


def test_roundtrip_failure_is_separate_from_passing_official_reference():
    record = {
        "status": "failed",
        "generated_network": {"species": 2, "reactions": 1},
        "native_reader": {"success": False},
        "official_conformance": {"status": "passed"},
    }
    stages = runner._stage_summary([record])
    assert stages["conversion"] == {"passed": 1}
    assert stages["roundtrip_structure"] == {"failed": 1}
    assert stages["independent_comparison"] == {"not-tested": 1}
    assert stages["official_reference"] == {"passed": 1}


def test_mismatch_samples_preserve_times_values_and_bound():
    times = np.arange(20, dtype=float)
    samples = runner._mismatch_samples(times, times + 1, times, tolerance=0.5)
    assert len(samples) == 16
    assert samples[0] == {"index": 0, "time": 0.0, "bng3": 1.0, "libroadrunner": 0.0}
    assert samples[-1]["index"] == 15


def test_mismatch_samples_distinguish_nonfinite_classes():
    samples = runner._mismatch_samples(
        np.array([0.0, 1.0, 2.0]),
        np.array([np.nan, np.inf, -np.inf]),
        np.array([np.nan, -np.inf, 2.0]),
        tolerance=0.0,
    )
    assert samples == [
        {"index": 1, "time": 1.0, "bng3": "+inf", "libroadrunner": "-inf"},
        {"index": 2, "time": 2.0, "bng3": "-inf", "libroadrunner": 2.0},
    ]
