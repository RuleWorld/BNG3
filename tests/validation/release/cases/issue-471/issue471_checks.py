"""Fail-closed consumers for issue #471 release evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _oracle_receipt_errors(
    row: dict[str, Any], receipt: dict[str, Any], revision: str
) -> list[str]:
    errors: list[str] = []
    row_id = row.get("id", "<missing-id>")
    expected_check = f"release-capability[{row_id}]"
    if receipt.get("schema_version") != 1:
        errors.append(f"{row_id}: receipt schema_version must be 1")
    if receipt.get("kind") != "release-oracle-consumer-receipt":
        errors.append(f"{row_id}: consumer receipt kind is missing")
    if (
        receipt.get("capability_id") != row_id
        or receipt.get("check_id") != expected_check
    ):
        errors.append(f"{row_id}: receipt does not name its exact capability check")
    if (
        receipt.get("source_revision") != revision
        or receipt.get("product_revision") != revision
    ):
        errors.append(f"{row_id}: source and product revisions must equal {revision}")
    if receipt.get("result") != "pass":
        errors.append(f"{row_id}: consumer result is not pass")

    oracle = receipt.get("oracle")
    if not isinstance(oracle, dict):
        errors.append(f"{row_id}: named oracle identity is missing")
        oracle = {}
    for key in ("name", "revision", "command"):
        if not isinstance(oracle.get(key), str) or not oracle[key].strip():
            errors.append(f"{row_id}: oracle {key} is missing")
    if not _sha256(oracle.get("artifact_sha256")):
        errors.append(f"{row_id}: oracle artifact SHA-256 is invalid")
    origin = oracle.get("expected_origin")
    if origin not in {
        "external-source",
        "analytic-derivation",
        "official-expected-data",
    }:
        errors.append(f"{row_id}: expected answer origin is not independently grounded")
    identity_text = " ".join(
        str(oracle.get(key, "")) for key in ("name", "command", "expected_origin")
    ).casefold()
    if any(
        term in identity_text
        for term in ("bng3-generated", "sut-generated", "self-oracle")
    ):
        errors.append(f"{row_id}: expected answer is identified as SUT-generated")

    producer = receipt.get("producer")
    consumer = receipt.get("consumer")
    if not isinstance(producer, dict) or not isinstance(consumer, dict):
        errors.append(
            f"{row_id}: separate producer and downstream consumer records are required"
        )
        producer, consumer = {}, {}
    producer_digest = producer.get("output_sha256")
    if not _sha256(producer_digest):
        errors.append(f"{row_id}: producer output digest is invalid")
    if consumer.get("consumed_producer_sha256") != producer_digest:
        errors.append(
            f"{row_id}: downstream consumer did not identify the producer output"
        )
    if consumer.get("consumed_oracle_sha256") != oracle.get("artifact_sha256"):
        errors.append(
            f"{row_id}: downstream consumer did not identify the oracle artifact"
        )
    if consumer.get("comparison") != "pass":
        errors.append(f"{row_id}: downstream comparison is not pass")
    return errors


def _has_named_oracle(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = value.casefold()
    if "as appropriate" in lowered or re.search(
        r"\b(?:tbd|unknown|none|n/a|oracle needed)\b", lowered
    ):
        return False
    if any(
        term in lowered for term in ("bng3-generated", "sut-generated", "self-oracle")
    ):
        return False
    names = (
        "bng2",
        "nfsim",
        "pybionetgen",
        "ssts",
        "roadrunner",
        "libsbml",
        "jsbml",
        "bngsim",
        "multi specification",
        "analytic",
        "hand-derived",
        "independently authored",
        "independent exact network enumerator",
    )
    return any(name in lowered for name in names)


def oracle_independence_report(
    root: Path, receipt_dir: Path, revision: str
) -> dict[str, Any]:
    """Report declaration coverage separately from exact-revision execution evidence."""
    matrix_path = root / "provenance/capability-matrix.yml"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    rows = matrix.get("rows")
    if not isinstance(rows, list):
        raise ValueError("capability matrix rows must be a list")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision must be a full 40-character commit SHA")
    duplicate_ids: set[str] = set()
    seen: set[str] = set()
    findings: list[str] = []
    named = 0
    grounded = 0
    status_counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            findings.append("matrix contains a row without a stable ID")
            continue
        row_id = row["id"]
        if row_id in seen:
            duplicate_ids.add(row_id)
        seen.add(row_id)
        status = str(row.get("status", "<missing>"))
        status_counts[status] = status_counts.get(status, 0) + 1
        oracle_decl = row.get("oracle")
        if _has_named_oracle(oracle_decl):
            named += 1
        else:
            findings.append(
                f"{row_id}: oracle declaration does not name an external or analytic source"
            )
        receipt_path = receipt_dir / f"{row_id}.json"
        if not receipt_path.is_file():
            findings.append(f"{row_id}: no exact-revision downstream consumer receipt")
            continue
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(f"{row_id}: consumer receipt cannot be read: {exc}")
            continue
        row_errors = _oracle_receipt_errors(row, receipt, revision)
        if status != "implemented":
            row_errors.append(
                f"{row_id}: matrix status is {status}; implementation is not qualified"
            )
        if row_errors:
            findings.extend(row_errors)
        else:
            grounded += 1
    findings.extend(
        f"duplicate matrix row ID: {row_id}" for row_id in sorted(duplicate_ids)
    )
    return {
        "schema_version": 1,
        "check_id": "release-oracle-independence",
        "revision": revision,
        "row_count": len(rows),
        "named_oracle_rows": named,
        "grounded_execution_rows": grounded,
        "source_status_counts": status_counts,
        "findings": findings,
        "result": "pass" if not findings and grounded == len(rows) else "fail",
    }


def topology_errors(
    workflow: dict[str, Any], independent_groups: list[list[str]]
) -> list[str]:
    """Check declared parallel job groups and unconditional partial-artifact uploads."""
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return ["workflow has no jobs"]
    errors: list[str] = []
    for group in independent_groups:
        for job_name in group:
            if job_name not in jobs:
                errors.append(f"independent job is missing: {job_name}")
        for left_index, left in enumerate(group):
            if left not in jobs:
                continue
            for right in group[left_index + 1 :]:
                if right not in jobs:
                    continue
                for dependent, other in ((left, right), (right, left)):
                    needs = jobs[dependent].get("needs", [])
                    needs = [needs] if isinstance(needs, str) else needs
                    if other in needs:
                        errors.append(
                            f"independent jobs are serialized: {other} -> {dependent}"
                        )
    for job_name, job in jobs.items():
        for step in job.get("steps", []) if isinstance(job, dict) else []:
            if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                condition = str(step.get("if", ""))
                if "always()" not in condition:
                    errors.append(
                        f"{job_name}: artifact upload does not run after failure"
                    )
    return errors


def check_workflow_topology(path: Path) -> dict[str, Any]:
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    groups = [["bng2-parity", "nfsim-parity", "pybionetgen-compat"]]
    errors = topology_errors(workflow, groups)
    # These jobs share source-lock validation but their scientific checks are independent.
    expected_needs = {name: ["oracle-lock"] for name in groups[0]}
    for name, expected in expected_needs.items():
        needs = workflow["jobs"].get(name, {}).get("needs", [])
        observed = [needs] if isinstance(needs, str) else needs
        if observed != expected:
            errors.append(f"{name}: needs must be {expected}, observed {observed}")
    return {
        "schema_version": 1,
        "check_id": "release-ci-topology",
        "workflow": str(path),
        "independent_jobs": groups[0],
        "errors": errors,
        "result": "pass" if not errors else "fail",
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="check", required=True)
    oracle = sub.add_parser("oracle")
    oracle.add_argument("--root", type=Path, default=Path.cwd())
    oracle.add_argument("--receipts", type=Path, required=True)
    oracle.add_argument("--revision", required=True)
    oracle.add_argument("--report", type=Path, required=True)
    topology = sub.add_parser("topology")
    topology.add_argument(
        "--workflow", type=Path, default=Path(".github/workflows/parity.yml")
    )
    topology.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.check == "oracle":
        report = oracle_independence_report(args.root, args.receipts, args.revision)
    else:
        report = check_workflow_topology(args.workflow)
    write_report(report, args.report)
    print(
        json.dumps(
            {
                key: report[key]
                for key in report
                if key
                in {
                    "check_id",
                    "result",
                    "row_count",
                    "grounded_execution_rows",
                    "errors",
                }
            },
            sort_keys=True,
        )
    )
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
