"""Fail-closed consumer for the CPU release qualification (#184).

It joins exact-revision hosted receipts from the independent parity and SBML
lanes with the installed-artifact and package-metadata contracts.  A failed or
missing receipt is retained as a failed result; GPU scope is explicitly deferred
to #474 and is never inferred from a compile-only or fallback check.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
PLATFORMS = ("linux", "macos", "windows")
CPU_EXTRAS = ("legacy", "plotting", "jax", "notebook", "full")


def _receipts(paths, revision):
    accepted, rejected = [], []
    for path in paths:
        data = json.loads(path.read_bytes())
        source = data.get("source", {})
        if source.get("revision") != revision or source.get("dirty") is not False:
            rejected.append((path.name, "stale or dirty receipt"))
            continue
        results = data.get("results", [])
        if not results:
            rejected.append((path.name, "no results"))
            continue
        failed = [
            row.get("id", "?")
            for row in results
            if row.get("status") not in {"PASS", "SKIPPED", "NOT_TESTED"}
            or (
                row.get("status") == "PASS"
                and row.get("supported_execution") is False
            )
        ]
        accepted.append(
            {
                "name": path.name,
                "results": len(results),
                "failed": failed,
                "reference": data.get("references", {}),
            }
        )
    return accepted, rejected


def metadata_gaps(root=ROOT):
    gaps = []
    pyproject = (root / "pyproject.toml").read_text()
    for extra in CPU_EXTRAS:
        if not re.search(rf"^{extra}\s*=\s*\[", pyproject, re.M):
            gaps.append(f"CPU extra {extra} is absent from pyproject.toml")
    if re.search(r"^gpu\s*=\s*\[", pyproject, re.M):
        gaps.append("pyproject declares a GPU extra; #474 owns GPU qualification")
    decisions = (root / "docs/DECISIONS.md").read_text()
    if "#474" not in decisions or "separate GPU workstream" not in decisions:
        gaps.append("GPU deferral to #474 is not recorded in DECISIONS.md")
    readme = (root / "README.md").read_text()
    if "general NFnext GPU support" not in readme or "does not imply" not in readme:
        gaps.append("README does not limit GPU claims to the CPU milestone")
    return gaps


def candidate_gaps(receipts, rejected, root=ROOT):
    gaps = [f"receipt {name}: {reason}" for name, reason in rejected]
    failed = [f"{r['name']}:{c}" for r in receipts for c in r["failed"]]
    gaps.extend(failed)
    if not receipts:
        gaps.append("no exact-revision hosted parity or SBML receipt was consumed")
    return sorted(set(gaps))


def installed_gaps(install_receipts, rejected, root=ROOT):
    gaps = [f"receipt {name}: {reason}" for name, reason in rejected]
    gaps.extend(metadata_gaps(root))
    observed = set()
    for receipt in install_receipts:
        reference = receipt.get("reference", {})
        for platform in PLATFORMS:
            if platform in receipt["name"].lower() or platform in str(reference):
                observed.add(platform)
    for platform in PLATFORMS:
        if platform not in observed:
            gaps.append(f"no exact-revision wheel/sdist install receipt for {platform}")
    return sorted(set(gaps))


def _result(check_id, gaps):
    return {
        "id": check_id,
        "status": "FAIL" if gaps else "PASS",
        "evidence_kind": "supported-execution",
        "supported_execution": not gaps,
        "related_issues": [184],
        "detail": f"{len(gaps)} unresolved gap(s)" if gaps else "CPU release contract satisfied",
        "gaps": gaps,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--scientific-receipt", type=Path, action="append", default=[])
    parser.add_argument("--install-receipt", type=Path, action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.root, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=args.root, text=True)
    if head != args.revision or dirty:
        parser.error("CPU release evidence requires the requested clean revision")
    scientific, sci_rejected = _receipts(args.scientific_receipt, args.revision)
    installed, inst_rejected = _receipts(args.install_receipt, args.revision)
    candidate = candidate_gaps(scientific, sci_rejected, args.root)
    artifacts = installed_gaps(installed, inst_rejected, args.root)
    report = {
        "schema_version": 1,
        "source": {"revision": args.revision, "dirty": False},
        "check_id": "issue-184-cpu-release",
        "scope": "CPU milestone; GPU scope is deferred to #474 and is not reported as passed",
        "receipts": scientific + installed,
        "results": [
            _result("release-candidate", candidate),
            _result("release-installed-artifacts", artifacts),
            _result("release-obligation-184", sorted(set(candidate + artifacts))),
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in report["results"]:
        print(f"{row['id']}: {row['status']} ({len(row['gaps'])} gaps)")
    return int(any(row["status"] == "FAIL" for row in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
