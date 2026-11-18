"""Negative controls for the Issue 160 capability receipt recorder.

The historical 6d2d4d3d receipt reported ``supported_execution: True`` for
every Core/comp row while 34 mapped cases were ``unsupported`` — including
required constructs (fast reactions, dynamic events). These controls pin that
a missing, refused, unsupported, timeout or stale-fixture case can never be
reported as demonstrated support for a #160 capability row.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_RECORDER = ROOT / "scripts/ci/record_issue160_release.py"
_spec = importlib.util.spec_from_file_location(
    "record_issue160_release", str(_RECORDER)
)
recorder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recorder)

REVISION = "6d2d4d3d1bc232599f3bbf0eb88a96f0b4311ab5"
CAPABILITY_MAPPING = ROOT / "provenance/sbml-capability-case-mapping.json"


def _mapping():
    return json.loads(CAPABILITY_MAPPING.read_text())


def _write_report(tmp_path, overrides=None):
    mapping = _mapping()
    case_ids = sorted(
        {
            cid
            for row, cases in mapping.items()
            if not row.startswith("_")
            for cid in cases
        }
    )
    overrides = overrides or {}
    report = {
        "suite_commit": "cf38585fac5de8e0e90112febb62851ee2181816",
        "source_provenance": {
            "bng3_commit": REVISION,
            "bng3_tracked_worktree_clean": True,
        },
        "partial_run": False,
        "case_inventory": 1923,
        "runtime_provenance": {"native_extension_sha256": "a" * 64},
        "suite_source_lock": {"revision": "cf38585f", "source_lock_sha256": "b" * 64},
        "records": [
            {
                "category": "semantic",
                "id": cid,
                "status": overrides.get(cid, "passed"),
            }
            for cid in case_ids
        ],
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    return path


def _write_fixtures(tmp_path, results=None):
    defaults = {name: True for name in recorder.FIXTURE_NAMES.values()}
    defaults.update(results or {})
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps({"fixtures": defaults}))
    return path


def _run(tmp_path, overrides=None, fixtures=None):
    report = _write_report(tmp_path, overrides)
    fixtures = fixtures if fixtures is not None else _write_fixtures(tmp_path)
    return recorder.build_receipt(
        report, CAPABILITY_MAPPING, REVISION, core_fixtures_report=fixtures
    )


def test_clean_report_emits_all_capability_rows(tmp_path):
    receipt = _run(tmp_path)
    assert len(receipt["results"]) >= 120
    assert all(r["supported_execution"] is True for r in receipt["results"])


def test_unsupported_mapped_case_fails_closed(tmp_path):
    case_id = _mapping()["sbml.core.SBase.metaid"][0]
    try:
        _run(tmp_path, {case_id: "unsupported"})
    except ValueError as exc:
        assert case_id in str(exc)
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("unsupported mapped case reported as capability support")


def test_missing_mapped_case_fails_closed(tmp_path):
    case_id = _mapping()["sbml.core.SBase.metaid"][0]
    report = _write_report(tmp_path)
    doc = json.loads(report.read_text())
    doc["records"] = [r for r in doc["records"] if r["id"] != case_id]
    report.write_text(json.dumps(doc))
    fixtures = _write_fixtures(tmp_path)
    try:
        recorder.build_receipt(
            report, CAPABILITY_MAPPING, REVISION, core_fixtures_report=fixtures
        )
    except ValueError as exc:
        assert case_id in str(exc)
    else:
        raise AssertionError("missing mapped case reported as capability support")


def test_negative_fixture_result_fails_closed(tmp_path):
    fixtures = _write_fixtures(tmp_path, {"parameter-units": False})
    try:
        _run(tmp_path, fixtures=fixtures)
    except ValueError as exc:
        assert "parameter-units" in str(exc)
    else:
        raise AssertionError(
            "a failed fixture result was reported as capability support"
        )


def test_missing_fixture_artifact_fails_closed(tmp_path):
    report = _write_report(tmp_path)
    try:
        recorder.build_receipt(
            report, CAPABILITY_MAPPING, REVISION, core_fixtures_report=None
        )
    except ValueError as exc:
        assert "fixture" in str(exc).lower()
    else:
        raise AssertionError("capability PASS self-authored without fixture evidence")
