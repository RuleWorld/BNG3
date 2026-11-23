#!/usr/bin/env python3
"""Execute and record Issue 178 shared-decision/backend release acceptance.

Verdicts are evidence-driven, not label-driven. A check is reported ``PASS``
only when the evidence that actually covers the named check was collected:

* ``release-shared-decisions`` and ``release-obligation-178`` are bounded
  architecture/documentation checks; their collected leaf tests are run here.
* ``release-interface-parity``, ``release-backend-contract`` and
  ``release-backend-oracles`` are cross-backend/format execution checks. A
  single decision-owner leaf test cannot certify them. They stay ``NOT_TESTED``
  unless a consuming route report is supplied with *all* required routes and
  all four evidence aspects (compiled input, result schema, invalid-option
  behaviour and independent semantic output).

GPU device execution is out of scope for this issue (DECISIONS item 17,
tracked under #474). Compile-only or fallback rows never count as device
execution here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_CHECKS = (
    "release-shared-decisions",
    "release-interface-parity",
    "release-obligation-178",
    "release-backend-contract",
    "release-backend-oracles",
)

# Each named check keeps its manifest selector. Running a leaf is necessary but
# not sufficient for the cross-backend checks: those require a route report.
LEAF_TESTS = {
    "release-shared-decisions": "tests/validation/test_option_decision_owner.py::test_poplevel_decision_has_one_compile_owner",
    "release-interface-parity": "tests/python/test_finite_backend.py::test_nf_never_routes_through_bngsim",
    "release-obligation-178": "tests/validation/test_nf_default_docs_consistency.py::test_active_docs_do_not_claim_nfcore_is_the_default",
    "release-backend-contract": "tests/python/test_finite_backend.py::test_explicit_bngsim_fails_closed_when_unavailable_or_unsupported",
    "release-backend-oracles": "tests/validation/test_shared_decision_ownership.py::test_general_energy_gate_has_one_owner",
}

# Bounded architecture/documentation checks whose leaf genuinely covers them.
MEASURED_LEAF_CHECKS = frozenset(
    {"release-shared-decisions", "release-obligation-178"}
)

# Cross-backend/format checks need a consuming report with full route coverage.
ROUTE_CHECKS = frozenset(
    {
        "release-interface-parity",
        "release-backend-contract",
        "release-backend-oracles",
    }
)

# The four evidence aspects every required route must carry. A partial report
# (missing any aspect or route) cannot satisfy a route check.
ROUTE_ASPECTS = (
    "compiled_input",
    "result_schema",
    "invalid_options",
    "independent_output",
)

# Required production routes for the CPU release. GPU device rows are excluded
# by the recorded scope decision and are never accepted as device evidence.
REQUIRED_ROUTES = {
    "release-interface-parity": (
        "ode:native",
        "ssa:native",
        "nf:nfnext",
        "format:bngl",
        "format:net",
    ),
    "release-backend-contract": (
        "ode:native",
        "ssa:native",
        "pla:native",
        "psa:native",
        "nf:nfnext",
        "nf:nfcore",
        "ode:bngsim",
        "ssa:bngsim",
    ),
    "release-backend-oracles": (
        "ode:native",
        "ssa:native",
        "nf:nfnext",
        "ode:bngsim",
        "ssa:bngsim",
    ),
}

# Honest descriptions used whenever full evidence was not collected. These
# replace the previous behaviour of emitting PASS with the same caveat text.
UNMEASURED_DETAILS = {
    "release-shared-decisions": (
        "Only the poplevel/simulation-option single-owner leaves ran; other "
        "option, rate and capability rules remain unmeasured."
    ),
    "release-interface-parity": (
        "Cross-backend and format semantic parity is unmeasured: no consuming "
        "report covers compiled input, result schema, invalid options and an "
        "independent semantic output for every required route."
    ),
    "release-obligation-178": (
        "The documentation/default leaf ran; the remaining work clauses "
        "(route and oracle coverage) remain unmeasured."
    ),
    "release-backend-contract": (
        "The BNGsim refusal leaf ran only. The shared compiled input, result "
        "schema and consistent invalid-option behaviour across all backends "
        "remain unmeasured."
    ),
    "release-backend-oracles": (
        "The energy-gate ownership leaf ran only. Backend execution against "
        "BNG2/native NFsim/analytic oracles remains unmeasured; GPU device "
        "execution is tracked under #474."
    ),
}


def _fail(message: str) -> None:
    raise ValueError(message)


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    manifest = json.loads((root / "provenance/issue-obligations.json").read_text())
    issue = next((i for i in manifest["issues"] if i["number"] == 178), None)
    if issue is None:
        _fail("Issue 178 is missing from the obligations manifest")
    checks: dict[str, dict] = {}
    for obligation in issue["obligations"]:
        for check in obligation["required_checks"]:
            if check["id"] not in EXPECTED_CHECKS:
                continue
            if check["id"] in checks:
                _fail(f"duplicate manifest definition for {check['id']}")
            if (
                check.get("selector") != LEAF_TESTS[check["id"]]
                or check.get("selector_status") != "COLLECTED"
            ):
                _fail(f"{check['id']} selector is not the expected collected leaf")
            if check.get(
                "receipt_producer_status"
            ) != "CONSUMER_READY" or not check.get("receipt_producer"):
                _fail(f"{check['id']} has no consumer-ready receipt producer")
            checks[check["id"]] = check
    if set(checks) != set(EXPECTED_CHECKS):
        _fail(f"manifest missing checks: {sorted(set(EXPECTED_CHECKS)-set(checks))}")
    return checks


def run_tests(root: Path = ROOT) -> dict[str, dict]:
    """Run every collected leaf and return the checks whose leaves executed.

    Failure is fail-closed: a non-zero leaf raises and no receipt is written.
    The returned mapping is the *only* evidence `build_release_record` may use
    to claim a leaf-backed verdict; a mocked/no-op runner returns nothing and
    therefore cannot yield a PASS for any check.
    """
    executed: dict[str, dict] = {}
    for check_id, selector in LEAF_TESTS.items():
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--noconftest", "-q", selector],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _fail(
                f"Issue 178 leaf {check_id} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
            )
        executed[check_id] = {"selector": selector, "returncode": 0}
    return executed


def verify_route_report(
    path: Path, check_id: str, revision: str
) -> dict | None:
    """Validate a consuming route report, or return None if it is insufficient.

    A report qualifies only when it is exact-revision, clean, PASS, reports
    ``supported-execution`` for the named check, and lists every required route
    with all four evidence aspects true. GPU device rows and compile-only
    fallbacks are explicitly excluded from device evidence.
    """
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict) or report.get("check") != check_id:
        return None
    if report.get("source_revision") != revision or report.get("source_dirty") is not False:
        return None
    if report.get("status") != "PASS":
        return None
    rows = report.get("routes")
    if not isinstance(rows, dict):
        return None
    for route in REQUIRED_ROUTES[check_id]:
        row = rows.get(route)
        if not isinstance(row, dict):
            return None
        if any(row.get(aspect) is not True for aspect in ROUTE_ASPECTS):
            return None
        if row.get("scope") == "gpu-device":
            # Device execution is owned by #474 and cannot qualify this check.
            return None
    return report


def build_release_record(
    expected_revision=None,
    root=ROOT,
    skip_tests=False,
    allow_dirty=False,
    route_reports=None,
):
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if expected_revision and head != expected_revision:
        _fail(f"stale Issue 178 evidence: HEAD {head} != {expected_revision}")
    revision = expected_revision or head
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if dirty and not allow_dirty:
        _fail(f"Issue 178 evidence checkout is dirty: {dirty}")
    manifest = verify_manifest(root)

    # A mocked or no-op runner must not be interpreted as executed evidence.
    executed = (run_tests(root) if not skip_tests else {}) or {}

    route_reports = route_reports or {}
    consumed_routes: dict[str, dict] = {}
    for check_id in ROUTE_CHECKS:
        report_path = route_reports.get(check_id)
        if report_path is not None:
            verified = verify_route_report(Path(report_path), check_id, revision)
            if verified is not None:
                consumed_routes[check_id] = verified

    results = []
    for check_id in EXPECTED_CHECKS:
        measured = check_id in MEASURED_LEAF_CHECKS and check_id in executed
        routed = check_id in ROUTE_CHECKS and check_id in consumed_routes
        if not skip_tests and (measured or routed):
            status = "PASS"
            evidence_kind = "supported-execution"
            supported = True
            detail = (
                "Consuming route report covers all required routes and evidence aspects."
                if routed
                else "Collected single-owner leaf executed for this bounded architecture check."
            )
        else:
            status = "NOT_TESTED"
            evidence_kind = "not-tested"
            supported = False
            detail = UNMEASURED_DETAILS[check_id]
        results.append(
            {
                "id": check_id,
                "check": check_id,
                "test_file": manifest[check_id]["selector"],
                "status": status,
                "evidence_kind": evidence_kind,
                "supported_execution": supported,
                "related_issues": [178],
                "stage": check_id,
                "detail": detail,
                "source_revision": revision,
                "selector": manifest[check_id]["selector"],
            }
        )
    return {
        "schema_version": 1,
        "acceptance_check": "release-obligation-178",
        "case": "issue-178-shared-decisions-release",
        "source": {"revision": revision, "dirty": bool(dirty)},
        "references": {
            "leaf_tests": list(LEAF_TESTS.values()),
            "provenance": "provenance/issue-obligations.json",
            "gpu_scope": "#474 (device execution excluded; compile-only is not device evidence)",
            "route_reports": {
                check: str(path) for check, path in sorted(route_reports.items())
            },
        },
        "results": results,
        "manifest_check_ids": sorted(EXPECTED_CHECKS),
        "unmeasured_checks": sorted(
            row["id"] for row in results if row["status"] == "NOT_TESTED"
        ),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-revision")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--summary-file", type=Path)
    p.add_argument("--skip-tests", action="store_true")
    p.add_argument("--allow-dirty", action="store_true")
    p.add_argument(
        "--route-report",
        action="append",
        default=[],
        metavar="CHECK=PATH",
        help="consuming route report for a cross-backend check (repeatable)",
    )
    a = p.parse_args(argv)
    route_reports = {}
    for item in a.route_report:
        check_id, _, path = item.partition("=")
        if check_id not in ROUTE_CHECKS or not path:
            _fail(f"invalid --route-report: {item}")
        route_reports[check_id] = path
    rec = build_release_record(
        a.source_revision,
        skip_tests=a.skip_tests,
        allow_dirty=a.allow_dirty,
        route_reports=route_reports,
    )
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(rec, indent=2) + "\n")
    if a.summary_file:
        a.summary_file.parent.mkdir(parents=True, exist_ok=True)
        with a.summary_file.open("a", encoding="utf-8") as h:
            h.write("\n## Issue 178 shared decisions release evidence\n\n")
            for r in rec["results"]:
                h.write(f"- {r['id']}: {r['status']}\n")
    print(f"wrote {a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
