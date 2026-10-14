from tests.validation import reporting


def test_similar_failures_are_hypotheses_not_confirmed_causes():
    rows = [
        {
            "id": name,
            "model": name,
            "stage": "network",
            "status": "FAIL",
            "detail": "reaction count 10 differs",
            "capabilities": ["network.expansion"],
        }
        for name in ("a", "b")
    ]
    groups = reporting.cluster_failures(rows)
    assert len(groups) == 1
    assert groups[0]["diagnosis_confidence"] == "signature-only"
    assert groups[0]["confirmed_root_cause"] is None
    assert len(groups[0]["cases"]) == 2


def test_history_does_not_call_deselected_failure_resolved():
    old = {
        "comparison_key": "same",
        "results": [{"id": "a", "status": "FAIL"}, {"id": "b", "status": "FAIL"}],
    }
    new = {"comparison_key": "same", "results": [{"id": "a", "status": "PASS"}]}
    change = reporting.history(new, old)
    assert change["resolved"] == ["a"]
    assert change["no_longer_executed"] == ["b"]
    new["comparison_key"] = "changed-corpus"
    assert reporting.history(new, old)["comparable"] is False


def test_one_passing_test_never_qualifies_whole_capability():
    cap = {
        "id": "x",
        "coverage": "NOT_TESTED",
        "existing_tests": ["tests/python/test_model.py"],
        "missing_tests": ["semantic oracle"],
    }
    rows = [{"id": "unit:tests.python.test_model::test_one", "status": "PASS"}]
    reporting.attach_coverage([cap], rows)
    assert cap["coverage"] == "PARTIAL"
    assert cap["missing_tests"] == ["semantic oracle"]
    assert cap["result_counts"]["PASS"] == 1
