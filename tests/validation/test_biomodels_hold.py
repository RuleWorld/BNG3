"""Fault controls for the curated BioModels hold and its retention (#162).

The full curated BioModels corpus is on hold.  These tests inject the faults
that would make the hold or the retention meaningless: a plan that claims
the corpus is closable, a corpus manifest that lost its pin, and a retention
that merges the invalid-source category with another one.
"""

from __future__ import annotations

import copy
import json

from tests.validation import biomodels_hold as hold
from tests.validation import integrated_extensions as extensions


def _by_check(rows):
    return {row["check"]: row for row in rows}


def _manifest():
    return json.loads(hold.MANIFEST.read_text(encoding="utf-8"))


def test_the_recorded_hold_stays_in_effect():
    rows = _by_check(hold.run())
    stop = rows["stop-in-effect"]
    assert stop["status"] == "PASS"
    # The hold is a diagnostic: it claims no result and no category count.
    assert stop["evidence_kind"] == "diagnostic-only"
    assert stop["supported_execution"] is False
    assert stop["corpus_executed"] is False


def test_the_pinned_corpus_is_retained():
    rows = _by_check(hold.run())
    pin = rows["corpus-pin"]
    assert pin["status"] == "PASS"
    manifest = _manifest()
    assert manifest["snapshot_date"]
    assert manifest["expected_total_records"] > 0
    assert manifest["curation_query"]


def test_the_five_result_categories_stay_separate():
    rows = _by_check(hold.run())
    retention = rows["result-retention"]
    assert retention["status"] == "PASS"
    assert retention["category_counts"] == {
        "passed": 1,
        "unsupported": 1,
        "failed": 1,
        "timeout": 1,
        "invalid_source": 1,
    }
    assert set(retention["campaign_statuses"]) >= {
        "PASS",
        "UNSUPPORTED",
        "FAIL",
        "TIMEOUT",
        "INVALID_INPUT",
    }


def test_a_plan_that_claims_the_corpus_is_closable_is_refused():
    audit = copy.deepcopy(hold._audit_row())
    audit["closure_eligible"] = True
    rows = _by_check(hold.assess(audit, _manifest()))
    assert rows["stop-in-effect"]["status"] == "FAIL"


def test_a_plan_that_drops_the_open_obligations_is_refused():
    audit = copy.deepcopy(hold._audit_row())
    audit["remaining_obligations"] = []
    rows = _by_check(hold.assess(audit, _manifest()))
    assert rows["stop-in-effect"]["status"] == "FAIL"


def test_a_corpus_manifest_without_its_pin_is_refused():
    manifest = copy.deepcopy(_manifest())
    manifest["snapshot_date"] = ""
    rows = _by_check(hold.assess(hold._audit_row(), manifest))
    assert rows["corpus-pin"]["status"] == "FAIL"


def test_a_retention_that_drops_the_corpus_binding_is_refused():
    from scripts.ci.sbml_campaign_inventory import biomodels_inventory

    report = hold._generated_report()
    report["corpus"] = {}
    inventory = biomodels_inventory(report)
    assert not inventory["corpus"]["manifest"]
    assert not inventory["corpus"]["manifest_sha256"]


def test_an_invalid_source_is_not_merged_with_a_failure():
    from scripts.ci.sbml_campaign_inventory import biomodels_inventory

    report = hold._generated_report()
    inventory = biomodels_inventory(report)
    assert inventory["category_counts"]["invalid_source"] == 1
    assert inventory["category_counts"]["failed"] == 1
    assert inventory["status_counts"]["invalid_source"] == 1


def test_the_operation_is_registered_in_the_campaign_registry():
    assert "biomodels-hold" in extensions.OPERATIONS
    assert extensions.check_ids("biomodels-hold") == hold.check_ids()
    assert set(hold.check_ids()) <= set(extensions.expected_ids([]))
    assert f"qualification:issue:162:{hold.OBLIGATION_CHECK}" in hold.check_ids()
