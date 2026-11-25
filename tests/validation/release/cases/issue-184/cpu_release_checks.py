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
REQUIRED_CANDIDATE_CHECKS = (
    "release-candidate:license-inventory",
    "release-candidate:notice-inventory",
    "release-candidate:memory-contract",
    "release-candidate:sanitizer-configuration",
    "release-candidate:platform-matrix-shape",
    "release-candidate:hosted-evidence",
    "release-candidate:reproducible-build-digests",
)
REQUIRED_INSTALL_SUBCHECKS = (
    "clean_install",
    "upgrade_path",
    "cli_execution",
    "compat_api_execution",
    "public_examples",
    "representative_cpu_workloads",
    "cpu_extras",
    "truthful_gpu_metadata",
    "archive_inventory",
)


def _extract_receipt_fields(data):
    """Extract (source_dict, results_list, error_reason) fail-closed."""
    has_source = isinstance(data.get("source"), dict)
    has_legacy_source = "source_revision" in data or "source_dirty" in data
    if has_source and has_legacy_source:
        src = data["source"]
        if (
            "source_revision" in data
            and data.get("source_revision") != src.get("revision")
        ) or ("source_dirty" in data and data.get("source_dirty") != src.get("dirty")):
            return None, None, "conflicting source identity"
        source = src
    elif has_source:
        source = data["source"]
    elif data.get("acceptance_check") == "release-obligation-142" and has_legacy_source:
        source = {
            "revision": data.get("source_revision"),
            "dirty": data.get("source_dirty"),
        }
    else:
        source = {}

    results = data.get("results")
    if isinstance(results, list) and results:
        return source, results, None
    if (
        data.get("acceptance_check") == "release-obligation-142"
        and isinstance(data.get("checks"), dict)
        and data["checks"]
    ):
        normalized = []
        for cid, entry in sorted(data["checks"].items()):
            status = entry.get("status") if isinstance(entry, dict) else None
            normalized.append(
                {
                    "id": cid,
                    "status": status or "FAIL",
                    "supported_execution": status == "PASS",
                    "evidence_kind": "supported-execution",
                }
            )
        return source, normalized, None
    return source, [], None


def _receipts(paths, revision):
    accepted, rejected = [], []
    for path in paths:
        data = json.loads(path.read_bytes())
        source, results, err = _extract_receipt_fields(data)
        if err is not None:
            rejected.append((path.name, err))
            continue
        if source.get("revision") != revision or source.get("dirty") is not False:
            rejected.append((path.name, "stale or dirty receipt"))
            continue
        if not results:
            rejected.append((path.name, "no results"))
            continue
        failed = [
            row.get("id", "?")
            for row in results
            if row.get("status") not in {"PASS", "SKIPPED", "NOT_TESTED"}
            or (row.get("status") == "PASS" and row.get("supported_execution") is False)
        ]
        passed_ids = {
            row.get("id")
            for row in results
            if row.get("status") == "PASS" and row.get("supported_execution") is True
        }
        accepted.append(
            {
                "name": path.name,
                "check_id": data.get("check_id", ""),
                "results": len(results),
                "passed_ids": sorted(i for i in passed_ids if i),
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


def candidate_gaps(
    receipts,
    rejected,
    root=ROOT,
    *,
    candidate_reports=(),
    candidate_rejected=(),
    require_candidate_checks=False,
):
    gaps = [
        f"receipt {name}: {reason}" for name, reason in [*rejected, *candidate_rejected]
    ]
    failed = [
        f"{r['name']}:{c}" for r in [*receipts, *candidate_reports] for c in r["failed"]
    ]
    gaps.extend(failed)
    if not receipts:
        gaps.append("no exact-revision hosted parity or SBML receipt was consumed")
    if require_candidate_checks or candidate_reports:
        passed_candidate_ids = {
            cid
            for r in [*receipts, *candidate_reports]
            for cid in r.get("passed_ids", ())
        }
        for req_id in REQUIRED_CANDIDATE_CHECKS:
            if req_id not in passed_candidate_ids:
                gaps.append(f"missing or unverified candidate evidence: {req_id}")
    return sorted(set(gaps))


def _structured_install_gaps(receipt):
    gaps = []
    name = receipt["name"]
    if receipt["failed"]:
        gaps.extend(f"{name}:{cid}" for cid in receipt["failed"])
    passed = set(receipt.get("passed_ids", ()))
    for sub in REQUIRED_INSTALL_SUBCHECKS:
        if sub not in passed:
            gaps.append(f"install receipt {name} missing subcheck: {sub}")
    ref = receipt.get("reference", {})
    if ref.get("gpu_scope_deferred_to") != "#474":
        gaps.append(f"install receipt {name} missing explicit GPU deferral to #474")
    if ref.get("gpu_qualified_by_this_receipt") is not False:
        gaps.append(f"install receipt {name} must not claim GPU qualification")
    if not ref.get("artifact_sha256"):
        gaps.append(f"install receipt {name} missing artifact_sha256")
    return gaps


def installed_gaps(
    install_receipts,
    rejected,
    root=ROOT,
    *,
    require_structured_install=False,
):
    gaps = [f"receipt {name}: {reason}" for name, reason in rejected]
    gaps.extend(metadata_gaps(root))
    observed_wheels = set()
    observed_platforms = set()
    has_sdist = False
    for receipt in install_receipts:
        reference = receipt.get("reference", {})
        is_structured = (
            receipt.get("check_id") == "issue184-install-receipt"
            or require_structured_install
        )
        if is_structured:
            gaps.extend(_structured_install_gaps(receipt))
        plat_value = str(reference.get("platform", "")).lower()
        kind = str(reference.get("artifact_kind", "")).lower()
        for platform in PLATFORMS:
            if (
                platform in receipt["name"].lower()
                or platform == plat_value
                or platform in str(reference).lower()
            ):
                observed_platforms.add(platform)
                if kind == "wheel" or not kind:
                    observed_wheels.add(platform)
        if kind == "sdist" or "sdist" in receipt["name"].lower():
            has_sdist = True
    for platform in PLATFORMS:
        if platform not in observed_platforms or (
            require_structured_install and platform not in observed_wheels
        ):
            gaps.append(f"no exact-revision wheel/sdist install receipt for {platform}")
    if require_structured_install and not has_sdist:
        gaps.append("no exact-revision sdist install receipt consumed")
    return sorted(set(gaps))


def _result(check_id, gaps):
    return {
        "id": check_id,
        "status": "FAIL" if gaps else "PASS",
        "evidence_kind": "supported-execution",
        "supported_execution": not gaps,
        "related_issues": [184],
        "detail": (
            f"{len(gaps)} unresolved gap(s)"
            if gaps
            else "CPU release contract satisfied"
        ),
        "gaps": gaps,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--scientific-receipt", type=Path, action="append", default=[])
    parser.add_argument("--candidate-report", type=Path, action="append", default=[])
    parser.add_argument("--install-receipt", type=Path, action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.root, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=args.root, text=True
    )
    if head != args.revision or dirty:
        parser.error("CPU release evidence requires the requested clean revision")
    scientific, sci_rejected = _receipts(args.scientific_receipt, args.revision)
    cand_parsed, cand_rejected = _receipts(args.candidate_report, args.revision)
    installed, inst_rejected = _receipts(args.install_receipt, args.revision)
    candidate = candidate_gaps(
        scientific,
        sci_rejected,
        args.root,
        candidate_reports=cand_parsed,
        candidate_rejected=cand_rejected,
        require_candidate_checks=True,
    )
    artifacts = installed_gaps(
        installed,
        inst_rejected,
        args.root,
        require_structured_install=True,
    )
    report = {
        "schema_version": 1,
        "source": {"revision": args.revision, "dirty": False},
        "check_id": "issue-184-cpu-release",
        "scope": "CPU milestone; GPU scope is deferred to #474 and is not reported as passed",
        "receipts": scientific + cand_parsed + installed,
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
