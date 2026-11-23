"""Consume exact-revision source and behavior evidence for #180."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPSTREAMS = {"bionetgen", "nfsim", "pybionetgen"}


def coverage_report(rows, lock, reports, revision):
    required = {
        row["id"]: row["upstream"].split(":", 1)[0]
        for row in rows
        if row["upstream"].split(":", 1)[0] in UPSTREAMS
    }
    observed = defaultdict(set)
    for report in reports:
        source = report.get("source", {})
        if source.get("revision") != revision or source.get("dirty") is not False:
            continue
        for result in report.get("results", []):
            check_id = result.get("id", "")
            row_id = check_id.removeprefix("release-capability[").removesuffix("]")
            upstream = required.get(row_id)
            if upstream is None or check_id != f"release-capability[{row_id}]":
                continue
            references = report.get("references", {})
            if result.get("oracle_kind") == "analytic":
                reference = references.get("analytic", {})
                if (
                    not isinstance(reference, dict)
                    or not reference.get("law")
                    or not re.fullmatch(
                        r"[0-9a-f]{64}", str(reference.get("source_sha256"))
                    )
                ):
                    continue
            else:
                reference = references.get(upstream, {})
                if (
                    not isinstance(reference, dict)
                    or reference.get("revision")
                    != lock["sources"][upstream]["revision"]
                ):
                    continue
            status = result.get("status")
            if (
                result.get("aggregate")
                or result.get("evidence_kind") != "supported-execution"
                or status not in {"PASS", "FAIL"}
                or (status == "PASS" and result.get("supported_execution") is not True)
            ):
                continue
            if status == "PASS" and any(
                isinstance(diagnostic, dict)
                and diagnostic.get("severity")
                in {"unsupported", "dropped", "approximated", "error", "untranslated"}
                for diagnostic in result.get("diagnostics", [])
            ):
                continue
            observed[row_id].add(status)
    conflicts = {row for row, outcomes in observed.items() if len(outcomes) > 1}
    return {
        "required_rows": len(required),
        "observed_rows": {
            row: next(iter(observed[row]))
            for row in sorted(observed.keys() - conflicts)
        },
        "missing_rows": sorted(required.keys() - observed.keys()),
        "conflicting_rows": sorted(conflicts),
    }


def canonical_gaps(coverage):
    gaps = []
    if not coverage["required_rows"] or coverage["missing_rows"]:
        gaps.append("Canonical rows lack an exact-revision independent case result.")
    if coverage["conflicting_rows"]:
        gaps.append("Exact-revision case results disagree for canonical rows.")
    failed = [
        row_id
        for row_id, status in coverage["observed_rows"].items()
        if status == "FAIL"
    ]
    if failed:
        gaps.append(f"Canonical behavior failed: {', '.join(failed)}.")
    return gaps


def _check_result(check_id, gaps):
    return {
        "id": check_id,
        "status": "FAIL" if gaps else "PASS",
        "evidence_kind": "supported-execution",
        "supported_execution": not gaps,
        "related_issues": [180],
        "detail": " ".join(gaps) if gaps else "Reconciliation evidence consumed.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--pin-report", type=Path, required=True)
    parser.add_argument("--behavior-report", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
    if head.strip() != args.revision or dirty:
        parser.error("reconciliation acceptance requires the requested clean revision")

    source = {"revision": args.revision, "dirty": False}
    pin_report = json.loads(args.pin_report.read_bytes())
    lock = json.loads((ROOT / "provenance/upstreams.lock.yml").read_bytes())
    matrix = json.loads((ROOT / "provenance/capability-matrix.yml").read_bytes())
    behavior_reports = [json.loads(path.read_bytes()) for path in args.behavior_report]
    coverage = coverage_report(matrix["rows"], lock, behavior_reports, args.revision)
    issues = []
    pins = pin_report.get("sources", {})
    if (
        pin_report.get("source") != source
        or pin_report.get("errors") != []
        or set(pins) != UPSTREAMS
        or any(
            details.get("checkout_revision") != lock["sources"][name]["revision"]
            or details.get("errors") != []
            for name, details in pins.items()
        )
    ):
        issues.append("Current upstream pin evidence is absent or invalid.")
    surfaces = pin_report.get("source_inventory_audit", {})
    if set(surfaces) != {"bng2_builtins", "nfsim_options", "pybionetgen_options"}:
        issues.append("The source inventory audit is incomplete.")
    for name, surface in surfaces.items():
        if surface.get("missing_rows") or surface.get("unexpected_rows"):
            issues.append(f"{name}: independent source inventory has unmatched rows.")
    if pin_report.get("source_symbol_audit", {}).get("unresolved_rows") != {}:
        issues.append("The pinned source symbol audit has unresolved rows.")
    issues.extend(canonical_gaps(coverage))

    results = [_check_result("release-reconciliation", issues)]
    semantic_deltas_without_case = []
    for name in sorted(UPSTREAMS):
        ledger = json.loads(
            (ROOT / f"provenance/reconciliation/{name}.yml").read_bytes()
        )
        for entry in ledger["entries"]:
            if entry["classification"] == "not-applicable":
                continue
            check_id = f"reconciliation-delta[{name},{entry['source_revision']}]"
            found = any(
                report.get("source") == source
                and isinstance(report.get("references", {}).get(name), dict)
                and report["references"][name].get("revision")
                == lock["sources"][name]["revision"]
                and any(
                    result.get("id") == check_id
                    and result.get("status") == "PASS"
                    and result.get("supported_execution") is True
                    and result.get("evidence_kind") == "supported-execution"
                    and not result.get("aggregate")
                    for result in report.get("results", [])
                )
                for report in behavior_reports
            )
            if not found:
                semantic_deltas_without_case.append(check_id)
    if semantic_deltas_without_case:
        issues.append("Substantive source changes lack independent case results.")
    results.append(_check_result("release-obligation-180", issues))
    report = {
        "schema_version": 1,
        "source": source,
        "references": pin_report.get("references", {}),
        "inputs": [
            {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in [args.pin_report, *args.behavior_report]
        ],
        "coverage": coverage,
        "unverified_deltas": semantic_deltas_without_case,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for issue in issues:
        print(issue)
    print(
        f"source behavior evidence: {len(coverage['observed_rows'])} of "
        f"{coverage['required_rows']} required canonical rows"
    )
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
