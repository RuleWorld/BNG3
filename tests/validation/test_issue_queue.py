"""Negative controls for issue/evidence reconciliation, not product simulations."""

import pytest

from tests.validation import issue_queue

REVISION = "a" * 40
ISSUES = [
    dict(number=141, title="Model reuse", state="OPEN", body=""),
    dict(
        number=179,
        title="Approve provenance",
        state="OPEN",
        body="**Type:** maintainer/product decision",
    ),
]


def report(rows):
    return dict(
        source=dict(revision=REVISION, dirty=False),
        results=rows,
        capabilities=[dict(id="reuse", kind="semantic-claim", issues=[141])],
    )


def test_green_process_without_behavior_evidence_remains_an_evidence_gap():
    rows = [dict(id="reuse:process", status="PASS", stage="api", related_issues=[141])]
    queue = issue_queue.build_queue(ISSUES, [report(rows)], REVISION)
    assert queue[0]["disposition"] == "EVIDENCE_GAP"
    assert queue[1]["disposition"] == "DECISION_REQUIRED"
    assert all(not row["closure_eligible"] for row in queue)


def test_observed_failure_becomes_a_bounded_investigation_not_a_closure_claim():
    rows = [
        dict(
            id="reuse:trajectory",
            status="FAIL",
            stage="reuse",
            check="values",
            related_issues=[141],
            first_difference=dict(time=1, column="A"),
        )
    ]
    queue = issue_queue.build_queue(ISSUES, [report(rows)], REVISION)
    assert queue[0]["disposition"] == "OBSERVED_FAILURE"
    assert queue[0]["next_action"] == "investigate-recorded-contract"
    assert queue[0]["evidence_ids"] == ["reuse:trajectory"]
    assert queue[0]["outcomes"] == {"FAIL": 1}


def test_stale_or_conflicting_observations_cannot_be_joined_as_current_evidence():
    stale = report([])
    stale["source"]["revision"] = "b" * 40
    with pytest.raises(ValueError, match="revision"):
        issue_queue.build_queue(ISSUES, [stale], REVISION)
    row = dict(
        id="reuse:trajectory",
        status="PASS",
        stage="reuse",
        check="values",
        related_issues=[141],
    )
    with pytest.raises(ValueError, match="conflicting"):
        issue_queue.build_queue(
            ISSUES, [report([row]), report([dict(row, status="FAIL")])], REVISION
        )


def test_duplicate_reports_do_not_inflate_coverage_or_hide_unmapped_issues():
    row = dict(
        id="reuse:trajectory",
        status="PASS",
        stage="reuse",
        check="values",
        related_issues=[141],
    )
    issues = ISSUES + [dict(number=170, title="Formal decision", state="OPEN", body="")]
    queue = issue_queue.build_queue(issues, [report([row]), report([row])], REVISION)
    assert queue[0]["outcomes"] == {"PASS": 1}
    assert queue[0]["disposition"] == "PARTIAL_EXECUTION"
    assert next(r for r in queue if r["number"] == 170)["disposition"] == "UNMAPPED"


def test_upstream_drift_is_identity_checked_and_never_auto_approved():
    lock = dict(
        sources=dict(
            nfsim=dict(
                repository="https://github.com/RuleWorld/NFsim.git",
                revision="a" * 40,
                branch="master",
                status="observed",
            )
        )
    )
    heads = dict(
        sources=dict(
            nfsim=dict(
                repository="https://github.com/RuleWorld/NFsim.git",
                branch="master",
                revision="b" * 40,
            )
        )
    )
    drift = issue_queue.source_drift(lock, heads)
    assert drift[0]["status"] == "DRIFTED"
    assert drift[0]["approval"] == "observed"
    heads["sources"]["nfsim"]["repository"] = "https://example.com/unrelated"
    with pytest.raises(ValueError, match="repository"):
        issue_queue.source_drift(lock, heads)


def test_dirty_revision_and_duplicate_rows_are_rejected_but_null_body_is_valid():
    dirty = report([])
    dirty["source"]["dirty"] = True
    with pytest.raises(ValueError, match="dirty"):
        issue_queue.build_queue(ISSUES, [dirty], REVISION)
    row = dict(id="duplicate", status="PASS", stage="reuse", check="values")
    with pytest.raises(ValueError, match="duplicate"):
        issue_queue.build_queue(ISSUES, [report([row, row])], REVISION)
    issue = dict(number=141, title="Bodyless issue", state="OPEN", body=None)
    assert (
        issue_queue.build_queue([issue], [], REVISION)[0]["disposition"] == "UNMAPPED"
    )
