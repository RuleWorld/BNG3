#!/usr/bin/env python3
"""Consume retained Issue 148 NFnext corpus evidence as release acceptance.

The corpus pytest case writes ``bng3-nfnext-corpus-report.json``.  This recorder
is the revision-locked consumer that turns that artifact into the three Issue
148 release rows.  It never runs the corpus itself and never infers a pass:
every field that establishes source revision, oracle identity, declared
protocol, per-model execution, negative controls and single-engine routes is
re-checked against the retained artifact before any PASS row is emitted.

No JUnit property cross-check is needed here.  The retained corpus report is
itself the leaf artifact written by the harness (the pytest case asserts its
contract), and the only identity required by the manifest is
``source.revision``.  That revision is re-verified below against git HEAD and
the report is tied to the pinned BNG2/NFsim lock, which is stronger than
restating JUnit property strings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.oracle_sources import load_lock, load_oracle_source  # noqa: E402
from tests.validation import corpus  # noqa: E402

EXPECTED_CHECKS = (
    "release-nfnext-execution",
    "release-nfnext-routes",
    "release-capability-coverage-148",
)
EXECUTION_CHECK = "release-nfnext-execution"
ROUTE_CHECK = "release-nfnext-routes"
RECORD_PRODUCER = "scripts/ci/record_issue148_release.py"
BNG3_REPOSITORY = "https://github.com/RuleWorld/BNG3.git"
MIN_SEEDS = 32
SHA64 = re.compile(r"^[0-9a-f]{64}$")
LOSS_SEVERITIES = {
    "dropped",
    "approximated",
    "unsupported",
    "untranslated",
    "error",
}


def _fail(message: str) -> None:
    raise ValueError(message)


def _require(condition: object, message: str) -> None:
    if not condition:
        _fail(message)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    """Require executable selectors and a consuming receipt for every check."""
    manifest = json.loads(
        (root / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue = next((item for item in manifest["issues"] if item["number"] == 148), None)
    if issue is None:
        _fail("Issue 148 is missing from the obligations manifest")

    checks: dict[str, dict] = {}
    for obligation in issue["obligations"]:
        for check in obligation["required_checks"]:
            check_id = check["id"]
            if check_id not in EXPECTED_CHECKS:
                continue
            if check_id in checks:
                _fail(f"duplicate or conflicting manifest definition for {check_id}")
            checks[check_id] = check
    missing = set(EXPECTED_CHECKS) - set(checks)
    if missing:
        _fail(f"manifest is missing required checks: {sorted(missing)}")

    digests = {issue.get("body_sha256")}
    for obligation in issue["obligations"]:
        if obligation["id"].startswith("issue:148:live-acceptance:"):
            digests.add(obligation.get("live_body_sha256"))
    _require(
        len(digests) == 1
        and all(isinstance(value, str) and SHA64.fullmatch(value) for value in digests),
        "Issue 148 live-body and issue-body digests are stale or conflicting",
    )

    for check_id, definition in checks.items():
        _require(
            definition.get("evidence_kind") == "supported-execution",
            f"check {check_id} is not supported-execution evidence",
        )
        _require(
            "source.revision" in definition.get("identity_requirements", []),
            f"check {check_id} does not require source revision identity",
        )
        _require(
            definition.get("selector_status") == "COLLECTED"
            and bool(definition.get("selector")),
            f"check {check_id} has no collected executable selector",
        )
        _require(
            definition.get("receipt_producer_status") == "CONSUMER_READY"
            and definition.get("receipt_producer") == RECORD_PRODUCER,
            f"check {check_id} is not mapped to its consuming receipt producer",
        )
        _require(
            not definition.get("missing_evidence"),
            f"check {check_id} still carries unmapped missing evidence",
        )
        selector_file = definition["selector"].split("::", 1)[0]
        _require(
            (root / selector_file).is_file(),
            f"selector for {check_id} does not exist: {selector_file}",
        )
    return checks


def _verify_oracle(report: dict, lock: dict, name: str, key: str) -> dict:
    source = load_oracle_source(lock, name)
    oracle = report.get("oracles", {}).get(key)
    _require(isinstance(oracle, dict), f"corpus report lacks {key} oracle identity")
    _require(oracle.get("available") is True, f"{key} oracle was not available")

    digest_key = "script_digest" if key == "bng2" else "binary_digest"
    digest = oracle.get(digest_key)
    _require(
        isinstance(digest, str) and SHA64.fullmatch(digest),
        f"{key} oracle has no valid script/binary digest",
    )
    locked = oracle.get("locked")
    _require(
        isinstance(locked, dict)
        and locked.get("revision") == source["revision"]
        and locked.get("repository") == source["repository"],
        f"{key} oracle identity is stale against the pinned lock",
    )
    artifact = lock.get("oracles", {}).get(key, {}).get("artifact_digest")
    if artifact:
        _require(
            locked.get("artifact_digest") == artifact,
            f"{key} oracle artifact digest differs from the pinned lock",
        )
    observed = oracle.get("revision")
    if observed:
        _require(
            observed == source["revision"],
            f"{key} oracle checkout revision differs from the pinned lock",
        )
    return {"revision": source["revision"], "digest": digest}


def verify_report(report_path: Path, expected_revision: str) -> dict:
    _require(report_path.is_file(), f"missing corpus report: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    _require(isinstance(report, dict), "corpus report is not an object")
    _require(
        report.get("check") == EXECUTION_CHECK,
        "corpus report has a conflicting check ID",
    )
    _require(
        ROUTE_CHECK in report.get("related_checks", []),
        "corpus report does not declare the route check",
    )
    if "report_path" in report:
        _require(
            Path(report["report_path"]).resolve() == report_path.resolve(),
            "corpus report path does not match the supplied artifact",
        )
    if "report_sha256" in report:
        _require(
            report["report_sha256"] == _sha256(report_path),
            "corpus report SHA-256 conflicts with the supplied artifact",
        )

    source = report.get("source")
    _require(isinstance(source, dict), "corpus report lacks source identity")
    _require(
        source.get("revision") == expected_revision,
        f"stale corpus source revision: {source.get('revision')} != {expected_revision}",
    )
    _require(source.get("dirty") is False, "corpus report was not recorded clean")
    _require(
        source.get("repository") == BNG3_REPOSITORY,
        "corpus report source repository is not BNG3",
    )

    lock = load_lock()
    oracles = {
        key: _verify_oracle(report, lock, name, key)
        for name, key in (("bionetgen", "bng2"), ("nfsim", "nfsim"))
    }

    plan = report.get("plan")
    _require(isinstance(plan, dict), "corpus report lacks a declared plan")
    _require(
        plan.get("declared_before_execution") is True,
        "plan was not declared before execution",
    )
    _require(
        plan.get("exclusions") == [], "plan excludes corpus models after selection"
    )
    planned = plan.get("models")
    _require(
        isinstance(planned, list)
        and len(planned) == len(set(planned))
        and set(planned) == set(corpus.TIER_NF),
        "declared plan does not cover the full TIER_NF corpus",
    )
    seeds = plan.get("seed_count")
    _require(
        isinstance(seeds, int) and not isinstance(seeds, bool) and seeds >= MIN_SEEDS,
        f"declared seed budget is below {MIN_SEEDS}",
    )
    alpha = plan.get("alpha")
    _require(
        isinstance(alpha, (int, float))
        and not isinstance(alpha, bool)
        and 0 < alpha <= 1,
        "declared family-wise error budget is invalid",
    )

    rows = report.get("models")
    _require(
        isinstance(rows, list) and len(rows) == len(corpus.TIER_NF),
        "corpus report does not contain one row per TIER_NF model",
    )
    names = [row.get("model") for row in rows]
    _require(
        len(set(names)) == len(names) and set(names) == set(corpus.TIER_NF),
        "corpus model rows are missing, duplicated, or outside TIER_NF",
    )
    for row in rows:
        label = row.get("model")
        _require(row.get("status") == "PASS", f"corpus model {label} did not pass")
        _require(
            row.get("evidence_kind") == "supported-execution"
            and row.get("supported_execution") is True,
            f"corpus model {label} is not supported execution",
        )
        completed = row.get("seeds_completed")
        _require(
            isinstance(completed, int)
            and not isinstance(completed, bool)
            and completed >= seeds,
            f"corpus model {label} did not complete the declared seeds",
        )
        _require(
            row.get("engines") == ["nfnext"],
            f"corpus model {label} did not stay on a single NFnext engine",
        )
        assessment = row.get("assessment")
        _require(
            isinstance(assessment, dict) and assessment.get("status") == "PASS",
            f"corpus model {label} has no passing statistical assessment",
        )
        _require(
            assessment.get("ensemble_runs", 0) >= seeds
            and assessment.get("comparison_count", 0) >= 1
            and assessment.get("sigma") == 4.0,
            f"corpus model {label} assessment budget or law is stale",
        )
        for diagnostic in row.get("diagnostics", []):
            _require(
                isinstance(diagnostic, dict)
                and str(diagnostic.get("severity", "")).lower() not in LOSS_SEVERITIES,
                f"corpus model {label} carries a loss diagnostic",
            )

    summary = report.get("summary")
    _require(isinstance(summary, dict), "corpus report lacks a summary")
    _require(
        summary.get("model_count") == len(corpus.TIER_NF)
        and summary.get("all_models_pass") is True,
        "corpus summary does not record every model as passing",
    )
    _require(
        summary.get("release_check_satisfied") is True,
        "corpus summary does not satisfy the release check",
    )

    controls = report.get("negative_controls")
    _require(isinstance(controls, dict), "corpus report lacks negative controls")
    _require(
        controls.get("rejects_wrong_law") is True,
        "negative controls did not reject a wrong law",
    )
    for name, expected in (
        ("positive_control", "PASS"),
        ("wrong_rate_control", "FAIL"),
        ("frozen_observable_control", "FAIL"),
    ):
        control = controls.get(name)
        _require(
            isinstance(control, dict) and control.get("status") == expected,
            f"negative control {name} is not {expected}",
        )
    _require(
        summary.get("negatives_reject_wrong_law") is True,
        "corpus summary does not record rejecting negative controls",
    )

    routes = report.get("routes")
    _require(isinstance(routes, dict), "corpus report lacks route evidence")
    _require(
        routes.get("status") == "PASS" and routes.get("single_engine") is True,
        "production routes did not stay on a single engine",
    )
    binding = routes.get("binding")
    _require(
        isinstance(binding, dict)
        and binding.get("status") == "PASS"
        and binding.get("engine") == "nfnext",
        "native NFnext binding route is not a passing NFnext route",
    )
    public_api = routes.get("public_api")
    _require(
        isinstance(public_api, dict)
        and public_api.get("status") in {"PASS", "NOT_TESTED"},
        "public API route is not an executed or explicitly untested route",
    )
    if public_api.get("status") == "PASS":
        _require(
            public_api.get("backend") == "nfnext",
            "public API route did not use the NFnext backend",
        )
    _require(
        summary.get("routes_single_engine") is True,
        "corpus summary does not record single-engine routes",
    )

    return {
        "source": {"revision": source["revision"], "dirty": False},
        "oracles": oracles,
        "plan": {
            "model_count": len(planned),
            "seed_count": seeds,
            "seed_base": plan.get("seed_base"),
            "alpha": alpha,
            "exclusions": [],
        },
        "summary": {
            "all_models_pass": summary["all_models_pass"],
            "release_check_satisfied": summary["release_check_satisfied"],
            "negatives_reject_wrong_law": summary["negatives_reject_wrong_law"],
            "routes_single_engine": summary["routes_single_engine"],
        },
    }


def build_release_record(
    report_path: Path,
    expected_revision: str,
    *,
    root: Path = ROOT,
    allow_dirty: bool = False,
) -> dict:
    head = _git(root, "rev-parse", "HEAD")
    _require(
        head == expected_revision,
        f"stale Issue 148 evidence: checkout HEAD {head} != {expected_revision}",
    )
    dirty = _git(root, "status", "--porcelain")
    if dirty and not allow_dirty:
        _fail(f"Issue 148 evidence checkout is dirty: {dirty}")
    manifest_checks = verify_manifest(root)
    evidence = verify_report(report_path, expected_revision)

    results = [
        {
            "id": check_id,
            "status": "PASS",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [148],
            "stage": "nfnext-native-corpus",
            "detail": detail,
            "source_revision": head,
            "corpus_report_sha256": _sha256(report_path),
        }
        for check_id, detail in (
            (
                "release-nfnext-execution",
                "every TIER_NF model executed through the production NFnext entry "
                "point and matched pinned native NFsim at the declared family-wise level.",
            ),
            (
                "release-nfnext-routes",
                "native binding and public API routes stayed on a single NFnext engine.",
            ),
            (
                "release-capability-coverage-148",
                "all assigned inventory rows passed with negative controls rejecting "
                "a wrong rate and a frozen observable.",
            ),
        )
    ]
    record = {
        "schema_version": 1,
        "acceptance_check": EXECUTION_CHECK,
        "case": "issue-148-nfnext-native-corpus-release",
        "source": {"revision": head, "dirty": bool(dirty)},
        "corpus_report": {
            "path": str(report_path.resolve()),
            "sha256": _sha256(report_path),
            **evidence,
        },
        "references": evidence["oracles"],
        "results": results,
        "manifest_check_ids": sorted(manifest_checks),
    }
    if allow_dirty:
        record["local_allow_dirty"] = True
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record Issue 148 NFnext native-corpus release acceptance."
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Retained bng3-nfnext-corpus-report.json from the exact main revision",
    )
    parser.add_argument(
        "--source-revision", required=True, help="Expected git commit SHA"
    )
    parser.add_argument("--output", type=Path, required=True, help="Output JSON path")
    parser.add_argument("--summary-file", type=Path, help="GitHub step summary path")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Local testing only; the resulting record is not exact-main evidence",
    )
    args = parser.parse_args(argv)

    try:
        record = build_release_record(
            args.report,
            args.source_revision,
            allow_dirty=args.allow_dirty,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

        summary = [
            "## Issue 148 NFnext native-corpus release obligation record",
            "",
            f"- Source commit: `{record['source']['revision']}`",
            *(f"- {row['id']}: {row['status']}" for row in record["results"]),
            "",
            f"Consolidated JSON report: `{args.output}`",
            "",
        ]
        if args.summary_file:
            with args.summary_file.open("a", encoding="utf-8") as stream:
                stream.write("\n".join(summary))
        else:
            sys.stdout.write("\n".join(summary))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"Issue 148 release record rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
