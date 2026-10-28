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
    integrated_boundaries,
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


def test_boundary_receipt_accepts_only_named_static_delay_execution(tmp_path):
    def run_boundary_receipt(mark_other_supported=False):
        report_dir = tmp_path / ("invalid" if mark_other_supported else "valid")
        rows = []

        def worker(case_id, operation, command, directory, results, **kwargs):
            directory.mkdir(parents=True)
            (directory / "identity.json").write_text("{}")
            checks = []
            for case_id, *_ in integrated_boundaries.CASES:
                static = case_id == "delay_state_history_a"
                dynamic = case_id == "delay_state_history_b"
                delay_execution = static or dynamic
                checks.append(
                    {
                        "id": f"sbml-boundary:{case_id}:"
                        f"{integrated_boundaries._registry_name(case_id)}",
                        "check": (
                            "static-delay-analytic-execution"
                            if static
                            else (
                                "dynamic-delay-analytic-execution"
                                if dynamic
                                else "explicit-loss-diagnostic"
                            )
                        ),
                        "status": "PASS",
                        "detail": (
                            "analytic trajectory"
                            if delay_execution
                            else "loss diagnostic"
                        ),
                        "related_issues": [157],
                        "supported_execution": delay_execution
                        or (
                            mark_other_supported
                            and case_id == "algebraic_species_product"
                        ),
                        "evidence_kind": (
                            "analytic-execution"
                            if delay_execution
                            else "diagnostic-only"
                        ),
                        "expected_behavior": (
                            "execute-static-delay-history"
                            if static
                            else (
                                "execute-state-dependent-delay-history"
                                if dynamic
                                else "explicit-loss-diagnostic"
                            )
                        ),
                    }
                )
                (directory / f"{case_id}.xml").write_text("<sbml/>")
                (directory / f"{case_id}.diagnostics.json").write_text("[]")
            for case_id, *_ in integrated_boundaries.SUPPORTED_EVENT_CASES:
                checks.append(
                    {
                        "id": f"sbml-event:{case_id}:source-trajectory",
                        "check": "source-trajectory",
                        "status": "PASS",
                        "detail": "source comparison passed",
                        "related_issues": [157],
                        "supported_execution": True,
                        "evidence_kind": "supported-execution",
                        "expected_behavior": (
                            "native-event-matches-independent-sbml-execution"
                        ),
                        "source_engine": "libRoadRunner",
                    }
                )
                (directory / f"{case_id}.xml").write_text("<sbml/>")
                (directory / f"{case_id}.diagnostics.json").write_text("[]")
                (directory / f"{case_id}.bngl").write_text("begin model\nend model\n")
            (directory / "delay_state_history_a.bngl").write_text(
                "begin model\nend model\n"
            )
            (directory / "delay_state_history_b.bngl").write_text(
                "begin model\nend model\n"
            )
            (directory / "checks.json").write_text(json.dumps(checks))
            parent = {"id": f"{case_id}:{operation}", "status": "PASS"}
            results.append(parent)
            return parent

        parent = extensions.invoke("boundaries", args(report_dir), rows, {}, worker)
        return parent

    assert run_boundary_receipt()["status"] == "PASS"
    invalid = run_boundary_receipt(mark_other_supported=True)
    assert invalid["status"] == "HARNESS_ERROR"
    assert (
        "unsupported boundary controls cannot claim supported execution"
        in invalid["detail"]
    )


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


def test_quantity_source_laws_are_declared_before_execution():
    assert "quantity-laws" in extensions.OPERATIONS
    names = extensions.check_ids("quantity-laws")
    assert names and len(names) == len(set(names))
    assert set(names) <= set(extensions.expected_ids([]))


def test_scientific_lane_runs_independent_checks_after_case_failure():
    import yaml

    workflow = yaml.safe_load(
        (Path(__file__).parents[2] / ".github/workflows/parity.yml").read_text()
    )
    steps = workflow["jobs"]["integrated-semantic-validation"]["steps"]
    native = next(
        s
        for s in steps
        if s.get("name") == "Check independently authored native BNGIR controls"
    )
    assert "steps.candidate_identity.outcome == 'success'" in native["if"]
    assert "always()" in native["if"]
    worker = next(
        s for s in steps if s.get("name") == "Verify spawned scientific worker identity"
    )
    assert "test_worker_package_identity.py" in worker["run"]


def test_the_worker_can_dispatch_every_registered_qualification():
    # The worker runs in isolated mode, so it cannot derive its dispatch list
    # from the registry at run time.  A qualification the worker cannot
    # dispatch falls through to the NFsim route and reports itself under the
    # wrong stage, which reads as an executed family that did something else.
    from tests.validation import integrated_worker

    registered = set(extensions.OPERATIONS)
    dispatchable = set(integrated_worker.QUALIFICATION_OPERATIONS)
    assert dispatchable == registered, {
        "missing_from_worker": sorted(registered - dispatchable),
        "unknown_to_worker": sorted(dispatchable - registered),
    }


def test_the_worker_refuses_an_operation_it_does_not_dispatch():
    # A catch-all route would run the NFsim trajectory for an operation the
    # worker does not dispatch, and the campaign would record that family as
    # executed.  The worker refuses the operation instead.
    import pytest

    from tests.validation import integrated_worker

    assert integrated_worker.require_dispatchable("boundaries") == "qualification"
    assert integrated_worker.require_dispatchable("bngir-v01") == "consumer"
    assert integrated_worker.require_dispatchable("nf") == "model"
    with pytest.raises(integrated_worker.HarnessError):
        integrated_worker.require_dispatchable("not-a-registered-family")
