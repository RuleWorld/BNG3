"""Fault controls for final-stage evidence import, budgets and replay identity."""

from argparse import Namespace
import json
from pathlib import Path

from tests.validation import (
    graph_identity,
    integrated_extensions as extensions,
    integrated_cases,
)


def args(tmp_path):
    return Namespace(
        report_dir=tmp_path, nfsim_binary=Path("/native/NFsim"), ensemble_runs=32
    )


def test_final_registry_covers_each_stage_and_namespaced_check_once():
    cases = integrated_cases.generated_cases()
    ids = extensions.expected_ids(cases)
    assert len(ids) == len(set(ids))
    assert "campaign:boundaries" in ids
    assert "campaign:graph-identity" in ids
    assert set(extensions.check_ids("graph-identity")) == {
        f"graph-identity:{case['id']}" for case in graph_identity.CASES
    }
    for case in cases:
        assert f"{case['id']}:protocol" in ids
        assert (f"{case['id']}:nf-marginals" in ids) == (
            case["family"] in ("decay", "reversible", "dimerization")
        )


def test_graph_identity_receipt_links_each_generated_observation_to_issue_142(
    tmp_path,
):
    rows = []

    def worker(case_id, operation, command, directory, results, **kwargs):
        directory.mkdir(parents=True)
        (directory / "identity.json").write_text("{}")
        checks = [
            {
                "id": check_id,
                "check": check_id.rsplit(":", 1)[-1],
                "status": "PASS",
                "detail": "generated graph identity observation",
                "related_issues": [142],
            }
            for check_id in extensions.check_ids("graph-identity")
        ]
        (directory / "checks.json").write_text(json.dumps(checks))
        row = dict(
            id=f"{case_id}:{operation}",
            stage=operation,
            status="PASS",
            receipt="receipt",
        )
        results.append(row)
        return row

    parent = extensions.invoke("graph-identity", args(tmp_path), rows, {}, worker)

    assert parent["status"] == "PASS"
    assert parent.get("aggregate") is True
    assert [row["related_issues"] for row in rows[1:]] == [[142]] * len(
        graph_identity.CASES
    )


def test_missing_qualification_checks_cannot_pass_after_successful_process(tmp_path):
    rows = []

    def success(case, stage, command, directory, results, **kwargs):
        directory.mkdir(parents=True)
        row = dict(
            id=f"{case}:{stage}", stage=stage, status="PASS", integration_case=case
        )
        results.append(row)
        return row

    parent = extensions.invoke("boundaries", args(tmp_path), rows, {}, success)
    assert parent["status"] == "HARNESS_ERROR"
    assert "integration_case" not in parent
    assert parent["qualification"] == "boundaries"
    assert all(r["status"] == "NOT_TESTED" for r in rows[1:])


def test_ensemble_receipt_preserves_seed_budget_and_rejects_duplicate_evidence(
    tmp_path,
):
    case = next(
        c for c in integrated_cases.generated_cases() if c["family"] == "reversible"
    )
    rows, captured = [], {}

    def duplicate(case_id, stage, command, directory, results, **kwargs):
        captured.update(command=command, timeout=kwargs["timeout"])
        directory.mkdir(parents=True)
        identity = extensions.check_ids("nf-marginals", case)[0]
        (directory / "checks.json").write_text(
            json.dumps([dict(id=identity, status="PASS")] * 2)
        )
        row = dict(id=f"{case_id}:{stage}", stage=stage, status="PASS")
        results.append(row)
        return row

    parent = extensions.invoke(
        "nf-marginals", args(tmp_path), rows, {}, duplicate, case=case
    )
    assert parent["status"] == "HARNESS_ERROR"
    command = captured["command"]
    assert command[command.index("--ensemble-runs") + 1] == "32"
    assert command[command.index("--ensemble-cases") + 1] == "61"
    assert captured["timeout"] == 240


def test_complete_ids_without_observation_payload_are_still_harness_errors(tmp_path):
    case = integrated_cases.generated_cases()[0]
    rows = []

    def empty_payload(case_id, stage, command, directory, results, **kwargs):
        directory.mkdir(parents=True)
        checks = [
            dict(id=identity, status="PASS")
            for identity in extensions.check_ids("protocol", case)
        ]
        (directory / "checks.json").write_text(json.dumps(checks))
        row = dict(id=f"{case_id}:{stage}", stage=stage, status="PASS")
        results.append(row)
        return row

    parent = extensions.invoke(
        "protocol", args(tmp_path), rows, {}, empty_payload, case=case
    )
    assert parent["status"] == "HARNESS_ERROR"
    assert all(r["status"] == "NOT_TESTED" for r in rows[1:])
