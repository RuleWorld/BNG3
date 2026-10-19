"""Audit a bounded generated execution and representation matrix.

The existing integrated runner owns execution and its independent adapters.
This module selects a small high-value slice, audits its exact receipts, and
adds an independently computed parameter-mutation check to those artifacts.
It does not change or emulate BNG3 product behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np

from . import (
    compare,
    integrated_consumers,
    integrated_marginals,
    integrated_protocol,
    reporting,
)
from .integrated_cases import TIMES, expected_trajectory, generated_cases

_BASE_ID = "v1-n20-r0-a0"
_TRANSFORMS = (
    "function-shadowing",
    "concentration-coordinate",
    "shadow-global-decoy",
)
_CELL_OUTPUTS = {
    "atomizer": "model.bngl",
    "bng2": "model.gdat",
    "cli": "model.gdat",
    "api": "api.gdat",
    "pybng": "model.gdat",
    "compat": "model.gdat",
    "net-reload": "reload.gdat",
    "bngir-v01": "api.gdat",
    "bngir-v02": "api.gdat",
    "bngl-reload": "api.gdat",
    "sbml-reload": "api.gdat",
    "nf": "nf.gdat",
    "native-nf": "nf.gdat",
    "reuse": "api.gdat",
    "protocol": "checks.json",
    "nf-marginals": "checks.json",
}
_EXECUTION_CELL_STAGES = (
    "atomizer",
    "bng2",
    "cli",
    "api",
    "pybng",
    "compat",
    "net-reload",
    "nf",
    "native-nf",
    "protocol",
    "nf-marginals",
)
_CONSUMER_STAGES = (
    "bngir-v01",
    "bngir-v02",
    "bngl-reload",
    "sbml-reload",
    "reuse",
)
REQUIRED_CONSUMER_CHECKS = integrated_consumers.CHECKS
_ALLOWED = {
    "PASS",
    "FAIL",
    "UNSUPPORTED",
    "NOT_TESTED",
    "INVALID_INPUT",
    "TIMEOUT",
    "HARNESS_ERROR",
}


def selected_cases():
    """Return the base, shadowing adversary, and concentration transform."""
    cases = {case["id"]: case for case in generated_cases(full=True)}
    selected = [dict(cases[_BASE_ID], transform="baseline")]
    for transform in _TRANSFORMS:
        selected.append(cases[f"{transform}-{_BASE_ID}"])
    return selected


def expected_cells(case):
    """Declare one required execution cell per shared runner stage."""
    return [
        {
            "id": f"{case['id']}:{stage}",
            "row_id": f"{case['id']}:{stage}",
            "stage": stage,
            "artifact": _CELL_OUTPUTS[stage],
            "route": (
                "execution"
                if stage in _EXECUTION_CELL_STAGES
                else "representation-consumer"
            ),
        }
        for stage in _CELL_OUTPUTS
    ]


def expected_check_ids(cases):
    """Return exact consumer evidence IDs independently of worker output."""
    consumer = [
        f"{case['id']}:{operation}:{check}"
        for case in cases
        for operation in integrated_consumers.OPERATIONS
        for check in integrated_consumers.CHECKS[operation]
    ]
    protocol = [
        f"{case['id']}:protocol:{check}"
        for case in cases
        for check in integrated_protocol.expected_check_names
    ]
    invariants = [
        f"{case['id']}:{route}-invariants:{check}"
        for case in cases
        for route in ("nf", "native-nf")
        for check in (
            "gdat.artifact-validity",
            "gdat.time-grid",
            "gdat.columns",
            "initial-amounts",
            "nonnegative-integer-counts",
            "observable-aliases",
            "invariant.conserved-total",
        )
    ]
    marginals = [
        f"{case['id']}:nf-marginals:{engine}.{check}"
        for case in cases
        for engine in ("embedded", "native")
        for check in integrated_marginals.CHECKS
    ]
    return consumer + protocol + invariants + marginals


def _status(rows):
    statuses = {row["status"] for row in rows}
    return next(
        (
            status
            for status in (
                "HARNESS_ERROR",
                "FAIL",
                "INVALID_INPUT",
                "TIMEOUT",
                "UNSUPPORTED",
                "NOT_TESTED",
            )
            if status in statuses
        ),
        "PASS",
    )


def _lane_failures(audit):
    """Return the audited rows that fail the matrix lane.

    The matrix audits receipts and evidence: a missing or stale receipt, an
    unexplained cell, or a failed comparison is a lane failure.  A consumer
    that explicitly refuses a construct, or a check that was never
    applicable, is reported with that status and stays distinct from a pass;
    it is a documented support boundary, not a receipt failure.  This is the
    same distinction the integrated report's gate makes.
    """
    failing = {"FAIL", "HARNESS_ERROR", "INVALID_INPUT", "TIMEOUT"}
    failures = [
        row
        for row in audit.get("results", [])
        if row.get("status") in failing
    ]
    if audit.get("errors"):
        failures.append(
            {
                "id": "matrix:report-integrity",
                "status": "HARNESS_ERROR",
                "detail": "; ".join(str(error) for error in audit["errors"]),
            }
        )
    return failures


def _row_index(report):
    rows = report.get("results")
    if not isinstance(rows, list):
        return {}, ["integrated report has no results list"]
    index = {}
    errors = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            errors.append("integrated report contains a result without an ID")
            continue
        index.setdefault(row["id"], []).append(row)
    duplicates = sorted(key for key, matches in index.items() if len(matches) != 1)
    if duplicates:
        errors.append("duplicate integrated result IDs: " + ", ".join(duplicates))
    return index, errors


def _artifact_from_receipt(row, artifact_name):
    receipt_path = row.get("receipt")
    if not isinstance(receipt_path, str) or not receipt_path:
        raise ValueError("missing command receipt")
    receipt_file = Path(receipt_path)
    payload = json.loads(receipt_file.read_text(encoding="utf-8"))
    _validate_receipt(payload, receipt_file, require_success=True)
    for artifact in payload.get("artifacts", []):
        path = Path(artifact.get("path", ""))
        if path.name == artifact_name:
            if not path.is_file():
                raise ValueError(f"receipt artifact is missing: {path}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != artifact.get("sha256"):
                raise ValueError(f"receipt digest mismatch: {path}")
            return path
    raise ValueError(f"receipt does not declare required artifact {artifact_name!r}")


def _validate_receipt(payload, path, *, require_success=False):
    if payload.get("status") not in _ALLOWED or not isinstance(
        payload.get("command"), list
    ):
        raise ValueError(f"command receipt has invalid status or command: {path}")
    if require_success and payload.get("status") != "PASS":
        raise ValueError(
            f"command receipt is not a successful execution receipt: {path}"
        )
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError(f"command receipt has no artifact inventory: {path}")
    for artifact in artifacts:
        artifact_path = Path(artifact.get("path", ""))
        if not artifact_path.is_file():
            raise ValueError(f"receipt artifact is missing: {artifact_path}")
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if digest != artifact.get("sha256"):
            raise ValueError(f"receipt artifact digest mismatch: {artifact_path}")


def _check_cell(index, case, cell):
    matches = index.get(cell["row_id"], [])
    if len(matches) != 1:
        return {
            **cell,
            "integration_case": case["id"],
            "status": "HARNESS_ERROR",
            "detail": f"expected exactly one stage row, found {len(matches)}",
        }
    source = matches[0]
    status = source.get("status")
    if status not in _ALLOWED:
        status = "HARNESS_ERROR"
        detail = f"invalid or missing stage status {source.get('status')!r}"
    else:
        detail = source.get("detail", "")
    result = {
        **cell,
        "integration_case": case["id"],
        "status": status,
        "detail": detail,
        "replay_command": source.get("command"),
        "receipt": source.get("receipt"),
        "blocked_by": source.get("blocked_by", []),
    }
    if status == "PASS":
        try:
            result["artifact_path"] = str(
                _artifact_from_receipt(source, cell["artifact"])
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            result.update(status="HARNESS_ERROR", detail=str(exc))
    elif not detail:
        result.update(status="HARNESS_ERROR", detail="non-pass cell has no explanation")
    return result


def _check_child(index, case, operation, check):
    check_id = f"{case['id']}:{operation}:{check}"
    matches = index.get(check_id, [])
    if len(matches) != 1:
        return {
            "id": check_id,
            "integration_case": case["id"],
            "stage": operation,
            "check": check,
            "status": "HARNESS_ERROR",
            "detail": f"expected exactly one consumer check, found {len(matches)}",
        }
    source = matches[0]
    status = source.get("status")
    receipts = source.get("receipts")
    if status not in _ALLOWED or not isinstance(receipts, list):
        status = "HARNESS_ERROR"
        detail = "consumer check has invalid status or receipt list"
    elif not receipts and status == "PASS":
        status = "HARNESS_ERROR"
        detail = "passing consumer check has no artifact receipt"
    elif not isinstance(source.get("detail"), str):
        status = "HARNESS_ERROR"
        detail = "consumer check has no detail"
    else:
        detail = source["detail"]
    if status == "PASS":
        try:
            for receipt in receipts:
                receipt_path = Path(receipt)
                if not receipt_path.is_file():
                    raise ValueError(f"consumer receipt is missing: {receipt}")
                _validate_receipt(
                    json.loads(receipt_path.read_text(encoding="utf-8")), receipt_path
                )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            status = "HARNESS_ERROR"
            detail = str(exc)
    return {
        "id": check_id,
        "integration_case": case["id"],
        "stage": operation,
        "check": check,
        "status": status,
        "detail": detail,
        "receipts": receipts if isinstance(receipts, list) else [],
    }


def _check_direct(index, case, check_id, stage, check_name):
    matches = index.get(check_id, [])
    if len(matches) != 1:
        return {
            "id": check_id,
            "integration_case": case["id"],
            "stage": stage,
            "check": check_name,
            "status": "HARNESS_ERROR",
            "detail": f"expected exactly one qualification result, found {len(matches)}",
        }
    source = matches[0]
    status = source.get("status")
    if status not in _ALLOWED or not isinstance(source.get("detail"), str):
        status = "HARNESS_ERROR"
        detail = "qualification result has invalid status or missing detail"
    else:
        detail = source["detail"]
    receipts = source.get("receipts", [])
    if status == "PASS":
        if not isinstance(receipts, list) or not receipts:
            status = "HARNESS_ERROR"
            detail = "passing qualification has no receipt"
        else:
            try:
                for receipt in receipts:
                    path = Path(receipt)
                    if not path.is_file():
                        raise ValueError(f"qualification receipt is missing: {receipt}")
                    _validate_receipt(
                        json.loads(path.read_text(encoding="utf-8")),
                        path,
                        require_success=False,
                    )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                status = "HARNESS_ERROR"
                detail = str(exc)
    return {
        "id": check_id,
        "integration_case": case["id"],
        "stage": stage,
        "check": check_name,
        "status": status,
        "detail": detail,
        "receipts": receipts if isinstance(receipts, list) else [],
    }


def _trajectory_difference(path, expected_values, expected_columns, *, rate=None):
    data, columns = compare.parse_gdat(path)
    if data is None or data.ndim != 2 or not np.isfinite(data).all():
        return {"field": "artifact", "detail": "trajectory missing or non-finite"}
    if data.shape[0] != len(TIMES) or not np.allclose(
        data[:, 0], TIMES, rtol=0, atol=1e-9
    ):
        return {
            "field": "time-grid",
            "expected_rows": len(TIMES),
            "actual_rows": int(data.shape[0]),
        }
    if len(columns) != data.shape[1] or len(columns) != len(set(columns)):
        return {"field": "columns", "actual": columns}
    for name in expected_columns:
        if name not in columns:
            return {"field": "columns", "missing": name, "actual": columns}
        observed = data[:, columns.index(name)]
        expected = expected_values[:, expected_columns.index(name)]
        unequal = ~np.isclose(observed, expected, rtol=1e-7, atol=1e-9)
        if unequal.any():
            row = int(np.flatnonzero(unequal)[0])
            return {
                "field": name,
                "row": row,
                "time": float(data[row, 0]),
                "expected": float(expected[row]),
                "actual": float(observed[row]),
                "rate": rate,
            }
    return None


def expected_source_trajectory(case):
    """Amount-coordinate independent reference on the shared generated grid."""
    data, columns = expected_trajectory(case)
    species = [name for name in columns if name in {"A", "B"}]
    return data[:, [columns.index(name) for name in species]], tuple(species)


def mutated_analytic_trajectory(case, *, rate):
    """Closed-form first-order conversion reference after a rate mutation."""
    times = TIMES
    initial = float(case["initial"])
    a = initial * np.exp(-float(rate) * times)
    return np.column_stack((a, initial - a)), ("A", "B")


def _analytic_rows(cells, case, child_checks):
    rows = []
    baseline, names = expected_source_trajectory(case)
    deterministic_stages = (
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
        "reuse",
    )
    by_stage = {cell["stage"]: cell for cell in cells}
    for stage in deterministic_stages:
        cell = by_stage[stage]
        row = {
            "id": f"{case['id']}:analytic-source:{stage}",
            "integration_case": case["id"],
            "stage": stage,
            "status": cell["status"],
            "detail": "bounded analytic amount trajectory check",
            "receipts": [cell["receipt"]] if cell.get("receipt") else [],
            "reference": "tests.validation.integrated_cases.expected_trajectory",
        }
        if cell["status"] == "PASS":
            try:
                difference = _trajectory_difference(
                    cell["artifact_path"], baseline, names
                )
                row.update(
                    status="FAIL" if difference else "PASS",
                    first_difference=difference,
                )
            except (OSError, ValueError) as exc:
                row.update(status="HARNESS_ERROR", detail=str(exc))
        rows.append(row)

    reuse = by_stage["reuse"]
    mutation_row = {
        "id": f"{case['id']}:parameter-invalidation:mutated-and-fresh",
        "integration_case": case["id"],
        "stage": "reuse",
        "status": reuse["status"],
        "detail": "reused and freshly compiled trajectories against k=0.6 analytic law",
        "reference": "closed-form dA/dt=-0.6*A; dB/dt=0.6*A",
        "receipts": [reuse["receipt"]] if reuse.get("receipt") else [],
    }
    mutation_child_id = f"{case['id']}:reuse:mutation-fresh"
    mutation_child = next(
        (row for row in child_checks if row["id"] == mutation_child_id), None
    )
    if mutation_child is None:
        mutation_row.update(
            status="HARNESS_ERROR", detail="missing mutation-fresh consumer check"
        )
    elif mutation_child["status"] != "PASS":
        mutation_row.update(
            status=mutation_child["status"],
            detail=(
                "parameter invalidation not executed or failed: "
                + mutation_child["detail"]
            ),
        )
    elif reuse["status"] == "PASS":
        try:
            payload = json.loads(Path(reuse["receipt"]).read_text(encoding="utf-8"))
            artifacts = {
                Path(item["path"]).name: item for item in payload.get("artifacts", [])
            }
            mutation_meta_path = Path(reuse["receipt"]).parent / "mutation.json"
            mutation_meta = json.loads(mutation_meta_path.read_text(encoding="utf-8"))
            source_path = Path(mutation_meta["source_path"])
            source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if source_digest != mutation_meta.get("source_sha256"):
                raise ValueError("mutation source digest does not match provenance")
            parameter_name = mutation_meta.get("parameter")
            source_rate = float(mutation_meta["original_value"])
            mutation_rate = float(mutation_meta["mutated_value"])
            mutation_factor = float(mutation_meta["factor"])
            if parameter_name != "k" or not np.isclose(source_rate, 0.4):
                mutation_row.update(
                    status="NOT_TESTED",
                    detail=(
                        f"changed parameter {parameter_name!r} is not a proven "
                        "direct k dependency"
                    ),
                )
                rows.append(mutation_row)
                return rows
            if not np.isclose(mutation_rate, source_rate * mutation_factor):
                raise ValueError("mutation value does not match recorded factor")
            expected, mutated_names = mutated_analytic_trajectory(
                case, rate=mutation_rate
            )
            differences = {}
            for name in ("reuse-mutated.gdat", "reuse-fresh.gdat"):
                artifact = artifacts.get(name)
                if artifact is None:
                    differences[name] = {"field": "receipt", "detail": "missing"}
                    continue
                path = Path(artifact["path"])
                if not path.is_file() or hashlib.sha256(
                    path.read_bytes()
                ).hexdigest() != artifact.get("sha256"):
                    differences[name] = {"field": "receipt-digest", "path": str(path)}
                    continue
                differences[name] = _trajectory_difference(
                    path, expected, mutated_names, rate=mutation_rate
                )
            actual = {
                name: diff for name, diff in differences.items() if diff is not None
            }
            row = mutation_row
            row.update(
                status="FAIL" if actual else "PASS",
                first_difference=actual or None,
                mutation_rate=mutation_rate,
                parameter_name=parameter_name,
                selected_parameter=mutation_child["detail"],
                source_rate=source_rate,
                mutation_factor=mutation_factor,
                adversarial_shadow_rate=float(case.get("shadow_global_rate", 7.0)),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            mutation_row.update(status="HARNESS_ERROR", detail=str(exc))
    rows.append(mutation_row)

    # Shadowing must preserve k=0.4 semantics despite the deliberately tempting
    # global-rate declaration in the generated source fixture.
    if case.get("transform") in ("function-shadowing", "shadow-global-decoy"):
        api = by_stage["api"]
        difference = None
        if api["status"] == "PASS":
            correct, correct_names = expected_source_trajectory(case)
            difference = _trajectory_difference(
                api["artifact_path"], correct, correct_names
            )
        status = (
            api["status"]
            if api["status"] != "PASS"
            else ("FAIL" if difference else "PASS")
        )
        rows.append(
            {
                "id": f"{case['id']}:adversarial-reference:shadowed-global-rate",
                "integration_case": case["id"],
                "stage": "api",
                "status": status,
                "detail": "executed API trajectory matches source k despite conflicting global rate",
                "reference": "tests.validation.integrated_cases.expected_trajectory",
                "decoy_rate": float(case.get("shadow_global_rate", 7.0)),
                "correct_rate": 0.4,
                "first_difference": difference,
            }
        )
    return rows


def audit_report(report, *, revision=None):
    """Audit expected stage/check cells and return a strict matrix report."""
    cases = selected_cases()
    index, errors = _row_index(report)
    source = report.get("source", {})
    actual_revision = source.get("revision")
    if not isinstance(actual_revision, str) or not actual_revision:
        errors.append("integrated report has no source revision")
    if source.get("dirty") is not False:
        errors.append(
            "integrated report source is dirty or clean-tree state is missing"
        )
    if revision is not None and actual_revision != revision:
        errors.append(
            f"candidate revision mismatch: expected {revision}, got {actual_revision}"
        )
    configured = {
        row.get("id")
        for row in report.get("configuration", {}).get("cases", [])
        if isinstance(row, dict)
    }
    missing_cases = sorted({case["id"] for case in cases} - configured)
    if missing_cases:
        errors.append(
            "selected cases absent from integrated run: " + ", ".join(missing_cases)
        )

    cells, checks, auxiliary, analytic = [], [], [], []
    for case in cases:
        case_cells = [_check_cell(index, case, cell) for cell in expected_cells(case)]
        cells.extend(case_cells)
        case_checks = [
            _check_child(index, case, operation, check)
            for operation, names in integrated_consumers.CHECKS.items()
            for check in names
        ]
        checks.extend(case_checks)
        direct_specs = [
            (
                f"{case['id']}:protocol:{name}",
                "protocol",
                name,
            )
            for name in integrated_protocol.expected_check_names
        ]
        invariant_names = (
            "gdat.artifact-validity",
            "gdat.time-grid",
            "gdat.columns",
            "initial-amounts",
            "nonnegative-integer-counts",
            "observable-aliases",
            "invariant.conserved-total",
        )
        direct_specs.extend(
            (f"{case['id']}:{route}-invariants:{name}", f"{route}-invariants", name)
            for route in ("nf", "native-nf")
            for name in invariant_names
        )
        direct_specs.extend(
            (
                f"{case['id']}:nf-marginals:{engine}.{name}",
                "nf-marginals",
                f"{engine}.{name}",
            )
            for engine in ("embedded", "native")
            for name in integrated_marginals.CHECKS
        )
        case_auxiliary = [_check_direct(index, case, *spec) for spec in direct_specs]
        auxiliary.extend(case_auxiliary)
        analytic.extend(_analytic_rows(case_cells, case, case_checks + case_auxiliary))

    all_rows = cells + checks + auxiliary + analytic
    status = _status(all_rows)
    if errors:
        status = "HARNESS_ERROR"
    findings = []
    cell_by_id = {cell["id"]: cell for cell in cells}
    for row in analytic:
        stage_cell = cell_by_id.get(f"{row['integration_case']}:{row['stage']}")
        issue_ids = (
            [161]
            if any(
                case["id"] == row["integration_case"]
                and case.get("transform") == "concentration-coordinate"
                for case in cases
            )
            else ([143, 141] if row["stage"] == "reuse" else [143])
        )
        findings.append(
            {
                **row,
                "check": row["id"].split(":", 1)[-1],
                "related_issues": issue_ids,
                "capabilities": [
                    "integration.cross-component",
                    "generated.consumer-matrix",
                ],
                "command": stage_cell.get("replay_command") if stage_cell else None,
                "receipt": stage_cell.get("receipt") if stage_cell else None,
            }
        )
    audited_cells = cells + checks + auxiliary
    for row in audited_cells:
        if row["status"] == "PASS":
            continue
        findings.append(
            {
                "id": f"matrix:audit:{row['id']}",
                "stage": "matrix-audit:" + row.get("stage", "cell"),
                "check": row.get("check", row.get("stage", "cell")),
                "integration_case": row.get("integration_case"),
                "status": row["status"],
                "detail": row.get("detail", ""),
                "first_difference": row.get("first_difference"),
                "related_issues": [],
                "capabilities": ["generated.consumer-matrix"],
                "command": row.get("replay_command"),
                "receipt": row.get("receipt"),
                "receipts": row.get("receipts", []),
            }
        )
    for index, error in enumerate(errors):
        findings.append(
            {
                "id": f"matrix:report-integrity:{index + 1}",
                "stage": "matrix-report-integrity",
                "check": "matrix-report-integrity",
                "status": "HARNESS_ERROR",
                "detail": error,
                "related_issues": [],
                "capabilities": ["generated.consumer-matrix"],
            }
        )
    matrix_report = {
        "schema_version": 1,
        "generated_by": "tests.validation.integrated_matrix",
        "status": status,
        "source": {
            "revision": actual_revision,
            "dirty": source.get("dirty"),
            "subject": report.get("subject", {}),
        },
        "subject": report.get("subject", {}),
        "references": report.get("references", {}),
        "configuration": {
            **report.get("configuration", {}),
            "matrix": "bounded-generated-consumer-matrix-v1",
            "selected_cases": [case["id"] for case in cases],
        },
        "errors": errors,
        "expected_cell_ids": [
            cell["row_id"] for case in cases for cell in expected_cells(case)
        ],
        "expected_check_ids": expected_check_ids(cases),
        "expected_contract_ids": [row["id"] for row in findings],
        "cells": cells,
        "consumer_checks": checks,
        "auxiliary_checks": auxiliary,
        "analytic_and_metamorphic_checks": analytic,
        "results": findings,
        "failure_clusters": reporting.cluster_failures(findings),
        "investigation_tasks": [],
    }
    return matrix_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    audit = audit_report(report, revision=args.revision)
    audit["investigation_tasks"] = reporting.investigation_tasks(
        audit, args.output.parent
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return 0 if _lane_failures(audit) == [] else 1


if __name__ == "__main__":
    raise SystemExit(main())
