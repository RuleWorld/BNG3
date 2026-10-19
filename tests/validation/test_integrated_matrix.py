"""Negative controls for the generated consumer matrix receipt audit."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from tests.validation import integrated_matrix as matrix
from tests.validation import integrated_marginals, integrated_protocol


def _write_gdat(path, data, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    values = np.column_stack((matrix.TIMES, data))
    np.savetxt(path, values, header="time " + " ".join(columns), fmt="%.17g")
    return path


def _receipt(directory, files):
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = [
        {
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]
    path = directory / "command.json"
    path.write_text(
        json.dumps({"status": "PASS", "command": ["fixture"], "artifacts": artifacts}),
        encoding="utf-8",
    )
    return str(path)


def _minimal_report(tmp_path):
    cases = matrix.selected_cases()
    rows = []
    for case in cases:
        for cell in matrix.expected_cells(case):
            directory = tmp_path / case["id"] / cell["stage"]
            data, columns = matrix.expected_source_trajectory(case)
            if cell["stage"] == "reuse":
                directory.mkdir(parents=True, exist_ok=True)
                mutated, mutated_columns = matrix.mutated_analytic_trajectory(
                    case, rate=0.6
                )
                source = directory / "translated.bngl"
                source.write_text("generated source", encoding="utf-8")
                metadata = {
                    "parameter": "k",
                    "original_value": 0.4,
                    "mutated_value": 0.6,
                    "factor": 1.5,
                    "source_path": str(source.resolve()),
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
                (directory / "mutation.json").write_text(
                    json.dumps(metadata), encoding="utf-8"
                )
                files = [
                    _write_gdat(directory / "api.gdat", data, columns),
                    _write_gdat(
                        directory / "reuse-mutated.gdat", mutated, mutated_columns
                    ),
                    _write_gdat(
                        directory / "reuse-fresh.gdat", mutated, mutated_columns
                    ),
                    directory / "mutation.json",
                    source,
                ]
            elif cell["stage"] in {"protocol", "nf-marginals"}:
                output = directory / "checks.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("[]", encoding="utf-8")
                files = [output]
            elif cell["stage"] == "atomizer":
                output = directory / "model.bngl"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("begin model\nend model\n", encoding="utf-8")
                files = [output]
            elif cell["stage"] in {"nf", "native-nf"}:
                files = [_write_gdat(directory / cell["artifact"], data, columns)]
            else:
                output = cell["artifact"]
                files = [_write_gdat(directory / output, data, columns)]
            receipt = _receipt(directory, files)
            rows.append(
                {
                    "id": cell["row_id"],
                    "integration_case": case["id"],
                    "stage": cell["stage"],
                    "status": "PASS",
                    "receipt": receipt,
                    "command": ["fixture", cell["stage"]],
                }
            )
        consumer_receipts = {
            operation: next(
                row["receipt"]
                for row in rows
                if row["id"] == f"{case['id']}:{operation}"
            )
            for operation in matrix.REQUIRED_CONSUMER_CHECKS
        }
        rows.extend(
            {
                "id": f"{case['id']}:{operation}:{check}",
                "integration_case": case["id"],
                "stage": operation,
                "check": check,
                "status": "PASS",
                "detail": "fixture selected parameter k and mutated it from 0.4 to 0.6",
                "receipts": [consumer_receipts[operation]],
            }
            for operation, names in matrix.REQUIRED_CONSUMER_CHECKS.items()
            for check in names
        )
        aux_receipt = consumer_receipts["reuse"]
        auxiliary = [
            (f"{case['id']}:protocol:{name}", "protocol", name)
            for name in integrated_protocol.expected_check_names
        ]
        auxiliary.extend(
            (
                f"{case['id']}:{route}-invariants:{name}",
                f"{route}-invariants",
                name,
            )
            for route in ("nf", "native-nf")
            for name in (
                "gdat.artifact-validity",
                "gdat.time-grid",
                "gdat.columns",
                "initial-amounts",
                "nonnegative-integer-counts",
                "observable-aliases",
                "invariant.conserved-total",
            )
        )
        auxiliary.extend(
            (
                f"{case['id']}:nf-marginals:{engine}.{name}",
                "nf-marginals",
                f"{engine}.{name}",
            )
            for engine in ("embedded", "native")
            for name in integrated_marginals.CHECKS
        )
        rows.extend(
            {
                "id": check_id,
                "integration_case": case["id"],
                "stage": stage,
                "check": check,
                "status": "PASS",
                "detail": "fixture check",
                "receipts": [aux_receipt],
            }
            for check_id, stage, check in auxiliary
        )
    return {
        "source": {"revision": "abc123", "dirty": False},
        "configuration": {"cases": cases},
        "results": rows,
    }


def test_expected_matrix_covers_mutation_and_all_declared_consumer_routes():
    cases = matrix.selected_cases()
    assert {case["transform"] for case in cases} == {
        "baseline",
        "function-shadowing",
        "concentration-coordinate",
        "shadow-global-decoy",
    }
    assert len(cases) == 4
    for case in cases:
        stages = {cell["stage"] for cell in matrix.expected_cells(case)}
        assert {
            "atomizer",
            "bng2",
            "cli",
            "api",
            "pybng",
            "compat",
            "net-reload",
            "bngir-v01",
            "bngir-v02",
            "bngl-reload",
            "sbml-reload",
            "nf",
            "native-nf",
            "reuse",
            "protocol",
            "nf-marginals",
        } <= stages
        assert f"{case['id']}:reuse:mutation-fresh" in matrix.expected_check_ids([case])


def test_report_audit_rejects_missing_and_duplicate_cells_and_missing_receipts(
    tmp_path,
):
    report = _minimal_report(tmp_path)
    assert matrix.audit_report(report, revision="abc123")["status"] == "PASS"

    missing = copy.deepcopy(report)
    missing["results"].pop()
    audited = matrix.audit_report(missing, revision="abc123")
    assert audited["status"] == "HARNESS_ERROR"
    assert any(row["status"] == "HARNESS_ERROR" for row in audited["auxiliary_checks"])

    duplicate = copy.deepcopy(report)
    duplicate["results"].append(duplicate["results"][0])
    assert (
        matrix.audit_report(duplicate, revision="abc123")["status"] == "HARNESS_ERROR"
    )

    no_receipt = copy.deepcopy(report)
    no_receipt["results"][0]["receipt"] = "/tmp/does-not-exist/command.json"
    assert (
        matrix.audit_report(no_receipt, revision="abc123")["status"] == "HARNESS_ERROR"
    )


def test_audit_keeps_unsupported_and_not_tested_distinct_from_pass(tmp_path):
    for status in ("UNSUPPORTED", "NOT_TESTED"):
        report = _minimal_report(tmp_path / status)
        report["results"][0]["status"] = status
        report["results"][0]["detail"] = "explicit test classification"
        audited = matrix.audit_report(report, revision="abc123")
        assert audited["status"] == status
        assert audited["cells"][0]["status"] == status


def test_lane_fails_on_failures_and_not_on_documented_support_boundaries(tmp_path):
    """The matrix audits receipts; a support boundary is reported, not failed.

    A consumer that refuses a construct, or a check that was never
    applicable, keeps its own status in the report.  Only a failed or
    malformed result fails the lane.
    """
    report = _minimal_report(tmp_path)
    assert matrix.audit_report(report, revision="abc123")["status"] == "PASS"
    assert matrix._lane_failures(matrix.audit_report(report, revision="abc123")) == []

    for status in ("UNSUPPORTED", "NOT_TESTED"):
        boundary = copy.deepcopy(report)
        boundary["results"][0]["status"] = status
        boundary["results"][0]["detail"] = "explicit test classification"
        audited = matrix.audit_report(boundary, revision="abc123")
        assert audited["status"] == status
        assert matrix._lane_failures(audited) == []

    for status in ("FAIL", "HARNESS_ERROR", "INVALID_INPUT", "TIMEOUT"):
        failed = copy.deepcopy(report)
        failed["results"][0]["status"] = status
        failed["results"][0]["detail"] = "explicit test classification"
        audited = matrix.audit_report(failed, revision="abc123")
        assert matrix._lane_failures(audited)


def test_adversarial_case_reaches_execution_matrix_with_conflicting_bindings():
    decoy = matrix.selected_cases()[-1]
    from tests.validation.integrated_cases import sbml_text

    source = sbml_text(decoy)
    assert decoy["id"] == "shadow-global-decoy-v1-n20-r0-a0"
    assert 'id="rate" value="13.0"' in source
    assert 'id="k" value="0.4"' in source
    assert "<bvar><ci>rate</ci></bvar>" in source
    assert {cell["stage"] for cell in matrix.expected_cells(decoy)} >= {
        "api",
        "sbml-reload",
        "reuse",
        "native-nf",
    }


def test_parameter_invalidation_check_is_not_tested_when_dependency_is_absent(tmp_path):
    report = _minimal_report(tmp_path)
    mutation = next(
        row for row in report["results"] if row["id"].endswith(":reuse:mutation-fresh")
    )
    mutation["status"] = "NOT_TESTED"
    mutation["detail"] = (
        "no translated parameter dependency; numeric folding is allowed"
    )
    audit = matrix.audit_report(report, revision="abc123")
    outcome = next(
        row
        for row in audit["analytic_and_metamorphic_checks"]
        if row["id"].endswith(":parameter-invalidation:mutated-and-fresh")
    )
    assert outcome["status"] == "NOT_TESTED"


def test_shared_wrong_mutated_and_fresh_outputs_fail_independent_law(tmp_path):
    report = _minimal_report(tmp_path)
    base_id = "v1-n20-r0-a0"
    reuse_row = next(
        row for row in report["results"] if row["id"] == f"{base_id}:reuse"
    )
    receipt_path = Path(reuse_row["receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    wrong, names = matrix.mutated_analytic_trajectory(
        next(case for case in matrix.selected_cases() if case["id"] == base_id),
        rate=0.4,
    )
    for artifact in receipt["artifacts"]:
        path = Path(artifact["path"])
        if path.name in {"reuse-mutated.gdat", "reuse-fresh.gdat"}:
            _write_gdat(path, wrong, names)
            artifact["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    audited = matrix.audit_report(report, revision="abc123")
    outcome = next(
        row
        for row in audited["analytic_and_metamorphic_checks"]
        if row["id"] == f"{base_id}:parameter-invalidation:mutated-and-fresh"
    )
    assert outcome["status"] == "FAIL"
    assert set(outcome["first_difference"]) == {
        "reuse-mutated.gdat",
        "reuse-fresh.gdat",
    }


def test_changed_artifact_digest_cannot_remain_green(tmp_path):
    report = _minimal_report(tmp_path)
    row = next(row for row in report["results"] if row["id"].endswith(":cli"))
    receipt_path = Path(row["receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    artifact_path = Path(receipt["artifacts"][0]["path"])
    artifact_path.write_text(artifact_path.read_text() + "\n", encoding="utf-8")
    audited = matrix.audit_report(report, revision="abc123")
    assert audited["status"] == "HARNESS_ERROR"
