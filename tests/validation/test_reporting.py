from tests.validation import reporting
import pytest


def test_history_exposes_admission_failures_and_lost_coverage():
    old = {
        "comparison_key": "same",
        "results": [
            {"id": "admitted", "status": "UNSUPPORTED"},
            {"id": "supported", "status": "UNSUPPORTED"},
            {"id": "lost", "status": "PASS"},
            {"id": "missing", "status": "PASS"},
            {"id": "blocked", "status": "UNSUPPORTED"},
        ],
    }
    new = {
        "comparison_key": "same",
        "results": [
            {"id": "admitted", "status": "FAIL"},
            {"id": "supported", "status": "PASS"},
            {"id": "lost", "status": "NOT_TESTED"},
            {"id": "blocked", "status": "HARNESS_ERROR"},
        ],
    }
    change = reporting.history(new, old)
    assert change["newly_admitted_failures"] == ["admitted"]
    assert change["unsupported_to_supported"] == ["supported"]
    assert change["coverage_regressions"] == ["lost", "missing"]
    assert change["new_failures"] == []


def test_history_rejects_duplicate_leaf_identities_and_ignores_rollups():
    baseline = {"comparison_key": "same", "results": []}
    report = {
        "comparison_key": "same",
        "results": [{"id": "rollup", "status": "FAIL", "aggregate": True}],
    }
    assert reporting.history(report, baseline)["newly_executed"] == []
    report["results"] = [{"id": "duplicate", "status": "PASS"}] * 2
    with pytest.raises(ValueError, match="duplicate"):
        reporting.history(report, baseline)


def test_issue_coverage_keeps_closed_unmapped_and_unexecuted_issues_visible():
    capabilities = [
        {
            "id": "rates",
            "kind": "semantic-claim",
            "issues": [143],
            "existing_tests": ["tests/rates.py"],
            "evidence_ids": ["one", "blocked"],
            "missing_tests": ["independent local scopes"],
        },
        {
            "id": "scopes",
            "kind": "semantic-claim",
            "issues": [143],
            "existing_tests": ["tests/scopes.py"],
            "evidence_ids": [],
        },
    ]
    results = [
        {"id": "one", "status": "PASS", "related_issues": [143]},
        {"id": "blocked", "status": "NOT_TESTED", "related_issues": [143]},
        {"id": "suite", "status": "FAIL", "related_issues": [143], "aggregate": True},
    ]
    issues = [
        {"number": 143, "title": "Rates", "state": "CLOSED"},
        {"number": 162, "title": "Campaign", "state": "OPEN"},
    ]
    rows = reporting.issue_coverage(capabilities, results, issues)
    assert [row["number"] for row in rows] == [143, 162]
    rates, campaign = rows
    assert rates["coverage"] == "PARTIAL"
    assert rates["state"] == "CLOSED"
    assert rates["result_counts"] == {"PASS": 1, "NOT_TESTED": 1}
    assert rates["unexecuted_capabilities"] == ["scopes"]
    assert rates["remaining_qualification"] == {"rates": ["independent local scopes"]}
    assert campaign["coverage"] == "NOT_TESTED"
    assert campaign["capabilities"] == []


@pytest.mark.parametrize(
    "issues",
    [
        [{"number": True}],
        [{"number": 0}],
        [{"number": 1}, {"number": 1}],
        [None],
        [{"number": 1, "title": []}],
        [{"number": 1, "state": "done"}],
    ],
)
def test_issue_coverage_rejects_ambiguous_issue_identities(issues):
    with pytest.raises(ValueError):
        reporting.issue_coverage([], [], issues)


def test_issue_coverage_rejects_duplicate_result_identities():
    with pytest.raises(ValueError, match="duplicate"):
        reporting.issue_coverage([], [{"id": "same", "status": "PASS"}] * 2)


def test_issue_coverage_rejects_unknown_outcomes():
    with pytest.raises(ValueError, match="status"):
        reporting.issue_coverage([], [{"id": "one", "status": "success-ish"}])


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


def test_node_specific_mapping_never_attributes_neighbor_failure_to_capability():
    cap = {
        "id": "actions.amounts",
        "existing_tests": [
            "tests/validation/test_diagnostic_probes.py::test_set_then_add_is_visible_in_exported_seed_amount"
        ],
        "missing_tests": [],
    }
    rows = [
        {
            "id": "probes:test_diagnostic_probes.py::test_set_then_add_is_visible_in_exported_seed_amount",
            "name": "test_diagnostic_probes.py::test_set_then_add_is_visible_in_exported_seed_amount",
            "test_file": "tests/validation/test_diagnostic_probes.py",
            "status": "FAIL",
        },
        {
            "id": "probes:test_diagnostic_probes.py::test_net_reload_preserves_all_declared_observable_columns",
            "name": "test_diagnostic_probes.py::test_net_reload_preserves_all_declared_observable_columns",
            "test_file": "tests/validation/test_diagnostic_probes.py",
            "status": "FAIL",
        },
    ]
    reporting.attach_coverage([cap], rows)
    assert cap["result_counts"] == {"FAIL": 1}
    assert rows[0]["mapped_capabilities"] == ["actions.amounts"]
    assert "mapped_capabilities" not in rows[1]


def test_named_pytest_task_uses_repository_path_and_pinned_oracle_environment(tmp_path):
    report = {
        "source": {"revision": "abc"},
        "subject": {"binary": "/engine"},
        "configuration": {},
        "references": {
            "bionetgen": {
                "path": "/oracle",
                "script": "/oracle/bng2/BNG2.pl",
                "interpreter": "/usr/bin/perl",
                "network_binary_sha256": "digest",
            }
        },
        "results": [
            {
                "id": "probes:test_diagnostic_probes.py::test_one",
                "name": "test_diagnostic_probes.py::test_one",
                "test_file": "tests/validation/test_diagnostic_probes.py",
                "stage": "test",
                "status": "FAIL",
                "detail": "rate mismatch",
            }
        ],
    }
    task = reporting.investigation_tasks(report, tmp_path)[0]
    assert (
        "tests/validation/test_diagnostic_probes.py::test_one"
        in task["reproduce_command"]
    )
    assert task["reproduce_environment"]["BNG2_PERL"] == "/oracle/bng2/BNG2.pl"
    assert task["reproduce_environment"]["BNG2_NETWORK_SHA256"] == "digest"
