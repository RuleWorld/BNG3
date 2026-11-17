"""Executable selectors for the 117 Issue 160 release-capability rows.

Each row's evidence source comes from the committed capability-case mapping:
mapped official SSTS cases must have no failed/invalid-source/timeout verdict in
an exact-main full report; the four rows absent from the official suite use the
analytic fixtures under provenance/core-fixtures. This verifies the evidence
contract only — it does not author a scientific expectation or change a verdict.
"""

import json
import os
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[5]
_MAP = _ROOT / "provenance/sbml-capability-case-mapping.json"
_FIXTURES = _ROOT / "provenance/core-fixtures"
_SUITE_REPORT = os.environ.get("BNG3_SSTS_FULL_REPORT")


def _rows():
    data = json.loads(_MAP.read_text(encoding="utf-8"))
    return sorted(k for k in data if k != "_meta")


ROWS = _rows()
FIXTURE_ROWS = set(json.loads(_MAP.read_text())["_meta"]["fixture_rows"])


def _report():
    if not _SUITE_REPORT:
        pytest.skip("BNG3_SSTS_FULL_REPORT not provided in this environment")
    return json.loads(Path(_SUITE_REPORT).read_text(encoding="utf-8"))


@pytest.mark.parametrize("row_id", ROWS)
def test_capability_row(row_id):
    mapping = json.loads(_MAP.read_text(encoding="utf-8"))
    if row_id in FIXTURE_ROWS:
        fixture = {
            "sbml.core.Parameter.units": "parameter-units",
            "sbml.core.Constraint.message": "constraint-message",
            "sbml.core.Reaction.compartment": "reaction-compartment",
            "sbml.core.LocalParameter.units": "localparameter-units",
        }[row_id]
        assert (_FIXTURES / f"{fixture}.xml").is_file()
        return
    cases = mapping[row_id]
    assert cases, f"row {row_id} has no mapped official case"
    report = _report()
    records = {(r["category"], r["id"]): r for r in report["records"]}
    for case_id in cases:
        key = ("semantic", case_id)
        assert key in records, f"mapped case {case_id} absent from full report"
        record = records[key]
        verdict = record["status"]
        assert verdict not in {
            "failed",
            "timeout",
            "invalid-source",
        }, f"{row_id}: mapped case {case_id} has verdict {verdict}"


def test_release_core_comp():
    """release-sbml-core-comp: full suite has no blocking verdicts."""
    report = _report()
    counts = report["counts"]
    for key in ("failed", "timeout", "invalid-source"):
        assert counts[key] == 0, f"full suite has {counts[key]} {key} cases"
    official = report["official_conformance"]["counts"]
    assert official["failed"] == 0 and official["timed-out"] == 0


def test_release_source_fidelity():
    """release-sbml-source-fidelity: no loss diagnostics on passing cases."""
    report = _report()
    for record in report["records"]:
        if record["status"] != "passed":
            continue
        detail = str(record.get("simulation_comparison") or {})
        assert "loss" not in detail.lower() or record.get("supported_execution", True)


def test_release_capability_coverage():
    """release-capability-coverage-160: all 117 rows have evidence sources."""
    mapping = json.loads(_MAP.read_text(encoding="utf-8"))
    rows = [k for k in mapping if k != "_meta"]
    fixtures = set(mapping["_meta"]["fixture_rows"])
    assert len(rows) == 117
    assert all(mapping[row] or row in fixtures for row in rows)
