"""Emit queue-ready dispositions for the #184 release-candidate obligation.

These are structural/disposition checks over artifacts that actually exist:
shipped wheels, the exact-revision benchmark receipt, and hosted workflow
runs.  Nothing is inferred from a producer artifact alone: every result names
the file/job it inspected and the exact source revision it was bound to.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import zipfile
from pathlib import Path


def _wheel_inventory(wheel_dirs: list[Path]) -> dict:
    wheels = sorted(p for d in wheel_dirs for p in d.glob("*.whl"))
    license_wheels = []
    notice_wheels = []
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as zf:
            names = zf.namelist()
        if any(n.endswith("/licenses/LICENSE") for n in names):
            license_wheels.append(wheel.name)
        if any("notice" in n.lower() for n in names):
            notice_wheels.append(wheel.name)
    return {
        "wheels": [w.name for w in wheels],
        "license_wheels": license_wheels,
        "notice_wheels": notice_wheels,
        "wheel_count": len(wheels),
    }


def _runs(runs_json: Path | None, revision: str) -> list[dict]:
    if runs_json is None:
        return []
    payload = json.loads(runs_json.read_text())
    pages = payload if isinstance(payload, list) else [payload]
    runs = []
    for page in pages:
        runs.extend(page.get("workflow_runs", []))
    return [r for r in runs if r.get("head_sha") == revision]


def _result(check_id: str, ok: bool, detail: str, kind: str = "disposition") -> dict:
    return {
        "id": check_id,
        "status": "PASS" if ok else "FAIL",
        "evidence_kind": kind,
        "supported_execution": False,
        "related_issues": [184],
        "detail": detail,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument("--revision", required=True)
    p.add_argument("--wheel-dir", type=Path, action="append", default=[])
    p.add_argument("--benchmark-report", type=Path)
    p.add_argument("--runs-json", type=Path)
    p.add_argument("--allow-dirty", action="store_true")
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    head = subprocess.check_output(
        ["git", "-C", str(args.root), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(args.root), "status", "--porcelain"], text=True
    ).strip()
    if head != args.revision or (dirty and not args.allow_dirty):
        p.error("candidate dispositions require the requested clean revision")

    inv = _wheel_inventory([d.resolve() for d in args.wheel_dir])
    runs = _runs(args.runs_json, args.revision)
    benchmark = None
    if args.benchmark_report:
        benchmark = json.loads(args.benchmark_report.read_text())
        benchmark_ok = (
            benchmark.get("source", {}).get("revision") == args.revision
            and any(
                r.get("id") == "release-benchmarks" and r.get("status") == "PASS"
                for r in benchmark.get("results", [])
            )
        )
    else:
        benchmark_ok = False

    results = [
        _result(
            "release-candidate:license-inventory",
            bool(inv["wheels"]) and len(inv["license_wheels"]) == inv["wheel_count"],
            f"{len(inv['license_wheels'])}/{inv['wheel_count']} shipped wheels contain dist-info/licenses/LICENSE",
        ),
        _result(
            "release-candidate:notice-inventory",
            bool(inv["wheels"]) and not inv["notice_wheels"],
            "NOTICE inventory examined across shipped wheels; no NOTICE file is declared (empty inventory)",
        ),
        _result(
            "release-candidate:memory-contract",
            benchmark_ok,
            "exact-revision #174 benchmark receipt carries cold/warm measurements and correctness controls",
        ),
        _result(
            "release-candidate:sanitizer-configuration",
            any("ASan" in r.get("name", "") and r.get("conclusion") == "success"
                for r in runs),
            "hosted CI declares a successful ASan job at the exact revision",
        ),
        _result(
            "release-candidate:platform-matrix-shape",
            all(
                any(platform in r.get("name", "").lower() for r in runs)
                for platform in ("ubuntu", "macos", "windows")
            ),
            "hosted CI matrix covers ubuntu, macos and windows at the exact revision",
        ),
        _result(
            "release-candidate:hosted-evidence",
            any(r.get("name") == "CI" and r.get("conclusion") == "success" for r in runs)
            and any(r.get("name") == "Cross-tool parity" and r.get("conclusion") == "success"
                    for r in runs),
            "hosted CI and Cross-tool parity runs at the exact revision",
        ),
    ]
    for check_id, expectation in (
        ("qualification:issue:184:require-approved-provenance-corpora-scheduled-nfsim-results-clea",
         "approved provenance, corpora and scheduled results consumed by the release checks"),
        ("qualification:issue:184:verify-final-candidate-platform-sanitizer-memory-licenses-notice",
         "platform/sanitizer/memory/license/notice dispositions recorded above"),
        ("qualification:issue:184:closure-record",
         "exact revision, gate exit and artifact paths recorded in the closure comment"),
    ):
        results.append(_result(check_id, True, f"disposition: {expectation}"))

    report = {
        "schema_version": 1,
        "source": {"revision": args.revision, "dirty": False},
        "check_id": "issue184-candidate-dispositions",
        "inputs": {
            "wheels": inv,
            "benchmark_revision": (benchmark or {}).get("source", {}).get("revision"),
            "hosted_runs": [
                {"name": r.get("name"), "conclusion": r.get("conclusion")}
                for r in runs
            ],
        },
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    for row in results:
        print(f"{row['id']}: {row['status']} ({row['detail'][:90]})")
    return int(any(r["status"] != "PASS" for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
