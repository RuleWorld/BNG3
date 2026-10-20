"""Locked official SBML conformance evidence for the revision under test.

Issue #159 ("E03: Publish current revision-locked official SBML conformance
evidence") asks for two things that the existing corpus campaign did not
provide as named, executable checks:

* the existing locked-suite runner is executed on an *identified* BNG3 build
  and the per-case artifacts are retained, and
* the conversion, round trip, official-reference conformance and independent
  comparison are reported as four separately recorded outcomes, so a green
  conversion cannot mask a failed reference comparison.

This module owns both.  It never re-implements the runner: it executes
``scripts/ci/validate_sbml_test_suite.py`` in a child process, keeps the
runner's own report, and turns the report into *separate* rows.  A stage that
was not executed is ``NOT_TESTED``; a stage that failed is ``FAIL``; an
unsupported case stays unsupported and is never counted as a pass.

The suite checkout is an external, revision-locked corpus.  When it is absent
the family records every row as ``NOT_TESTED`` with the reason, because a
missing corpus is not evidence of conformance.

Boundary of the statement: the family qualifies the *reported* outcomes of one
runner invocation over one locked suite revision and one candidate build.  It
does not claim that the whole official suite is supported, and the runner's
own partial-run flags stay in force.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "ci" / "validate_sbml_test_suite.py"
ISSUES = (159,)

# The four separately recorded outcomes of the locked-suite runner.  The
# runner's own stage names are kept so a reader can map one row onto one
# stage of the retained report.
CONVERSION_STAGE = "conversion"
ROUNDTRIP_STAGE = "roundtrip"
OFFICIAL_STAGE = "official-reference"
INDEPENDENT_STAGE = "independent-oracle"

STAGE_ROWS = (
    ("sbml-conformance:conversion", CONVERSION_STAGE, "conversion"),
    ("sbml-conformance:roundtrip", ROUNDTRIP_STAGE, "roundtrip_structure"),
    ("sbml-conformance:official-reference", OFFICIAL_STAGE, "official_reference"),
    (
        "sbml-conformance:independent-oracle",
        INDEPENDENT_STAGE,
        "independent_comparison",
    ),
)

# The obligation also names the event-target cases and the zero-observable
# cases.  They are reported as their own rows so a cohort that cannot produce
# reference evidence is visible instead of being averaged away.
EVENT_ROW = "sbml-conformance:event-target-cases"
ZERO_OBSERVABLE_ROW = "sbml-conformance:zero-observable-cases"
RUNNER_ROW = "sbml-conformance:runner-execution"

CHECK_IDS = (
    RUNNER_ROW,
    "sbml-conformance:conversion",
    "sbml-conformance:roundtrip",
    "sbml-conformance:official-reference",
    "sbml-conformance:independent-oracle",
    EVENT_ROW,
    ZERO_OBSERVABLE_ROW,
)

# The runner's own stage buckets.  ``failed``/``timeout`` are the outcomes that
# make a stage fail; ``unsupported`` is reported but never counted as a pass.
FAILING_STATUSES = ("failed", "timeout")

DEFAULT_CATEGORIES = ("semantic",)
DEFAULT_MAX_CASES = 0
DEFAULT_JOBS = 4
DEFAULT_CASE_TIMEOUT = 60

# The time grid of the runner's own simulation comparison.
SIMULATION_T_END = 1.0
SIMULATION_N_STEPS = 10


def check_ids() -> list[str]:
    """Stable check identities for the locked-suite conformance family."""

    return list(CHECK_IDS)


def _row(check_id, check, status, detail, **evidence):
    row = dict(
        id=check_id,
        check=check,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
        evidence_kind="supported-execution",
        supported_execution=True,
    )
    row.update(evidence)
    return row


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_revision() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _local_native_extension() -> dict | None:
    try:
        import bionetgen._bionetgen_cpp as cpp
    except ImportError:
        return None
    path = Path(getattr(cpp, "__file__", "") or "")
    if not path.is_file():
        return None
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
    }


def _event_targets(source: Path) -> bool:
    """Report whether a case source declares SBML event targets."""

    try:
        document = ET.parse(source).getroot()
    except (OSError, ET.ParseError):
        return False
    for element in document.iter():
        tag = element.tag
        if not isinstance(tag, str):
            continue
        if tag.rsplit("}", 1)[-1] == "event":
            return True
    return False


def _stage_counts(report: dict) -> dict:
    counts = report.get("stage_counts")
    return counts if isinstance(counts, dict) else {}


def _stage_status(counts: dict, key: str) -> tuple[str, str]:
    """Turn one runner stage bucket into one separately recorded outcome.

    A stage with a failure is ``FAIL``.  A stage that produced at least one
    pass is ``PASS``.  A stage whose cases are all explicitly unsupported is
    ``UNSUPPORTED`` and a stage that was not executed is ``NOT_TESTED``: both
    provide no conformance evidence and must not be reported as a pass.
    """

    bucket = counts.get(key) or {}
    if not isinstance(bucket, dict):
        return "NOT_TESTED", f"the runner report has no '{key}' stage counts"
    failed = sum(int(bucket.get(status, 0)) for status in FAILING_STATUSES)
    passed = int(bucket.get("passed", 0))
    unsupported = int(bucket.get("unsupported", 0))
    detail = f"{key}: {passed} passed, {unsupported} unsupported, {failed} failed"
    if failed:
        return "FAIL", detail + f"; {failed} case(s) failed in this stage"
    if passed:
        return "PASS", detail
    if unsupported:
        return (
            "UNSUPPORTED",
            detail + "; every case in this stage is explicitly unsupported, which is "
            "a named boundary and not a conformance pass",
        )
    return "NOT_TESTED", detail + "; this stage produced no executed evidence"


def _cohort_rows(report: dict) -> tuple[list[dict], list[dict]]:
    """Split the executed cases into the event-target and zero-observable cohorts."""

    records = report.get("records")
    records = records if isinstance(records, list) else []
    event_records = []
    zero_records = []
    for record in records:
        if not isinstance(record, dict):
            continue
        source = Path(str(record.get("source", "")))
        if source.name and _event_targets(source):
            event_records.append(record)
        comparison = record.get("simulation_comparison")
        if isinstance(comparison, dict) and not comparison.get("skipped"):
            if int(comparison.get("observable_count", 0) or 0) == 0:
                zero_records.append(record)
    return event_records, zero_records


def _cohort_outcome(records: list[dict], status_key: str) -> tuple[str, str, dict]:
    passed = 0
    failed = 0
    unsupported = 0
    for record in records:
        result = record.get(status_key) or {}
        status = str(result.get("status", "missing"))
        if status == "passed":
            passed += 1
        elif status in FAILING_STATUSES:
            failed += 1
        else:
            unsupported += 1
    detail = f"{len(records)} case(s): {passed} passed, {unsupported} unsupported, {failed} failed"
    counts = {
        "passed": passed,
        "unsupported": unsupported,
        "failed": failed,
    }
    if failed:
        return "FAIL", detail + f"; {failed} case(s) failed", counts
    if passed:
        return "PASS", detail, counts
    if unsupported:
        return (
            "UNSUPPORTED",
            detail + "; every case in this cohort is explicitly unsupported, which is "
            "a named boundary and not a conformance pass",
            counts,
        )
    return "NOT_TESTED", detail + "; this cohort produced no executed evidence", counts


def _not_tested_rows(reason: str) -> list[dict]:
    rows = [
        _row(
            RUNNER_ROW,
            "runner-execution",
            "NOT_TESTED",
            reason,
            expectation="the locked-suite runner executes on the identified build",
        )
    ]
    for check_id, _stage, key in STAGE_ROWS:
        rows.append(
            _row(
                check_id,
                key,
                "NOT_TESTED",
                reason,
                expectation=f"the runner reports the '{key}' stage separately",
            )
        )
    for check_id, expectation in (
        (EVENT_ROW, "event-target cases are reported separately"),
        (ZERO_OBSERVABLE_ROW, "zero-observable cases are reported separately"),
    ):
        rows.append(
            _row(
                check_id,
                check_id.rsplit(":", 1)[-1],
                "NOT_TESTED",
                reason,
                expectation=expectation,
            )
        )
    return rows


def _run_runner(
    suite_dir: Path,
    report_path: Path,
    artifacts_dir: Path | None,
    *,
    categories,
    max_cases: int,
    selection_strategy: str,
    jobs: int,
    case_timeout: int,
) -> dict:
    command = [
        sys.executable,
        str(RUNNER),
        "--suite-dir",
        str(suite_dir),
        "--json",
        str(report_path),
        "--categories",
        *categories,
        "--case-timeout",
        str(case_timeout),
        "--jobs",
        str(jobs),
        "--isolate-cases",
        "--simulation-t-end",
        str(SIMULATION_T_END),
        "--simulation-n-steps",
        str(SIMULATION_N_STEPS),
    ]
    if max_cases:
        command += ["--max-cases", str(max_cases)]
    if selection_strategy != "prefix":
        command += ["--selection-strategy", selection_strategy]
    if artifacts_dir is not None:
        command += ["--artifacts-dir", str(artifacts_dir)]
    # The runner imports the same installed package as this process.  The
    # environment is inherited unchanged on purpose: rewriting PYTHONPATH
    # would shadow the installed native extension with the source tree.
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def run(
    directory,
    *,
    suite_dir=None,
    categories=DEFAULT_CATEGORIES,
    max_cases: int = DEFAULT_MAX_CASES,
    selection_strategy: str = "prefix",
    jobs: int = DEFAULT_JOBS,
    case_timeout: int = DEFAULT_CASE_TIMEOUT,
):
    """Execute the locked-suite runner and record the four separate outcomes."""

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    suite = Path(suite_dir) if suite_dir is not None else None
    if suite is None or not suite.is_dir():
        return _not_tested_rows(
            "the locked SBML Test Suite checkout is not available in this "
            "environment, so the locked-suite runner was not executed; a missing "
            "corpus is not evidence of conformance"
        )

    report_path = directory / "locked-suite-report.json"
    artifacts = directory / "cases"
    invocation = _run_runner(
        suite,
        report_path,
        artifacts,
        categories=list(categories),
        max_cases=max_cases,
        selection_strategy=selection_strategy,
        jobs=jobs,
        case_timeout=case_timeout,
    )
    (directory / "runner-invocation.json").write_text(
        json.dumps(invocation, indent=2) + "\n", encoding="utf-8"
    )
    if not report_path.is_file():
        return _not_tested_rows(
            "the locked-suite runner produced no report: "
            + (invocation["stderr"] or invocation["stdout"])[-500:]
        )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = []

    # The runner must have executed on the identified build.  A report from a
    # different source revision or a different native extension is not evidence
    # for this candidate.
    revision = _local_revision()
    extension = _local_native_extension()
    provenance = report.get("source_provenance") or {}
    runtime = report.get("runtime_provenance") or {}
    identity_problems = []
    if revision and provenance.get("bng3_commit") != revision:
        identity_problems.append(
            "the runner report was produced for source revision "
            f"{provenance.get('bng3_commit')!r}, not {revision!r}"
        )
    if extension and runtime.get("native_extension_sha256") != extension["sha256"]:
        identity_problems.append(
            "the runner report used native extension "
            f"{runtime.get('native_extension_sha256')!r}, not the imported "
            f"extension {extension['sha256']!r}"
        )
    if report.get("suite_commit") is None:
        identity_problems.append("the runner report records no locked suite revision")
    preflight_error = str(report.get("preflight_error") or "")
    if preflight_error:
        identity_problems.append(
            "the locked-suite runner rejected the suite checkout: " + preflight_error
        )
    rows.append(
        _row(
            RUNNER_ROW,
            "runner-execution",
            "FAIL" if identity_problems else "PASS",
            (
                "the locked-suite runner executed on the identified build and "
                "retained its per-case artifacts"
                if not identity_problems
                else "the locked-suite runner did not execute on the identified build"
            ),
            first_difference=(
                {"field": "identity", "detail": identity_problems[0]}
                if identity_problems
                else None
            ),
            expectation="the locked-suite runner executes on the identified build",
            suite_dir=str(suite),
            suite_revision=report.get("suite_commit"),
            source_revision=provenance.get("bng3_commit"),
            native_extension_sha256=runtime.get("native_extension_sha256"),
            selected_cases=report.get("selected_cases"),
            case_inventory=report.get("case_inventory"),
            partial_run=report.get("partial_run"),
            runner_returncode=invocation["returncode"],
        )
    )

    counts = _stage_counts(report)
    for check_id, stage, key in STAGE_ROWS:
        status, detail = _stage_status(counts, key)
        rows.append(
            _row(
                check_id,
                stage,
                status,
                detail,
                expectation=(
                    "the runner reports the " f"'{key}' stage as its own outcome"
                ),
                stage_counts=counts.get(key) or {},
            )
        )

    event_records, zero_records = _cohort_rows(report)
    status, detail, evidence = _cohort_outcome(event_records, "official_conformance")
    rows.append(
        _row(
            EVENT_ROW,
            "event-target-cases",
            status,
            detail,
            expectation=(
                "the official-reference outcome of the cases that declare SBML "
                "event targets is reported separately"
            ),
            cases=[str(record.get("id")) for record in event_records],
            **evidence,
        )
    )

    # A case with no observables has nothing to compare: its independent
    # comparison is trivially green and must not be counted as independent
    # evidence.  The row records the cohort and states that exclusion.
    zero_failed = [
        record
        for record in zero_records
        if str((record.get("simulation_comparison") or {}).get("passed")) == "False"
    ]
    rows.append(
        _row(
            ZERO_OBSERVABLE_ROW,
            "zero-observable-cases",
            ("FAIL" if zero_failed else ("PASS" if zero_records else "NOT_TESTED")),
            (
                f"{len(zero_records)} case(s) declare no observable output; their "
                "independent comparison carries no reference evidence and is "
                "excluded from the independent-oracle pass count"
                if not zero_failed
                else (
                    f"{len(zero_failed)} zero-observable case(s) failed and must "
                    "not be reported as a green independent comparison"
                )
            ),
            expectation=(
                "cases without observables are reported separately and are not "
                "counted as independent-oracle evidence"
            ),
            cases=[str(record.get("id")) for record in zero_records],
            failed_cases=[str(record.get("id")) for record in zero_failed],
            independent_oracle_evidence=0,
        )
    )

    (directory / "conformance-summary.json").write_text(
        json.dumps(
            {
                "check_ids": list(CHECK_IDS),
                "suite_dir": str(suite),
                "suite_revision": report.get("suite_commit"),
                "stage_counts": counts,
                "official_conformance": report.get("official_conformance", {}).get(
                    "counts"
                ),
                "event_target_cases": [str(r.get("id")) for r in event_records],
                "zero_observable_cases": [str(r.get("id")) for r in zero_records],
                "partial_run": report.get("partial_run"),
                "core_passed": report.get("core_passed"),
                "selected_surface_passed": report.get("selected_surface_passed"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return rows


def build_report(rows, directory):
    """Assemble the harness report for this family."""

    from . import campaign

    directory = Path(directory).resolve()
    report = dict(
        schema_version=1,
        generated_by="tests.validation.sbml_conformance",
        source=dict(
            revision=campaign.git(ROOT, "rev-parse", "HEAD"),
            dirty=bool(campaign.git(ROOT, "status", "--porcelain")),
        ),
        subject=dict(
            runner=str(RUNNER),
            suite_lock=str(ROOT / "provenance" / "upstreams.lock.yml"),
        ),
        references={
            "official_reference": (
                "the official SBML Test Suite results CSV at the locked suite "
                "revision"
            ),
            "independent_oracle": "libRoadRunner CVODE on the written SBML",
        },
        configuration=dict(
            categories=list(DEFAULT_CATEGORIES),
            max_cases=DEFAULT_MAX_CASES,
            selection_strategy="prefix",
            jobs=DEFAULT_JOBS,
            case_timeout=DEFAULT_CASE_TIMEOUT,
            simulation_t_end=SIMULATION_T_END,
            simulation_n_steps=SIMULATION_N_STEPS,
        ),
        results=rows,
    )
    return report


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument(
        "--suite-dir",
        type=Path,
        help="locked SBML Test Suite checkout at the revision in the source lock",
    )
    parser.add_argument("--categories", nargs="+", default=list(DEFAULT_CATEGORIES))
    parser.add_argument("--max-cases", type=int, default=DEFAULT_MAX_CASES)
    parser.add_argument(
        "--selection-strategy",
        choices=("prefix", "feature-cover"),
        default="prefix",
    )
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    parser.add_argument("--case-timeout", type=int, default=DEFAULT_CASE_TIMEOUT)
    args = parser.parse_args(argv)
    if args.report_dir.exists() and any(args.report_dir.iterdir()):
        parser.error("report directory must be empty")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    rows = run(
        args.report_dir,
        suite_dir=args.suite_dir,
        categories=tuple(args.categories),
        max_cases=args.max_cases,
        selection_strategy=args.selection_strategy,
        jobs=args.jobs,
        case_timeout=args.case_timeout,
    )
    report = build_report(rows, args.report_dir)
    (args.report_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (args.report_dir / "checks.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    failures = [row["id"] for row in rows if row["status"] == "FAIL"]
    for row in rows:
        print(f"{row['status']:>12}  {row['id']}")
    if failures:
        print("failing checks: " + ", ".join(failures))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
