from tests.validation import external_lanes


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
