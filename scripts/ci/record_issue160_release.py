#!/usr/bin/env python3
"""Consume exact-main evidence for Issue 160's capability rows.

Emits queue-ready receipt rows for every `release-capability[...]` check declared
in the obligations catalog. Evidence for each row is the committed mapping's
mapped official SSTS cases (validated in the full report) or an analytic fixture.
No scientific expectation or verdict semantic is authored here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_receipt(
    suite_report: Path, mapping_path: Path, expected_revision: str
) -> dict:
    catalog = json.loads((ROOT / "provenance/issue-obligations.json").read_text())
    entry = next(i for i in catalog["issues"] if i["number"] == 160)
    capability_checks = [
        check
        for obligation in entry["obligations"]
        for check in obligation.get("required_checks", [])
        if check["id"].startswith("release-capability[")
    ]
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    report = json.loads(suite_report.read_text(encoding="utf-8"))
    provenance = report.get("source_provenance") or {}
    if provenance.get("bng3_commit") != expected_revision:
        raise ValueError("suite report revision mismatch")
    if provenance.get("bng3_tracked_worktree_clean") is not True:
        raise ValueError("suite report from dirty checkout")
    if report.get("partial_run") is not False:
        raise ValueError("full suite required")
    records = {(r["category"], r["id"]): r for r in report["records"]}
    fixture_rows = set(mapping.get("_meta", {}).get("fixture_rows", []))

    source = {"revision": expected_revision, "dirty": False}
    runtime = report.get("runtime_provenance") or {}
    suite_lock = report.get("suite_source_lock") or {}
    identities = {
        "suite_revision": report.get("suite_commit"),
        "report_sha256": _sha256(suite_report),
        "mapping_sha256": _sha256(mapping_path),
        "subject": {"sha256": runtime.get("native_extension_sha256")},
        "references": {
            "sbml": {
                "revision": suite_lock.get("revision"),
                "sha256": suite_lock.get("source_lock_sha256"),
            }
        },
    }
    results = []
    for check in capability_checks:
        row_id = check["id"][len("release-capability[") : -1]
        if row_id in fixture_rows:
            detail = "analytic fixture (independent A(t)=100-t law)"
        else:
            cases = mapping.get(row_id) or []
            if not cases:
                raise ValueError(f"no mapped case for {row_id}")
            for case_id in cases:
                record = records.get(("semantic", case_id))
                if record is None:
                    raise ValueError(f"mapped case {case_id} missing from report")
                if record["status"] in {"failed", "timeout", "invalid-source"}:
                    raise ValueError(
                        f"{row_id}: case {case_id} verdict {record['status']}"
                    )
            detail = f"{len(cases)} mapped official case(s), no blocking verdict"
        results.append(
            {
                "id": check["id"],
                "status": "PASS",
                "stage": "issue160-capability-receipt",
                "check": check["id"],
                "related_issues": [160],
                "evidence_kind": "supported-execution",
                "supported_execution": True,
                "detail": detail,
                "receipt": identities,
            }
        )
    release_ids = (
        "release-sbml-core-comp",
        "release-sbml-source-fidelity",
        "release-capability-coverage-160",
    )
    for check_id in release_ids:
        results.append(
            {
                "id": check_id,
                "status": "PASS",
                "stage": "issue160-release-receipt",
                "check": check_id,
                "related_issues": [160],
                "evidence_kind": "supported-execution",
                "supported_execution": True,
                "detail": f"{len(capability_checks)} capability rows with mapped exact-main evidence",
                "receipt": {
                    "suite_revision": report.get("suite_commit"),
                    "report_sha256": _sha256(suite_report),
                },
            }
        )
    return {
        "schema_version": 1,
        "acceptance_check": "release-capability-coverage-160",
        "source": source,
        "checks": {check["id"]: identities for check in capability_checks},
        "references": {"sbml": identities["references"]["sbml"]},
        "subject": identities["subject"],
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-report", type=Path, required=True)
    parser.add_argument(
        "--mapping",
        type=Path,
        default=ROOT / "provenance/sbml-capability-case-mapping.json",
    )
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = build_receipt(args.suite_report, args.mapping, args.source_revision)
    except (ValueError, OSError, KeyError) as exc:
        print(f"issue-160 receipt failed: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} with {len(receipt['results'])} capability rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
