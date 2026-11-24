"""Negative controls for the Issue 152 release recorder.

A partial fixture result (invariants only), a missing/stale native-NFsim
report, or a skipped test must not be reported as a full scientific PASS.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts.ci import record_issue152_release as rec

ROOT = Path(__file__).resolve().parents[2]
REV = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
NATIVE_REV = "9b00d42f734dcc3e695205600f12cae5b44d1daa"


def _native(revision=REV, native_rev=NATIVE_REV, families=None):
    families = (
        families
        if families is not None
        else {
            family: {
                "native_comparison": True,
                "seed_budget": 64,
                "independent_oracle": "native-NFsim@" + native_rev,
            }
            for family in rec.REQUIRED_FAMILIES
        }
    )
    return {
        "check": "release-energy-protocols",
        "status": "PASS",
        "source_revision": revision,
        "source_dirty": False,
        "native_revision": native_rev,
        "expected_native_revision": NATIVE_REV,
        "families": families,
    }


def _extension(rows=None):
    rows = (
        rows
        if rows is not None
        else {
            key: {"product_linked": True, "independent_expectation": "analytic"}
            for key in (
                "cycle_affinity",
                "driven_monotonicity",
                "barrier_detailed_balance",
            )
        }
    )
    return {
        "check": "release-extension-protocols",
        "status": "PASS",
        "source_revision": REV,
        "source_dirty": False,
        "checks": rows,
    }


def _build(executed=None, reports=None, **kwargs):
    executed = {} if executed is None else executed

    def fake(root):
        return executed

    mp = pytest.MonkeyPatch()
    mp.setattr(rec, "run_tests", fake)
    try:
        record = rec.build_release_record(
            expected_revision=REV,
            allow_dirty=True,
            root=ROOT,
            reports=reports or {},
            **kwargs,
        )
    finally:
        mp.undo()
    return {row["id"]: row for row in record["results"]}


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


def test_skipped_or_mocked_execution_cannot_be_scientific_pass():
    rows = _build(executed={}, skip_tests=True)
    for check_id in rec.REPORT_CHECKS:
        assert rows[check_id]["status"] == "NOT_TESTED"


def test_leaf_only_cannot_certify_energy_or_extension():
    rows = _build(executed={"release-obligation-152": {}})
    assert rows["release-obligation-152"]["status"] == "PASS"
    assert rows["release-energy-protocols"]["status"] == "NOT_TESTED"
    assert rows["release-extension-protocols"]["status"] == "NOT_TESTED"


def test_partial_native_report_cannot_satisfy_full_check(tmp_path):
    families = {
        family: {
            "native_comparison": family != "motor",
            "seed_budget": 64,
            "independent_oracle": "native-NFsim",
        }
        for family in rec.REQUIRED_FAMILIES
    }
    path = _write(tmp_path, "partial.json", _native(families=families))
    rows = _build(reports={"release-energy-protocols": path})
    assert rows["release-energy-protocols"]["status"] == "NOT_TESTED"


def test_pinned_native_revision_mismatch_is_rejected(tmp_path):
    path = _write(tmp_path, "drift.json", _native(native_rev="0" * 40))
    rows = _build(reports={"release-energy-protocols": path})
    assert rows["release-energy-protocols"]["status"] == "NOT_TESTED"


def test_missing_native_artifact_cannot_satisfy_check(tmp_path):
    rows = _build(reports={"release-energy-protocols": str(tmp_path / "none.json")})
    assert rows["release-energy-protocols"]["status"] == "NOT_TESTED"


def test_arithmetic_only_extension_report_is_rejected(tmp_path):
    rows_report = {
        key: {"product_linked": False, "independent_expectation": "arithmetic"}
        for key in ("cycle_affinity", "driven_monotonicity", "barrier_detailed_balance")
    }
    path = _write(tmp_path, "arith.json", _extension(rows=rows_report))
    rows = _build(reports={"release-extension-protocols": path})
    assert rows["release-extension-protocols"]["status"] == "NOT_TESTED"


def test_stale_extension_report_is_rejected(tmp_path):
    doc = _extension()
    doc["source_revision"] = "0" * 40
    path = _write(tmp_path, "stale.json", doc)
    rows = _build(reports={"release-extension-protocols": path})
    assert rows["release-extension-protocols"]["status"] == "NOT_TESTED"


def test_complete_reports_can_produce_pass(tmp_path):
    energy = _write(tmp_path, "energy.json", _native())
    extension = _write(tmp_path, "extension.json", _extension())
    rows = _build(
        reports={
            "release-energy-protocols": energy,
            "release-extension-protocols": extension,
        }
    )
    assert rows["release-energy-protocols"]["status"] == "PASS"
    assert rows["release-extension-protocols"]["status"] == "PASS"
