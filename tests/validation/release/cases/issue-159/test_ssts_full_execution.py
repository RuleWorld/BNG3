"""Executable selectors for the two fully-grounded Issue 159 live checks.

These consume an exact-main full SSTS report and its receipt, produced by
scripts/ci/record_issue159_release.py. They verify only the evidence contract:
full non-partial run, exact revision, zero failed/timeout/invalid-source, and
recorded identities. No scientific expectation or verdict is authored here.
"""

import json
import os
from pathlib import Path
import sys

import pytest

_ROOT = Path(__file__).resolve().parents[5]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.ci import sbml_noncomparable_disposition as disposition

_SUITE_REPORT = os.environ.get("BNG3_SSTS_FULL_REPORT")
_RECEIPT = os.environ.get("BNG3_ISSUE159_RECEIPT")
_FIXTURES = Path(__file__).resolve().parents[5] / "provenance/core-fixtures"


def _load(path, label):
    if not path:
        pytest.skip(f"{label} not provided in this environment")
    return json.loads(Path(path).read_text(encoding="utf-8"))


_REPORT_CACHE = {}


def report_cache():
    """Load the full report once; None when no report was provided."""
    if "report" not in _REPORT_CACHE:
        _REPORT_CACHE["report"] = (
            _load(_SUITE_REPORT, "BNG3_SSTS_FULL_REPORT") if _SUITE_REPORT else None
        )
    return _REPORT_CACHE["report"]


def test_release_ssts_exact_full_run():
    """release-ssts: exact-revision full suite with zero blocking outcomes."""
    report = _load(_SUITE_REPORT, "BNG3_SSTS_FULL_REPORT")
    revision = os.environ.get("BNG3_EXACT_REVISION")
    assert revision and len(revision) == 40
    prov = report["source_provenance"]
    assert prov["bng3_commit"] == revision
    assert prov["bng3_tracked_worktree_clean"] is True
    assert report["partial_run"] is False
    assert report["case_inventory"] == report["selected_cases"] >= 1923
    counts = report["counts"]
    for key in ("failed", "timeout", "invalid-source"):
        assert counts[key] == 0
    official = report["official_conformance"]["counts"]
    assert official["failed"] <= 1 and official["timed-out"] == 0
    if official["failed"] == 1:
        off_failures = [
            (r["category"], r["id"])
            for r in report.get("records", [])
            if (
                r.get("official_conformance", {}).get("status") == "failed"
                or r.get("stages", {}).get("official_reference", {}).get("status")
                == "failed"
            )
        ]
        assert off_failures == [("stochastic", "00003")]


def test_release_obligation_159_receipt():
    """release-obligation-159: identities and main revision are recorded."""
    receipt = _load(_RECEIPT, "BNG3_ISSUE159_RECEIPT")
    revision = os.environ.get("BNG3_EXACT_REVISION")
    assert revision and len(revision) == 40
    assert receipt["source"]["revision"] == revision
    assert receipt["source"]["dirty"] is False
    rows = {row["id"]: row for row in receipt["results"]}
    # The receipt is the sole structural carrier of all three live #159
    # acceptance identities to the closure gate. Require exactly those three;
    # the coverage row must additionally be grounded in a real fixture
    # execution artifact (fixtures_report_sha256) and report digest, so an
    # ungrounded, self-authored coverage PASS cannot satisfy this check.
    expected = {"release-ssts", "release-ssts-coverage", "release-obligation-159"}
    assert set(rows) == expected
    # The random-event-order case is an explicit non-comparable disposition,
    # never an acceptance PASS and never a silent skip.
    dispositions = receipt.get("dispositions") or []
    assert len(dispositions) == 1
    row = dispositions[0]
    assert row["id"] == "non-comparable:semantic/00965"
    assert row["status"] == disposition.DISPOSITION_STATUS
    assert row["evidence_kind"] == disposition.DISPOSITION_EVIDENCE_KIND
    assert row["supported_execution"] is False
    assert row["counts_as_pass"] is False
    assert row["reason"] == disposition.REASON
    assert row["spec_basis"] == list(disposition.SPEC_BASIS)
    assert rows["release-ssts-coverage"]["receipt"]["disposition_ids"] == [row["id"]]
    assert rows["release-ssts"]["evidence_kind"] == "supported-execution"
    assert rows["release-ssts"]["supported_execution"] is True
    coverage = rows["release-ssts-coverage"]
    assert coverage["evidence_kind"] == "supported-execution"
    assert coverage["supported_execution"] is True
    assert coverage["receipt"]["fixtures_report_sha256"]
    assert len(coverage["receipt"]["fixtures_report_sha256"]) == 64
    assert coverage["receipt"]["report_sha256"]
    assert coverage["receipt"]["core_rows_checked"] >= 104
    # The catalog declares these as supported-execution; do not weaken them.
    assert rows["release-obligation-159"]["evidence_kind"] == "supported-execution"
    assert receipt["references"]["ssts"]["revision"]


def test_release_ssts_coverage():
    """release-ssts-coverage: every Core row has an executing independent case.

    The committed mapping pairs 100 Core rows with pinned SSTS cases; the four
    rows absent from the official suite use the analytic fixtures. Assignment
    to the fixture list, XML presence, a clean process, or an ``unsupported``
    verdict cannot qualify a row: each mapped case must have actually executed
    and passed, and each suite-absent row must be backed by a real fixture
    execution report, not just the fixture file. The single pinned random-event
    order case is the only exception: it qualifies only through an exact
    identity check of the harness-generated reason and spec basis and is
    recorded as NON_COMPARABLE, never as a pass.
    """
    if not _SUITE_REPORT and not os.environ.get("BNG3_CORE_FIXTURES_REPORT"):
        pytest.skip("no full SSTS report or Core fixture execution report provided")
    root = Path(__file__).resolve().parents[5]
    contract = json.loads(
        (root / "tests/validation/release/cases/issue-159/contract.json").read_text()
    )
    core_rows = contract["inventory_rows"]
    mapping = json.loads((root / "provenance/sbml-core-case-mapping.json").read_text())
    fixtures = set(mapping.get("_meta", {}).get("uncovered_rows", []))
    assert len(core_rows) == 104
    fixture_names = {
        "sbml.core.Parameter.units": "parameter-units",
        "sbml.core.Constraint.message": "constraint-message",
        "sbml.core.Reaction.compartment": "reaction-compartment",
        "sbml.core.LocalParameter.units": "localparameter-units",
        "sbml.core.SBase.annotation": "sbase-annotation",
    }
    fixture_report_path = os.environ.get("BNG3_CORE_FIXTURES_REPORT")
    fixture_results = {}
    if fixture_report_path:
        fixture_report = json.loads(
            Path(fixture_report_path).read_text(encoding="utf-8")
        )
        fixture_results = fixture_report.get("fixtures", {})
    for row in core_rows:
        if row in fixtures:
            fixture = fixture_names[row]
            assert (
                _FIXTURES / f"{fixture}.xml"
            ).is_file(), f"{row}: missing analytic fixture source {fixture}.xml"
            # File presence is not execution evidence. The producer must supply
            # an affirmative per-fixture result from an actual native run.
            assert fixture_report_path, (
                f"{row}: BNG3_CORE_FIXTURES_REPORT not provided; fixture XML "
                "presence cannot qualify a suite-absent Core row"
            )
            assert fixture_results.get(fixture) is True, (
                f"{row}: fixture {fixture} has no affirmative passing execution "
                f"in BNG3_CORE_FIXTURES_REPORT"
            )
        else:
            cases = mapping.get(row) or []
            assert cases, f"Core row {row} has no independent case"
            if not _SUITE_REPORT:
                continue
            report = report_cache()
            assert report is not None
            records = {(r["category"], r["id"]): r for r in report["records"]}
            for case_id in cases:
                key = ("semantic", case_id)
                assert key in records, f"{row}: mapped case {case_id} missing"
                record = records[key]
                try:
                    noncomparable = disposition.classify(
                        row, "semantic", case_id, record
                    )
                except ValueError as exc:
                    raise AssertionError(
                        f"{row}: mapped case {case_id} non-comparable identity "
                        f"mismatch: {exc}"
                    ) from exc
                if noncomparable is not None:
                    continue
                assert record["status"] == "passed", (
                    f"{row}: mapped case {case_id} status={record['status']}; "
                    "unsupported/not-tested cannot qualify row coverage"
                )
