"""Fault controls for the corpus selection reconciliation (#181).

The selection is a recorded, frozen artifact.  These tests inject the faults
that would make its reconciliation meaningless: a model that is selected
without a reason, a reason that no longer matches the model file, a failed
model that quietly disappears from the selection, and an empty tier that
hides its emptiness.
"""

from __future__ import annotations

import copy

from tests.validation import corpus_selection as selection
from tests.validation import integrated_extensions as extensions


def _by_check(rows):
    return {row["check"]: row for row in rows}


def test_the_recorded_selection_is_reconciled_with_the_retained_workflow():
    rows = _by_check(selection.run())
    for name in selection.CHECKS:
        assert rows[name]["status"] == "PASS", rows[name]


def test_the_selection_counts_agree_with_the_retained_workflow():
    document = selection.manifest()
    workflow = selection._retained_workflow()
    assert len(document["tiers"]["p"]) == (
        workflow["selected_model_count"] + len(workflow["unselected_on_disk_models"])
    )
    assert workflow["result"].startswith("71 passed, 29 failed")


def test_every_selected_model_records_a_reason_and_a_provenance():
    document = selection.manifest()
    assert document["records"]
    reasons = set()
    for record in document["records"]:
        selection_ = record["selection"]
        assert selection_["reason"].strip()
        assert selection_["tiers"] == record["tiers"]
        assert selection_["capability"].strip()
        assert selection_["provenance"] in {
            "frozen-selection",
            "added-after-the-frozen-selection",
        }
        reasons.add(selection_["reason"])
    # No two selected models share one reason, so the reason is specific.
    assert len(reasons) == len(document["records"])


def test_a_model_without_a_reason_is_refused():
    document = copy.deepcopy(selection.manifest())
    document["records"][0]["selection"]["reason"] = ""
    rows = _by_check(selection.assess(document, selection._retained_workflow()))
    assert rows["tier-justification"]["status"] == "FAIL"


def test_a_reason_that_does_not_match_the_model_file_is_refused():
    document = copy.deepcopy(selection.manifest())
    document["records"][0]["selection"]["reason"] = "selected because it is nice"
    rows = _by_check(selection.assess(document, selection._retained_workflow()))
    assert rows["tier-justification"]["status"] == "FAIL"
    assert rows["tier-justification"]["stale_reasons"]


def test_a_dropped_failure_is_refused():
    document = copy.deepcopy(selection.manifest())
    failed = next(
        entry
        for entry in document["reconciliation"]["failure_categories"].values()
        for entry in entry["models"]
    )
    document["tiers"]["p"] = [
        model for model in document["tiers"]["p"] if model != failed
    ]
    rows = _by_check(selection.assess(document, selection._retained_workflow()))
    assert rows["selection-agreement"]["status"] == "FAIL"


def test_an_unapproved_selection_is_refused():
    document = copy.deepcopy(selection.manifest())
    document["accepted_selections"]["approved_tiers"] = ["p"]
    rows = _by_check(selection.assess(document, selection._retained_workflow()))
    assert rows["selection-agreement"]["status"] == "FAIL"


def test_an_empty_tier_without_a_recorded_reason_is_refused():
    document = copy.deepcopy(selection.manifest())
    document["tier_justifications"]["x"].pop("empty_reason")
    rows = _by_check(selection.assess(document, selection._retained_workflow()))
    assert rows["empty-tier-reporting"]["status"] == "FAIL"


def test_the_empty_tiers_are_reported_with_their_owner_and_budget():
    document = selection.manifest()
    empty = [tier for tier in selection.TIERS if not document["tiers"][tier]]
    assert empty == ["x", "b"]
    for tier in empty:
        entry = document["tier_justifications"][tier]
        assert entry["empty_reason"].strip()
        assert entry["owner"].strip()
        assert entry["budget"]


def test_the_operation_is_registered_in_the_campaign_registry():
    assert "corpus-selection" in extensions.OPERATIONS
    assert extensions.check_ids("corpus-selection") == selection.check_ids()
    assert set(selection.check_ids()) <= set(extensions.expected_ids([]))
    for name in selection.OBLIGATION_CHECKS:
        assert f"qualification:issue:181:{name}" in selection.check_ids()
