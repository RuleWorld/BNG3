"""Issue #148 live gate: full TIER_NF corpus, NFnext against pinned native NFsim.

The harness runs every model in ``corpus.TIER_NF`` through the production
``cpp.simulate_nfnext`` binding, generates the oracle XML with pinned BNG2, and
executes the pinned native NFsim binary on the same source.  This module is the
leaf pytest selector and the evidence consumer: it verifies the report contract,
the negative controls and the single-engine routes, then refuses to claim the
release check unless every corpus row is a real PASS.

With oracles unset the report is still emitted with NOT_TESTED rows, and
``require_oracle`` turns that into a skip locally or a hard failure in strict CI.
A skip is never counted as support.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.validation import corpus, nfnext_native_corpus as harness  # noqa: E402
from tests.validation.strict import require_oracle  # noqa: E402

_CACHE: dict[str, dict] = {}


def _report(tmp_path: Path) -> dict:
    """Run the campaign once per pytest session and reuse its report."""
    if "report" not in _CACHE:
        _CACHE["report"] = harness.run(tmp_path / "campaign")
    return _CACHE["report"]


def _assert_report_contract(report: dict, tmp_path: Path) -> None:
    destination = os.environ.get(harness.REPORT_ENV)
    if destination:
        assert report.get("report_path") == str(Path(destination).resolve())
        path = Path(destination)
        assert path.is_file(), f"report artifact was not written: {path}"
        assert json.loads(path.read_text(encoding="utf-8"))["check"] == harness.CHECK_ID
    assert report["check"] == harness.CHECK_ID
    assert len(report["source"]["revision"]) == 40
    assert report["plan"]["declared_before_execution"] is True
    assert report["plan"]["exclusions"] == []
    assert set(report["plan"]["models"]) == set(corpus.TIER_NF)
    assert report["plan"]["seed_count"] >= 32
    assert len(report["models"]) == len(corpus.TIER_NF)
    assert {row["model"] for row in report["models"]} == set(corpus.TIER_NF)
    assert all(row["status"] in harness.STATUSES for row in report["models"])
    assert all(
        row["evidence_kind"] == "supported-execution" and row["supported_execution"]
        for row in report["models"]
        if row["status"] == "PASS"
    )
    # A model that did not execute can never be reported as a pass.
    assert all(
        not row["supported_execution"]
        for row in report["models"]
        if row["status"] != "PASS"
    )
    assert report["summary"]["model_count"] == len(corpus.TIER_NF)


def _assert_oracles(report: dict) -> None:
    require_oracle(
        bool(report["oracles"]["bng2"]["available"]),
        "pinned BNG2 unavailable (set BNG2_PERL)",
    )
    require_oracle(
        bool(report["oracles"]["nfsim"]["available"]),
        "pinned native NFsim unavailable (set NFSIM_BIN)",
    )
    assert report["oracles"]["bng2"]["script_digest"]
    assert report["oracles"]["nfsim"]["binary_digest"]
    assert report["oracles"]["nfsim"]["revision"]
    assert len(report["oracles"]["nfsim"]["binary_digest"]) == 64


def test_release_nfnext_full_corpus_native_parity(tmp_path: Path) -> None:
    """release-nfnext-execution: every TIER_NF row must be a real parity PASS."""
    report = _report(tmp_path)
    _assert_report_contract(report, tmp_path)
    _assert_oracles(report)

    failures = [
        f"{row['model']}={row['status']} ({row['detail']})"
        for row in report["models"]
        if row["status"] != "PASS"
    ]
    assert report["summary"]["all_models_pass"] is True, (
        "release-nfnext-execution is not satisfied; no model may be excluded "
        "after results: " + "; ".join(failures)
    )
    assert report["summary"]["release_check_satisfied"] is True


def test_release_nfnext_routes_single_engine(tmp_path: Path) -> None:
    """release-nfnext-routes: both public routes stay on the NFnext engine."""
    report = _report(tmp_path)
    _assert_report_contract(report, tmp_path)
    _assert_oracles(report)

    routes = report["routes"]
    assert routes["status"] == "PASS", routes
    assert routes["binding"]["status"] == "PASS", routes["binding"]
    assert routes["binding"]["engine"] == "nfnext"
    assert routes["single_engine"] is True
    if routes["public_api"]["status"] == "PASS":
        assert routes["public_api"]["backend"] == "nfnext"
    for row in report["models"]:
        if row["status"] == "PASS":
            assert row["engines"] == ["nfnext"]


def test_release_nfnext_comparator_negative_controls(tmp_path: Path) -> None:
    """The comparator must reject a wrong rate and a frozen observable."""
    report = _report(tmp_path)
    _assert_report_contract(report, tmp_path)
    _assert_oracles(report)

    controls = report["negative_controls"]
    assert controls["positive_control"]["status"] == "PASS", controls
    assert controls["wrong_rate_control"]["status"] == "FAIL", controls
    assert controls["frozen_observable_control"]["status"] == "FAIL", controls
    assert controls["rejects_wrong_law"] is True
