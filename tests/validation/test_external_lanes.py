from tests.validation import external_lanes
import pytest


def test_import_success_does_not_imply_official_sbml_conformance():
    rows = external_lanes.sbml_results(
        {
            "records": [
                {
                    "id": "1",
                    "category": "semantic",
                    "status": "passed",
                    "official_conformance": {
                        "status": "unsupported",
                        "reason": "dynamic stoichiometry",
                    },
                }
            ]
        }
    )
    official = next(r for r in rows if r["stage"] == "official-conformance")
    assert official["status"] == "UNSUPPORTED"
    assert "dynamic stoichiometry" in official["detail"]


def test_unknown_or_missing_official_status_is_harness_error():
    rows = external_lanes.sbml_results(
        {"records": [{"id": "1", "category": "semantic", "status": "passed"}]}
    )
    assert any(
        r["stage"] == "official-conformance" and r["status"] == "HARNESS_ERROR"
        for r in rows
    )


def test_benchmark_error_cannot_pass_even_when_script_exits_zero():
    rows = external_lanes.benchmark_results(
        {"models": [{"model": "bad", "status": "error", "error": "missing engine"}]}
    )
    assert rows[0]["status"] == "FAIL"


def test_cross_engine_stage_not_attempted_after_unsupported_import():
    rows = external_lanes.sbml_results(
        {
            "records": [
                {
                    "id": "1",
                    "category": "semantic",
                    "status": "unsupported",
                    "official_conformance": {"status": "unsupported"},
                }
            ]
        }
    )
    cross = next(r for r in rows if r["stage"] == "cross-engine-simulation")
    assert cross["status"] == "NOT_TESTED"


def test_skipped_false_simulation_is_not_tested_not_a_failure():
    rows = external_lanes.sbml_results(
        {
            "records": [
                {
                    "id": "7",
                    "category": "semantic",
                    "status": "unsupported",
                    "simulation_comparison": {
                        "passed": False,
                        "skipped": True,
                        "reason": "dynamic event semantics are unsupported",
                    },
                }
            ]
        }
    )
    simulation = next(r for r in rows if r["stage"] == "cross-engine-simulation")
    assert simulation["status"] == "NOT_TESTED"
    assert "dynamic event semantics" in simulation["detail"]


def test_ssts_official_statuses_keep_timeout_invalid_source_and_pending_distinct():
    rows = external_lanes.sbml_results(
        {
            "records": [
                {
                    "id": "1",
                    "category": "semantic",
                    "official_conformance": {
                        "status": "timed-out",
                        "reason": "solver deadline",
                    },
                },
                {
                    "id": "2",
                    "category": "semantic",
                    "official_conformance": {
                        "status": "invalid-source",
                        "reason": "bad settings CSV",
                    },
                },
                {
                    "id": "3",
                    "category": "semantic",
                    "official_conformance": {
                        "status": "pending",
                        "reason": "not attempted",
                    },
                },
            ]
        }
    )
    official = {
        r["id"].split(":")[2]: r for r in rows if r["stage"] == "official-conformance"
    }
    assert official["1"]["status"] == "TIMEOUT"
    assert official["2"]["status"] == "INVALID_INPUT"
    assert official["3"]["status"] == "NOT_TESTED"


def test_biomodels_stage_rows_do_not_infer_conversion_or_simulation_pass():
    rows = external_lanes.biomodel_results(
        {
            "source_provenance": {"bng3_commit": "abc"},
            "runtime_provenance": {"native_extension_sha256": "native-digest"},
            "records": [
                {
                    "id": "BIOMD1",
                    "status": "passed",
                    "modes": [
                        {
                            "mode": "flat",
                            "status": "passed",
                            "simulation_comparison": {
                                "passed": False,
                                "skipped": True,
                                "reason": "unsupported dynamic rule",
                            },
                        },
                        {
                            "mode": "atomized",
                            "status": "timeout",
                            "error": "worker deadline",
                        },
                    ],
                }
            ],
        }
    )
    assert not any(r["stage"] == "conversion" and r["status"] == "PASS" for r in rows)
    flat_sim = next(
        r for r in rows if r["id"].endswith(":flat:cross-engine-simulation")
    )
    assert flat_sim["status"] == "NOT_TESTED"
    atomized = next(
        r for r in rows if ":atomized:" in r["id"] and r["stage"] == "mode-execution"
    )
    assert atomized["status"] == "TIMEOUT"


def test_unknown_present_external_status_is_harness_error():
    rows = external_lanes.biomodel_results(
        {"records": [{"id": "BIOMD2", "modes": [{"mode": "flat", "status": "maybe"}]}]}
    )
    assert any(r["status"] == "HARNESS_ERROR" for r in rows)


@pytest.mark.parametrize(
    "value",
    [
        {"passed": False, "status": "passed"},
        {"passed": True, "status": "failed"},
        {"passed": "false"},
        {"passed": True, "skipped": True},
        {"passed": False, "skipped": "true"},
        [],
    ],
)
def test_external_comparison_rejects_malformed_or_contradictory_flags(value):
    rows = external_lanes.sbml_results(
        {
            "records": [
                {
                    "id": "1",
                    "category": "semantic",
                    "simulation_comparison": value,
                    "official_conformance": {"status": "passed"},
                }
            ]
        }
    )
    assert (
        next(r for r in rows if r["stage"] == "cross-engine-simulation")["status"]
        == "HARNESS_ERROR"
    )


@pytest.mark.parametrize(
    "network",
    [{}, {"species": True, "reactions": 1}, {"species": -1, "reactions": 1}, []],
)
def test_external_conversion_requires_nonnegative_integer_network_counts(network):
    rows = external_lanes.sbml_results(
        {
            "records": [
                {
                    "id": "1",
                    "category": "semantic",
                    "generated_network": network,
                    "official_conformance": {"status": "passed"},
                }
            ]
        }
    )
    assert (
        next(r for r in rows if r["stage"] == "conversion")["status"] == "HARNESS_ERROR"
    )


def test_external_unknown_record_status_is_not_discarded():
    rows = external_lanes.sbml_results(
        {
            "records": [
                {
                    "id": "1",
                    "category": "semantic",
                    "status": "maybe",
                    "official_conformance": {"status": "passed"},
                }
            ]
        }
    )
    assert any(r["status"] == "HARNESS_ERROR" for r in rows)
