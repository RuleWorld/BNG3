"""Positive and negative controls for #180 reconciliation delta execution verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci.record_reconciliation_deltas import (
    evaluate_ledger_deltas,
    match_test_reference,
    parse_junit_cases,
)
from scripts.ci.record_reconciliation_release import coverage_report

REVISION = "a" * 40
PINNED = {
    "bionetgen": "1" * 40,
    "nfsim": "2" * 40,
    "pybionetgen": "3" * 40,
}
LOCK = {"sources": {name: {"revision": rev} for name, rev in PINNED.items()}}


def _pin_report(revision=REVISION, errors=None, nfsim_rev=PINNED["nfsim"]):
    return {
        "source": {"revision": revision, "dirty": False},
        "errors": [] if errors is None else errors,
        "sources": {
            "bionetgen": {"checkout_revision": PINNED["bionetgen"], "errors": []},
            "nfsim": {"checkout_revision": nfsim_rev, "errors": []},
            "pybionetgen": {"checkout_revision": PINNED["pybionetgen"], "errors": []},
        },
    }


def _ledgers():
    return {
        "bionetgen": {
            "source": "bionetgen",
            "entries": [
                {
                    "source_revision": "b1" + "0" * 38,
                    "classification": "incorporated-equivalently",
                    "tests": ["tests/validation/test_sample.py::test_ok"],
                },
                {
                    "source_revision": "b2" + "0" * 38,
                    "classification": "pending-port",
                    "tests": ["tests/python/test_legacy_sample.py::test_legacy_ok"],
                },
                {
                    "source_revision": "b3" + "0" * 38,
                    "classification": "not-applicable",
                    "tests": [],
                },
            ],
        },
        "nfsim": {
            "source": "nfsim",
            "entries": [
                {
                    "source_revision": "n1" + "0" * 38,
                    "classification": "incorporated-equivalently",
                    "tests": ["tests/cpp/test_nfsim_ast_adapter.cpp::NFsim AST case"],
                },
                {
                    "source_revision": "n2" + "0" * 38,
                    "classification": "pending-port",
                    "tests": [
                        "tests/validation/test_totalrate.py::test_counterexample"
                    ],
                },
            ],
        },
        "pybionetgen": {
            "source": "pybionetgen",
            "entries": [
                {
                    "source_revision": "p1" + "0" * 38,
                    "classification": "incorporated-equivalently",
                    "tests": [
                        "tests/validation/test_reconciliation_evidence.py::test_pkg"
                    ],
                }
            ],
        },
    }


def _write_junit(tmp_path: Path, filename: str, body: str) -> Path:
    path = tmp_path / filename
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n' f"<testsuites>{body}</testsuites>\n",
        encoding="utf-8",
    )
    return path


def test_evaluates_incorporated_and_pending_port_deltas_honestly(tmp_path):
    py_xml = _write_junit(
        tmp_path,
        "py.xml",
        """
        <testsuite name="pytest">
          <testcase classname="test_sample" name="test_ok[p1]" />
          <testcase classname="tests.python.test_legacy_sample" name="test_legacy_ok" />
          <testcase classname="tests.validation.test_reconciliation_evidence" name="test_pkg" />
          <testcase classname="test_totalrate" name="test_counterexample">
            <properties>
              <property name="semantic_result" value="FAIL" />
            </properties>
          </testcase>
        </testsuite>
        """,
    )
    cpp_xml = _write_junit(
        tmp_path,
        "ctest.xml",
        """
        <testsuite name="CTest">
          <testcase name="native-port::NFsim AST case" classname="CTest" status="run" />
        </testsuite>
        """,
    )
    cases = parse_junit_cases([py_xml, cpp_xml])
    report = evaluate_ledger_deltas(
        ledgers=_ledgers(),
        lock=LOCK,
        pin_report=_pin_report(),
        cases=cases,
        revision=REVISION,
    )
    assert report["summary"] == {
        "total_non_applicable": 5,
        "passed": 3,
        "failed": 2,
        "pending_port": 2,
    }
    by_id = {row["id"]: row for row in report["results"]}
    assert (
        by_id[f"reconciliation-delta[bionetgen,{'b1' + '0' * 38}]"]["status"] == "PASS"
    )
    assert by_id[f"reconciliation-delta[nfsim,{'n1' + '0' * 38}]"]["status"] == "PASS"
    assert (
        by_id[f"reconciliation-delta[pybionetgen,{'p1' + '0' * 38}]"]["status"]
        == "PASS"
    )

    # Even when its tests pass, pending-port must NEVER emit PASS.
    pending_bng = by_id[f"reconciliation-delta[bionetgen,{'b2' + '0' * 38}]"]
    assert pending_bng["status"] == "FAIL"
    assert pending_bng["supported_execution"] is False
    assert pending_bng["evidence_kind"] == "observed-failure"

    # Assertion-free diagnostic with semantic_result=FAIL must record semantic failure.
    pending_nf = by_id[f"reconciliation-delta[nfsim,{'n2' + '0' * 38}]"]
    assert pending_nf["status"] == "FAIL"
    assert pending_nf["semantic_failures"] == [
        "tests/validation/test_totalrate.py::test_counterexample: semantic_result=FAIL"
    ]


def test_negative_controls_reject_skipped_missing_and_semantic_fail_for_incorporated(
    tmp_path,
):
    xml = _write_junit(
        tmp_path,
        "neg.xml",
        """
        <testsuite name="pytest">
          <testcase classname="test_sample" name="test_ok">
            <skipped message="skipped" />
          </testcase>
          <testcase classname="tests.validation.test_reconciliation_evidence" name="test_pkg">
            <properties>
              <property name="semantic_result" value="FAIL" />
            </properties>
          </testcase>
        </testsuite>
        """,
    )
    cases = parse_junit_cases([xml])
    report = evaluate_ledger_deltas(
        ledgers=_ledgers(),
        lock=LOCK,
        pin_report=_pin_report(),
        cases=cases,
        revision=REVISION,
    )
    by_id = {row["id"]: row for row in report["results"]}
    assert (
        by_id[f"reconciliation-delta[bionetgen,{'b1' + '0' * 38}]"]["status"] == "FAIL"
    )
    assert by_id[f"reconciliation-delta[nfsim,{'n1' + '0' * 38}]"]["status"] == "FAIL"
    assert by_id[f"reconciliation-delta[nfsim,{'n1' + '0' * 38}]"]["missing_tests"] == [
        "tests/cpp/test_nfsim_ast_adapter.cpp::NFsim AST case"
    ]
    assert (
        by_id[f"reconciliation-delta[pybionetgen,{'p1' + '0' * 38}]"]["status"]
        == "FAIL"
    )


def test_negative_controls_reject_stale_or_mismatched_pin_report(tmp_path):
    xml = _write_junit(tmp_path, "empty.xml", '<testsuite name="empty"/>')
    cases = parse_junit_cases([xml])
    with pytest.raises(ValueError, match="pin report"):
        evaluate_ledger_deltas(
            ledgers=_ledgers(),
            lock=LOCK,
            pin_report=_pin_report(revision="f" * 40),
            cases=cases,
            revision=REVISION,
        )
    with pytest.raises(ValueError, match="nfsim: pin report checkout"):
        evaluate_ledger_deltas(
            ledgers=_ledgers(),
            lock=LOCK,
            pin_report=_pin_report(nfsim_rev="9" * 40),
            cases=cases,
            revision=REVISION,
        )


def test_class_method_ref_matching_and_release_consumer_compatibility(tmp_path):
    xml = _write_junit(
        tmp_path,
        "cls.xml",
        """
        <testsuite name="pytest">
          <testcase classname="tests.python.test_cpp_backend.TestSimulation" name="test_simulate_nf" />
        </testsuite>
        """,
    )
    cases = parse_junit_cases([xml])
    hits = match_test_reference(
        "tests/python/test_cpp_backend.py::TestSimulation::test_simulate_nf", cases
    )
    assert len(hits) == 1 and hits[0].passed

    # Also verify coverage_report rejects behavior reports when semantic_result is absent
    # or check fails.
    cov = coverage_report(
        [{"id": "nf.option.cb", "upstream": "nfsim:src/NFsim.cpp:cb"}],
        LOCK,
        [
            {
                "source": {"revision": REVISION, "dirty": False},
                "references": {"nfsim": {"revision": PINNED["nfsim"]}},
                "results": [
                    {
                        "id": "release-capability[nf.option.cb]",
                        "status": "PASS",
                        "evidence_kind": "supported-execution",
                        "supported_execution": True,
                    }
                ],
            }
        ],
        REVISION,
    )
    assert cov["missing_rows"] == []
    assert cov["observed_rows"] == {"nf.option.cb": "PASS"}
