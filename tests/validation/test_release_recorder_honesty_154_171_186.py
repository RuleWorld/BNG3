"""Negative controls for the release recorders of #154/#155/#156/#171/#172/#186.

A recorder must never report PASS for a named check whose test did not run,
whose artifact is missing, or whose evidence belongs to another revision.
These controls exercise those failure modes directly; they do not change any
expected product value, tolerance, seed or exclusion.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock
import xml.etree.ElementTree as ET

import pytest

from tests.validation.eq_catalogue import CASES, validate_catalogue_report

from scripts.ci import (
    record_bngir_release,
    record_bngir_roundtrip_release,
    record_issue155_release,
    record_issue171_release,
    record_issue172_release,
    record_issue186_release,
)

REV = "a" * 40


def _junit(path: Path, names: tuple[str, ...], *, skipped: tuple[str, ...] = ()) -> Path:
    suite = ET.Element("testsuite")
    for name in names:
        case = ET.SubElement(suite, "testcase", name=name)
        if name in skipped:
            ET.SubElement(case, "skipped")
    ET.ElementTree(suite).write(path)
    return path


def _checkout_stub(argv, **_kwargs):
    if "rev-parse" in argv:
        return REV + "\n"
    return ""


# --- 154/155/156: per-check execution is derived from the JUnit report. -------

@pytest.mark.parametrize(
    "recorder,checks",
    [
        (
            record_bngir_roundtrip_release,
            {
                "release-bngir-roundtrip": "test_release_bngir_roundtrip",
                "release-bngir-version": "test_release_bngir_version",
                "release-obligation-154": "test_release_obligation_154",
            },
        ),
        (
            record_bngir_release,
            {
                "release-bngir-schema": "test_release_bngir_schema",
                "release-semantic-equality": "test_release_semantic_equality",
                "release-capability-coverage-156": "test_release_capability_coverage_156",
            },
        ),
        (
            record_issue155_release,
            {
                "release-bngir-adversarial": "test_release_bngir_adversarial",
                "release-bngir-consumer": "test_release_bngir_consumer",
                "release-obligation-155": "test_release_obligation_155",
            },
        ),
    ],
)
def test_partial_or_skipped_junit_cannot_certify_full_check(tmp_path, recorder, checks):
    names = tuple(checks.values())
    # Every named test except the last actually executed and passed.
    report = _junit(tmp_path / "partial.xml", names[:-1])
    with pytest.raises(ValueError, match="did not execute"):
        recorder.build_release_record(junit_path=report, allow_dirty=True)

    # A skipped test is not an executed test.
    skipped = _junit(tmp_path / "skipped.xml", names, skipped=(names[0],))
    with pytest.raises(ValueError, match="skipped or failed"):
        recorder.build_release_record(junit_path=skipped, allow_dirty=True)

    # A full report of executed cases still yields PASS only for those names.
    full = _junit(tmp_path / "full.xml", names)
    rows = {
        row["id"]: row
        for row in recorder.build_release_record(junit_path=full, allow_dirty=True)[
            "results"
        ]
    }
    assert all(row["status"] == "PASS" for row in rows.values())
    assert all(row["supported_execution"] is True for row in rows.values())


def test_issue154_version_cannot_pass_with_zero_executed_cases():
    """Regression for the unconditional PASS on release-bngir-version."""
    with mock.patch.object(record_bngir_roundtrip_release, "run_tests", lambda root: []):
        report = record_bngir_roundtrip_release.build_release_record(allow_dirty=True)
    rows = {row["id"]: row for row in report["results"]}
    assert all(row["status"] == "NOT_TESTED" for row in rows.values())
    assert not rows["release-bngir-version"]["supported_execution"]


def test_missing_junit_artifact_is_rejected():
    with pytest.raises(ValueError, match="missing JUnit report"):
        record_bngir_roundtrip_release.build_release_record(
            junit_path=Path("/nonexistent/pytest.xml"), allow_dirty=True
        )


# --- 171/172/186: no named test, no disposition evidence, no PASS. -----------

RECEIVERS = [
    (
        record_issue171_release,
        (
            "test_release_python_api",
            "test_release_python_install",
            "test_release_capability_coverage_171",
        ),
        record_issue171_release.DISPOSITION_CHECKS,
    ),
    (
        record_issue172_release,
        (
            "test_release_python_consolidation",
            "test_release_python_legacy",
            "test_release_obligation_172",
        ),
        record_issue172_release.DISPOSITION_CHECKS,
    ),
    (
        record_issue186_release,
        (
            "test_release_migration_docs",
            "test_release_maintenance_docs",
            "test_release_obligation_186",
        ),
        record_issue186_release.DISPOSITION_CHECKS,
    ),
]


def _receipt(recorder, tmp_path, *, junit, disposition=None, revision=REV):
    output = tmp_path / f"{recorder.__name__}.json"
    argv = [
        "--source-revision",
        revision,
        "--output",
        str(output),
        "--allow-dirty",
    ]
    if junit is not None:
        argv += ["--junit", str(junit)]
    if disposition is not None:
        argv += ["--disposition-evidence", str(disposition)]
    with mock.patch.object(recorder.subprocess, "check_output", _checkout_stub):
        recorder.main(argv)
    return json.loads(output.read_text())


@pytest.mark.parametrize("recorder,tests,dispositions", RECEIVERS)
def test_partial_junit_cannot_certify_live_checks(
    recorder, tests, dispositions, tmp_path
):
    partial = _junit(tmp_path / "partial.xml", tests[:-1])
    with mock.patch.object(recorder.subprocess, "check_output", _checkout_stub):
        with pytest.raises(SystemExit, match="did not execute"):
            recorder.main(
                [
                    "--source-revision",
                    REV,
                    "--output",
                    str(tmp_path / "out.json"),
                    "--junit",
                    str(partial),
                    "--allow-dirty",
                ]
            )


@pytest.mark.parametrize("recorder,tests,dispositions", RECEIVERS)
def test_skipped_junit_cannot_certify_live_checks(
    recorder, tests, dispositions, tmp_path
):
    skipped = _junit(tmp_path / "skipped.xml", tests, skipped=(tests[0],))
    with mock.patch.object(recorder.subprocess, "check_output", _checkout_stub):
        with pytest.raises(SystemExit, match="did not execute"):
            recorder.main(
                [
                    "--source-revision",
                    REV,
                    "--output",
                    str(tmp_path / "out.json"),
                    "--junit",
                    str(skipped),
                    "--allow-dirty",
                ]
            )


@pytest.mark.parametrize("recorder,tests,dispositions", RECEIVERS)
def test_disposition_needs_exact_revision_evidence(
    recorder, tests, dispositions, tmp_path
):
    full = _junit(tmp_path / "full.xml", tests)
    # No disposition artifact: rows must stay NOT_TESTED, never PASS.
    report = _receipt(recorder, tmp_path, junit=full)
    rows = {row["id"]: row for row in report["results"]}
    for check in dispositions:
        assert rows[check]["status"] == "NOT_TESTED"
        assert rows[check]["supported_execution"] is False

    # A stale artifact (different revision) is refused.
    stale = tmp_path / "stale-disposition.json"
    stale.write_text(
        json.dumps(
            {
                "source": {"revision": "b" * 40},
                "results": [{"id": dispositions[0], "status": "PASS"}],
            }
        )
    )
    with mock.patch.object(recorder.subprocess, "check_output", _checkout_stub):
        with pytest.raises(SystemExit, match="stale revision"):
            recorder.main(
                [
                    "--source-revision",
                    REV,
                    "--output",
                    str(tmp_path / "reject.json"),
                    "--junit",
                    str(full),
                    "--disposition-evidence",
                    str(stale),
                    "--allow-dirty",
                ]
            )

    # An exact-revision artifact can discharge only the rows it actually names.
    evidence = tmp_path / "disposition.json"
    evidence.write_text(
        json.dumps(
            {
                "source": {"revision": REV},
                "results": [
                    {
                        "id": dispositions[0],
                        "status": "PASS",
                        "detail": "executed disposition check",
                    }
                ],
            }
        )
    )
    report = _receipt(recorder, tmp_path, junit=full, disposition=evidence)
    rows = {row["id"]: row for row in report["results"]}
    assert rows[dispositions[0]]["status"] == "PASS"
    assert rows[dispositions[0]]["evidence_kind"] == "disposition"
    for check in dispositions[1:]:
        assert rows[check]["status"] == "NOT_TESTED"


# --- #156: inventory membership cannot certify per-row EQ outcomes. ----------

def test_membership_only_eq_evidence_is_rejected():
    membership_only = {
        "acceptance_check": "release-semantic-equality",
        "case_count": len(CASES),
        "row_count": 2 * len(CASES),
        "results": [
            {
                "case": case.id,
                "variant": variant,
                "oracle": case.oracle,
                "expected": "equal",
                "observed": "equal",
                "status": "PASS",
            }
            for case in CASES
            for variant in ("equal", "different")
        ],
    }
    # Every declared outcome was overwritten with "equal" and no certificate
    # rows were executed, so the catalogue cannot be a real per-row result.
    with pytest.raises(ValueError, match="outcomes|missing rows"):
        validate_catalogue_report(membership_only)


def test_partial_eq_evidence_is_rejected():
    partial = {
        "acceptance_check": "release-semantic-equality",
        "case_count": len(CASES),
        "row_count": 2 * len(CASES),
        "results": [
            {
                "case": CASES[0].id,
                "variant": "equal",
                "oracle": CASES[0].oracle,
                "expected": CASES[0].equal_outcome,
                "observed": CASES[0].equal_outcome,
                "status": "PASS",
            }
        ],
    }
    with pytest.raises(ValueError, match="missing rows"):
        validate_catalogue_report(partial)
