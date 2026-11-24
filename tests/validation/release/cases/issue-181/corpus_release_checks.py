"""Fail-closed consumers for the three release obligations of issue #181.

Tier membership and per-case identities are structural contracts.  A scientific
result is counted only from an exact-revision independent report, and a partial
shard counts only when its replay receipt shows that completed artifacts were
reused and stale artifacts were identified and discarded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
TIERS = ("s", "p", "nf", "expr", "x", "b")
LOSS = {"unsupported", "dropped", "approximated", "untranslated", "error"}


def _yaml(path):
    import yaml

    return yaml.safe_load(path.read_text())


def coverage_gaps(root=ROOT):
    gaps = []
    selection = json.loads((root / "provenance/corpus/selection.json").read_text())
    if selection.get("selection_status") != "approved":
        gaps.append("corpus selection is not approved under DECISIONS.md item 11")
    tiers = selection.get("tiers", {})
    for tier in TIERS:
        values = tiers.get(tier)
        if not isinstance(values, list) or not values:
            gaps.append(f"tier {tier} is empty or missing")
        elif sorted(set(values)) != sorted(values):
            gaps.append(f"tier {tier} has duplicate or unsorted members")
    records = {row["id"]: row for row in selection.get("records", [])}
    for tier, values in tiers.items():
        for case_id in values:
            row = records.get(case_id)
            if row is None:
                gaps.append(f"tier {tier} references unknown case {case_id}")
                continue
            if not str(row.get("sha256", "")).startswith("sha256:"):
                gaps.append(f"{case_id}: missing source digest")
            if tier not in row.get("tiers", []):
                gaps.append(f"{case_id}: record disagrees with tier {tier}")
    matrix = _yaml(root / "provenance/capability-matrix.yml")
    if len(matrix["rows"]) != 997:
        gaps.append(f"matrix row count changed: {len(matrix['rows'])}")
    return gaps


def _observed_results(reports, revision):
    observed = {}
    for report in reports:
        source = report.get("source", {})
        if source.get("revision") != revision or source.get("dirty") is not False:
            continue
        for result in report.get("results", []):
            key = result.get("id")
            if not key or result.get("aggregate"):
                continue
            status = result.get("status")
            if key.startswith("corpus-case[") and status == "PASS":
                if (
                    result.get("supported_execution") is not True
                    or result.get("evidence_kind") != "supported-execution"
                ):
                    status = "UNQUALIFIED_PASS"
            observed.setdefault(key, set()).add(status)
    return observed


def result_gaps(reports, revision, replay_receipts, root=ROOT):
    gaps = []
    observed = _observed_results(reports, revision)
    selection = json.loads((root / "provenance/corpus/selection.json").read_text())
    all_cases = [row["id"] for row in selection["records"]]
    for case_id in all_cases:
        identity = f"corpus-case[{case_id}]"
        if observed.get(identity) != {"PASS"}:
            gaps.append(
                f"{case_id}: no exact-revision independently checked case result"
            )
    for key, statuses in observed.items():
        if len(statuses) > 1:
            gaps.append(f"{key}: conflicting results {sorted(statuses)}")
        if statuses & {"FAIL", "HARNESS_ERROR", "TIMEOUT"}:
            gaps.append(
                f"{key}: unresolved {sorted(statuses & {'FAIL', 'HARNESS_ERROR', 'TIMEOUT'})}"
            )
    if not replay_receipts:
        gaps.append("no interrupted-run per-case replay receipt was consumed")
    for receipt in replay_receipts:
        if receipt.get("source_revision") != revision:
            gaps.append(
                "replay receipt revision differs from the qualification revision"
            )
        actions = receipt.get("phases", {}).get("resume", {}).get("actions", {})
        if "reused" not in actions.values():
            gaps.append("replay did not reuse a completed per-case artifact")
        if receipt.get("phases", {}).get("stale_control", {}).get("action") != (
            "stale-discarded-and-executed"
        ):
            gaps.append("stale or partial artifact was not identified and discarded")
    return gaps


def _result(check_id, gaps):
    return {
        "id": check_id,
        "status": "FAIL" if gaps else "PASS",
        "evidence_kind": "supported-execution",
        "supported_execution": not gaps,
        "related_issues": [181],
        "detail": f"{len(gaps)} unresolved gap(s)" if gaps else "contract satisfied",
        "gaps": gaps,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--case-report", type=Path, action="append", default=[])
    parser.add_argument("--replay-receipt", type=Path, action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.root, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=args.root, text=True
    )
    if head != args.revision or dirty:
        parser.error("corpus acceptance requires the requested clean revision")
    reports = [json.loads(p.read_bytes()) for p in args.case_report]
    receipts = [json.loads(p.read_bytes()) for p in args.replay_receipt]
    coverage = coverage_gaps(args.root)
    results = result_gaps(reports, args.revision, receipts, args.root)
    report = {
        "schema_version": 1,
        "source": {"revision": args.revision, "dirty": False},
        "check_id": "issue-181-corpus",
        "inputs": [
            {"file": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in [*args.case_report, *args.replay_receipt]
        ],
        "results": [
            _result("release-corpus-coverage", coverage),
            _result("release-corpus-results", results),
            _result(
                "release-obligation-181",
                [g for g in coverage + results if g],
            ),
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in report["results"]:
        print(f"{row['id']}: {row['status']} ({len(row['gaps'])} gaps)")
    return int(any(row["status"] == "FAIL" for row in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
