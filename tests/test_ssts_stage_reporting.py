"""Keep conversion, round-trip and numerical evidence independently visible."""

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
