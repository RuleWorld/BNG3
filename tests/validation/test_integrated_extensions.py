"""Fault controls for final-stage evidence import, budgets and replay identity."""

from argparse import Namespace
import json
import hashlib
from pathlib import Path

from tests.validation import (
    bngir_adversarial,
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
    assert "campaign:bngir-adversarial" in ids
    assert set(bngir_adversarial.check_ids()).issubset(ids)
    assert not set(
        extensions.expected_ids(cases, include_bngir_adversarial=False)
    ).intersection({"campaign:bngir-adversarial", *bngir_adversarial.check_ids()})
    assert set(extensions.check_ids("graph-identity")) == {
        f"graph-identity:{case['id']}" for case in graph_identity.CASES
    }
    for case in cases:
        assert f"{case['id']}:protocol" in ids
        assert (f"{case['id']}:nf-marginals" in ids) == (
            case["family"] in ("decay", "reversible", "dimerization")
        )


def test_bngir_adversarial_extension_requires_exact_issue_linked_checks(tmp_path):
    rows = []

    def worker(case_id, operation, command, directory, results, **kwargs):
        directory.mkdir(parents=True)
        (directory / "identity.json").write_text("{}")
        checks = [
            {
                "id": identity,
                "check": identity.rsplit(":", 1)[-1],
                "status": "PASS",
                "detail": "native structural control",
                "related_issues": [153, 154, 155, 156],
                "evidence_kind": "diagnostic-only",
                "supported_execution": False,
                "source_artifact": identity.rsplit(":", 1)[-1] + ".bngir.json",
                "source_sha256": hashlib.sha256(b"{}\n").hexdigest(),
            }
            for identity in extensions.check_ids("bngir-adversarial")
        ]
        for row in checks:
            (directory / row["source_artifact"]).write_bytes(b"{}\n")
        (directory / "checks.json").write_text(json.dumps(checks))
        row = dict(
            id=f"{case_id}:{operation}",
            stage=operation,
            status="PASS",
            receipt="receipt",
        )
        results.append(row)
        return row

    parent = extensions.invoke("bngir-adversarial", args(tmp_path), rows, {}, worker)

    assert parent["status"] == "PASS"
    assert parent["qualification"] == "bngir-adversarial"
    assert [row["id"] for row in rows[1:]] == extensions.check_ids("bngir-adversarial")
    assert all(row["related_issues"] == [153, 154, 155, 156] for row in rows[1:])


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


def test_native_marginals_route_consumes_bng3_exported_xml(tmp_path):
    """Native NFsim must read BNG3's XML so BNG3 conversion semantics apply."""
    case = next(
        c for c in integrated_cases.generated_cases() if c["family"] == "reversible"
    )
    rows, captured = [], {}

    def capture(case_id, stage, command, directory, results, **kwargs):
        captured["command"] = command
        directory.mkdir(parents=True)
        (directory / "checks.json").write_text("[]")
        row = dict(id=f"{case_id}:{stage}", stage=stage, status="PASS")
        results.append(row)
        return row

    extensions.invoke("nf-marginals", args(tmp_path), rows, {}, capture, case=case)
    command = captured["command"]
    native_xml = Path(command[command.index("--native-xml") + 1])
    assert native_xml == tmp_path / "cases" / case["id"] / "bng3/model.xml"
    assert "bng2" not in native_xml.parts


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
