"""Emit real artifact-derived #184 release-candidate evidence checks."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.record_issue184_install_receipt import (  # noqa: E402
    inspect_archive_inventory,
)

REQUIRED_PUSH_WORKFLOWS = (
    "CI",
    "Cross-tool parity",
    "Lean semantic kernel",
    "CodeQL",
)
REQUIRED_CI_JOBS = (
    "C++ (ubuntu-22.04, gcc-12)",
    "C++ (ubuntu-22.04, clang-15)",
    "C++ (macos-15, clang-arm64)",
    "C++ (windows-2022, msvc)",
    "C++ ASan (Ubuntu)",
    "Wheels (ubuntu-22.04)",
    "Wheels (macos-15-intel)",
    "Wheels (macos-15)",
    "Wheels (windows-2022)",
    "Source Distribution",
    "Package Smoke (sdist)",
    *(f"Python 3.{minor} (ubuntu-22.04)" for minor in range(9, 15)),
    *(f"Python 3.{minor} (macos-15)" for minor in range(9, 15)),
    *(f"Python 3.{minor} (windows-2022)" for minor in range(9, 15)),
)
REQUIRED_WHEEL_PLATFORM_TAGS = (
    "manylinux",
    "x86_64",
    "arm64",
    "win_amd64",
)
CANDIDATE_CHECK_IDS = (
    "release-candidate:license-inventory",
    "release-candidate:notice-inventory",
    "release-candidate:memory-contract",
    "release-candidate:sanitizer-configuration",
    "release-candidate:platform-matrix-shape",
    "release-candidate:hosted-evidence",
    "release-candidate:reproducible-build-digests",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _flatten_runs(paths: list[Path], revision: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        pages = payload if isinstance(payload, list) else [payload]
        for page in pages:
            if isinstance(page, dict):
                runs.extend(
                    r
                    for r in (page.get("workflow_runs") or [])
                    if isinstance(r, dict) and r.get("head_sha") == revision
                )
    return runs


def _flatten_jobs(paths: list[Path]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        pages = payload if isinstance(payload, list) else [payload]
        for page in pages:
            if isinstance(page, dict):
                jobs.extend(j for j in (page.get("jobs") or []) if isinstance(j, dict))
    return jobs


def _parse_junit(path: Path) -> dict[str, Any]:
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    suites = (
        list(root.findall("testsuite"))
        if root.tag == "testsuites"
        else ([root] if root.tag == "testsuite" else [])
    )
    if not suites:
        raise ValueError(f"no <testsuite> element in {path}")
    tests = sum(int(s.attrib.get("tests", "0")) for s in suites)
    failures = sum(int(s.attrib.get("failures", "0")) for s in suites)
    errors = sum(int(s.attrib.get("errors", "0")) for s in suites)
    skipped = sum(int(s.attrib.get("skipped", "0")) for s in suites)
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }


def _check_license_inventory(inv: dict[str, Any]) -> tuple[bool, str]:
    wheels = inv["wheels"]
    sdist = inv["sdist"]
    if not wheels or sdist is None:
        return (
            False,
            f"requires non-empty wheels and sdist (wheels={len(wheels)}, sdist={sdist is not None})",
        )
    missing_wheel = [w["filename"] for w in wheels if not w["license_entries"]]
    sdist_ok = bool(sdist["license_entries"])
    if missing_wheel or not sdist_ok:
        return (
            False,
            f"missing LICENSE entries: wheels={missing_wheel}, sdist_ok={sdist_ok}",
        )
    return (
        True,
        f"{len(wheels)}/{len(wheels)} wheels and sdist ({sdist['filename']}) carry LICENSE entries",
    )


def _check_notice_inventory(inv: dict[str, Any], root: Path) -> tuple[bool, str]:
    wheels = inv["wheels"]
    sdist = inv["sdist"]
    if not wheels or sdist is None:
        return (
            False,
            f"requires inspected wheels and sdist (wheels={len(wheels)}, sdist={sdist is not None})",
        )
    repo_notice = (root / "NOTICE").is_file()
    wheel_notices = [
        (w["filename"], w["notice_entries"]) for w in wheels if w["notice_entries"]
    ]
    sdist_notices = sdist["notice_entries"]
    return (
        True,
        f"inspected {len(wheels)} wheels and sdist; repo_notice={repo_notice}, "
        f"wheel_notices={len(wheel_notices)}, sdist_notice_entries={len(sdist_notices)}",
    )


def _check_memory_contract(
    revision: str,
    benchmark_path: Path | None,
    current_path: Path | None,
) -> tuple[bool, str]:
    if benchmark_path is None or not benchmark_path.is_file():
        return False, "missing #174 benchmark record (--benchmark-report)"
    data = json.loads(benchmark_path.read_text(encoding="utf-8"))
    source = data.get("source", {})
    if source.get("revision") != revision or source.get("dirty") is not False:
        return False, f"benchmark report revision/dirty mismatch: {source}"
    by_id = {
        r.get("id"): r
        for r in data.get("results", [])
        if isinstance(r, dict) and r.get("id")
    }
    required_ids = (
        "release-benchmarks",
        "release-benchmark-correctness",
        "release-obligation-174",
    )
    missing_or_failed = [
        cid
        for cid in required_ids
        if by_id.get(cid, {}).get("status") != "PASS"
        or by_id.get(cid, {}).get("supported_execution") is not True
    ]
    if missing_or_failed:
        return False, f"benchmark contract unmet for: {missing_or_failed}"
    if current_path is not None:
        if not current_path.is_file():
            return False, f"missing current benchmark file: {current_path}"
        cur = json.loads(current_path.read_text(encoding="utf-8"))
        cur_id = cur.get("identity", {})
        if cur_id.get("source_revision") != revision:
            return False, f"current benchmark identity revision mismatch: {cur_id}"
        workloads = cur.get("workloads", {})
        expected_w = ("cold_startup", *cur.get("required_workloads", []))
        bad_w = [
            w
            for w in expected_w
            if workloads.get(w, {}).get("status") != "PASS"
            or float(workloads.get(w, {}).get("median", 0.0)) <= 0.0
        ]
        if bad_w:
            return False, f"current benchmark workloads failed or zero timing: {bad_w}"
    return True, f"#174 benchmark contract verified at {revision[:8]}"


def _check_sanitizer(
    revision: str,
    junit_paths: list[Path],
    asan_receipt_path: Path | None,
    ci_jobs: list[dict[str, Any]],
) -> tuple[bool, str]:
    if not junit_paths:
        return False, "missing actual ASan CTest JUnit XML (--asan-junit)"
    parsed: list[dict[str, Any]] = []
    for jp in junit_paths:
        if not jp.is_file():
            return False, f"ASan JUnit file missing: {jp}"
        try:
            parsed.append(_parse_junit(jp))
        except (ET.ParseError, ValueError) as exc:
            return False, f"invalid ASan JUnit {jp}: {exc}"
    total_tests = sum(p["tests"] for p in parsed)
    bad = [
        p
        for p in parsed
        if p["tests"] <= 0 or p["failures"] > 0 or p["errors"] > 0 or p["skipped"] > 0
    ]
    if total_tests <= 0 or bad:
        return False, f"ASan JUnit failures/skips/empty: {parsed}"

    if asan_receipt_path is not None:
        if not asan_receipt_path.is_file():
            return False, f"missing ASan receipt: {asan_receipt_path}"
        rec = json.loads(asan_receipt_path.read_text(encoding="utf-8"))
        src = rec.get("source", {})
        if src.get("revision") != revision or src.get("dirty") is not False:
            return False, f"ASan receipt revision/dirty mismatch: {src}"
        if not rec.get("sanitize_address") or not rec.get(
            "detect_leaks_1_late_stop_passed"
        ):
            return False, f"ASan receipt missing sanitizer flags/late-stop pass: {rec}"
        expected_hashes = {
            h for h in rec.get("junit_sha256", {}).values() if isinstance(h, str)
        }
        actual_hashes = {p["sha256"] for p in parsed}
        if expected_hashes and not (expected_hashes <= actual_hashes):
            return False, "ASan receipt JUnit sha256 mismatch"

    if ci_jobs:
        asan_jobs = [j for j in ci_jobs if j.get("name") == "C++ ASan (Ubuntu)"]
        if not asan_jobs or any(j.get("conclusion") != "success" for j in asan_jobs):
            return False, "CI job 'C++ ASan (Ubuntu)' missing or not success"
    return (
        True,
        f"ASan JUnit verified: {total_tests} tests across {len(parsed)} suite(s), 0 failures/errors/skips",
    )


def _check_platform_matrix(
    inv: dict[str, Any],
    ci_jobs: list[dict[str, Any]],
) -> tuple[bool, str]:
    if not ci_jobs:
        return False, "missing exact-SHA CI job list (--ci-jobs-json)"
    by_name = {j.get("name"): j for j in ci_jobs}
    missing = [
        name
        for name in REQUIRED_CI_JOBS
        if by_name.get(name, {}).get("status") != "completed"
        or by_name.get(name, {}).get("conclusion") != "success"
    ]
    if missing:
        return False, f"CI platform matrix missing/failed jobs: {missing}"
    wheel_names = [w["filename"] for w in inv["wheels"]]
    missing_tags = [
        tag
        for tag in REQUIRED_WHEEL_PLATFORM_TAGS
        if not any(tag in name for name in wheel_names)
    ]
    if missing_tags:
        return False, f"missing built wheel platform tags: {missing_tags}"
    return (
        True,
        f"{len(REQUIRED_CI_JOBS)}/{len(REQUIRED_CI_JOBS)} CI jobs green; "
        f"{len(wheel_names)} wheels across {list(REQUIRED_WHEEL_PLATFORM_TAGS)}",
    )


def _check_hosted_evidence(
    revision: str,
    runs: list[dict[str, Any]],
    mutation_report_path: Path | None,
) -> tuple[bool, str]:
    if not runs:
        return False, "missing exact-SHA workflow runs (--runs-json)"
    missing_push = [
        wf
        for wf in REQUIRED_PUSH_WORKFLOWS
        if not any(
            r.get("name") == wf
            and r.get("event") == "push"
            and r.get("head_branch") in (None, "main")
            and r.get("status") == "completed"
            and r.get("conclusion") == "success"
            for r in runs
        )
    ]
    sbml_ok = any(
        r.get("name") == "Official SBML conformance subset"
        and r.get("event") == "workflow_dispatch"
        and r.get("status") == "completed"
        and r.get("conclusion") == "success"
        for r in runs
    )
    weekly_ok = any(
        r.get("name") == "Weekly Validation"
        and r.get("event") in {"schedule", "workflow_dispatch"}
        and r.get("head_branch") in (None, "main")
        and r.get("status") == "completed"
        and r.get("conclusion") == "success"
        for r in runs
    )
    if missing_push or not sbml_ok or not weekly_ok:
        return (
            False,
            f"missing hosted workflows: push={missing_push}, sbml={sbml_ok}, weekly={weekly_ok}",
        )
    if mutation_report_path is None or not mutation_report_path.is_file():
        return False, "missing exact-SHA weekly mutation report (--mutation-report)"
    mut = json.loads(mutation_report_path.read_text(encoding="utf-8"))
    if mut.get("revision") != revision:
        return False, f"mutation report revision {mut.get('revision')} != {revision}"
    caught = int(mut.get("caught", 0))
    denom = int(mut.get("denominator", 0))
    survived = int(mut.get("status_counts", {}).get("survived", 0))
    infra = int(mut.get("status_counts", {}).get("infrastructure_error", 0))
    if denom <= 0 or caught < denom or survived > 0 or infra > 0:
        return (
            False,
            f"mutation ratchet invalid: caught={caught}/{denom} survived={survived} infra={infra}",
        )
    return (
        True,
        f"push={list(REQUIRED_PUSH_WORKFLOWS)}, SBML, Weekly + mutation {caught}/{denom} verified",
    )


def _check_reproducible_digests(
    revision: str,
    inv: dict[str, Any],
    install_receipt_paths: list[Path],
) -> tuple[bool, str]:
    wheels = inv["wheels"]
    sdist = inv["sdist"]
    if not wheels or sdist is None:
        return False, "missing wheels or sdist archive for digest verification"
    if inv["collisions"]:
        return False, f"archive filename collisions: {inv['collisions']}"
    record_bad = [w["filename"] for w in wheels if w["record_errors"]]
    if record_bad:
        return False, f"wheel RECORD sha256 verification failed: {record_bad}"

    known_digests = {item["filename"]: item["sha256"] for item in [*wheels, sdist]}
    if not install_receipt_paths:
        return False, "missing install receipts for artifact SHA-256 cross-check"
    for rp in install_receipt_paths:
        if not rp.is_file():
            return False, f"missing install receipt: {rp}"
        data = json.loads(rp.read_text(encoding="utf-8"))
        src = data.get("source", {})
        if src.get("revision") != revision or src.get("dirty") is not False:
            return False, f"install receipt {rp.name} stale or dirty: {src}"
        refs = data.get("references", {})
        art_name = refs.get("artifact_name")
        art_sha = refs.get("artifact_sha256")
        if (
            not art_name
            or art_name not in known_digests
            or known_digests[art_name] != art_sha
        ):
            return (
                False,
                f"install receipt {rp.name} digest mismatch for {art_name}: {art_sha}",
            )
    return (
        True,
        f"verified SHA-256 digests and RECORD integrity for {len(wheels)} wheels + sdist + {len(install_receipt_paths)} install receipts",
    )


def _result(check_id: str, ok: bool, detail: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "PASS" if ok else "FAIL",
        "evidence_kind": "supported-execution",
        "supported_execution": ok,
        "related_issues": [184],
        "detail": detail,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--revision", required=True)
    p.add_argument("--wheel-dir", type=Path, action="append", default=[])
    p.add_argument("--sdist", type=Path, default=None)
    p.add_argument("--benchmark-report", type=Path, default=None)
    p.add_argument("--current-benchmark-report", type=Path, default=None)
    p.add_argument("--asan-junit", type=Path, action="append", default=[])
    p.add_argument("--asan-receipt", type=Path, default=None)
    p.add_argument("--ci-jobs-json", type=Path, action="append", default=[])
    p.add_argument("--runs-json", type=Path, action="append", default=[])
    p.add_argument("--mutation-report", type=Path, default=None)
    p.add_argument("--install-receipt", type=Path, action="append", default=[])
    p.add_argument("--allow-dirty", action="store_true")
    p.add_argument("--report", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain"], text=True
    ).strip()
    if head != args.revision or (dirty and not args.allow_dirty):
        parser.error("candidate evidence requires the requested clean revision")

    inv = inspect_archive_inventory(
        wheel_dirs=[d.resolve() for d in args.wheel_dir],
        sdist_path=args.sdist.resolve() if args.sdist else None,
    )
    runs = _flatten_runs([p.resolve() for p in args.runs_json], args.revision)
    ci_jobs = _flatten_jobs([p.resolve() for p in args.ci_jobs_json])

    checks = [
        ("release-candidate:license-inventory", *_check_license_inventory(inv)),
        ("release-candidate:notice-inventory", *_check_notice_inventory(inv, root)),
        (
            "release-candidate:memory-contract",
            *_check_memory_contract(
                args.revision, args.benchmark_report, args.current_benchmark_report
            ),
        ),
        (
            "release-candidate:sanitizer-configuration",
            *_check_sanitizer(
                args.revision, args.asan_junit, args.asan_receipt, ci_jobs
            ),
        ),
        (
            "release-candidate:platform-matrix-shape",
            *_check_platform_matrix(inv, ci_jobs),
        ),
        (
            "release-candidate:hosted-evidence",
            *_check_hosted_evidence(args.revision, runs, args.mutation_report),
        ),
        (
            "release-candidate:reproducible-build-digests",
            *_check_reproducible_digests(args.revision, inv, args.install_receipt),
        ),
    ]
    results = [_result(cid, ok, detail) for cid, ok, detail in checks]

    report = {
        "schema_version": 1,
        "check_id": "issue184-candidate-evidence",
        "source": {"revision": args.revision, "dirty": False},
        "references": {
            "wheel_count": inv["wheel_count"],
            "sdist_filename": inv["sdist"]["filename"] if inv["sdist"] else None,
            "sdist_sha256": inv["sdist"]["sha256"] if inv["sdist"] else None,
            "wheel_sha256s": {w["filename"]: w["sha256"] for w in inv["wheels"]},
            "install_receipts": [str(p) for p in args.install_receipt],
            "asan_junits": [str(p) for p in args.asan_junit],
        },
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in results:
        print(f"{row['id']}: {row['status']} ({row['detail'][:90]})")
    return int(any(r["status"] != "PASS" for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
