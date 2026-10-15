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


def test_task_packets_are_leaf_failures_with_replay_and_bounded_acceptance(tmp_path):
    report = {
        "source": {"revision": "abc"},
        "subject": {"binary": "/bng_cpp"},
        "configuration": {},
        "references": {},
        "results": [
            {
                "id": "m:network",
                "stage": "bounded-network",
                "status": "FAIL",
                "aggregate": True,
            },
            {
                "id": "m:network:initial-amounts",
                "model": "m",
                "check": "initial-amounts",
                "stage": "network.initial-amounts",
                "status": "FAIL",
                "detail": "S 100 versus 200",
                "related_issues": [140],
                "source_locations": ["cpp/actions/ActionDispatch.cpp"],
                "evidence": ["reference.net", "subject.net"],
            },
        ],
    }
    tasks = reporting.investigation_tasks(report, tmp_path)
    assert len(tasks) == 1
    task = tasks[0]
    assert task["case_id"] == "m:network:initial-amounts"
    assert task["confirmed_root_cause"] is None
    assert task["source_revision"] == "abc"
    assert "initial-amounts" in task["acceptance_criteria"][0]
    assert "--models" in task["reproduce_command"]
    assert "m" in task["reproduce_command"]
    assert task["related_issues"] == [140]
    assert task["evidence"] == ["reference.net", "subject.net"]
