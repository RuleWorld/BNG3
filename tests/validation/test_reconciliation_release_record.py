"""Controls for the reconciled source coverage evidence gate."""

from scripts.ci.record_reconciliation_release import coverage_report

REVISION = "b" * 40
UPSTREAM = "a" * 40
ROWS = [
    dict(id="action.simulate", upstream="bionetgen:bng2/Perl2/BNGAction.pm:simulate"),
    dict(id="action.visualize", upstream="bionetgen:bng2/Perl2/BNGOutput.pm:visualize"),
]
LOCK = {"sources": {"bionetgen": {"revision": UPSTREAM}}}


def evidence(*rows, revision=REVISION):
    return {
        "source": {"revision": revision, "dirty": False},
        "references": {"bionetgen": {"revision": UPSTREAM}},
        "results": list(rows),
    }


def observation(row_id, **values):
    return {
        "id": f"release-capability[{row_id}]",
        "status": "PASS",
        "evidence_kind": "supported-execution",
        "supported_execution": True,
        **values,
    }


def test_structural_inventory_and_green_aggregate_do_not_show_behavior():
    records = [
        evidence(observation("action.simulate", aggregate=True)),
        evidence(observation("action.visualize"), revision="c" * 40),
    ]
    result = coverage_report(ROWS, LOCK, records, REVISION)
    assert result["missing_rows"] == ["action.simulate", "action.visualize"]
    assert result["observed_rows"] == {}


def test_records_an_observed_mismatch_without_claiming_support():
    records = [
        evidence(
            observation("action.simulate"),
            observation("action.visualize", status="FAIL", supported_execution=False),
        ),
    ]
    result = coverage_report(ROWS, LOCK, records, REVISION)
    assert result["missing_rows"] == []
    assert result["observed_rows"] == {
        "action.simulate": "PASS",
        "action.visualize": "FAIL",
    }


def test_disagreed_receipts_cannot_complete_a_mapping():
    records = [
        evidence(observation("action.simulate")),
        evidence(
            observation("action.simulate", status="FAIL", supported_execution=False)
        ),
    ]
    result = coverage_report(ROWS, LOCK, records, REVISION)
    assert result["conflicting_rows"] == ["action.simulate"]
    assert result["observed_rows"] == {}


def test_accepts_a_recorded_analytic_law_and_rejects_loss_diagnostics():
    record = evidence(
        observation("action.simulate", oracle_kind="analytic"),
        observation("action.visualize", diagnostics=[{"severity": "unsupported"}]),
    )
    record["references"]["analytic"] = {
        "law": "The expected value is constant for zero transitions.",
        "source_sha256": "1" * 64,
    }
    result = coverage_report(ROWS, LOCK, [record], REVISION)
    assert result["observed_rows"] == {"action.simulate": "PASS"}
    assert result["missing_rows"] == ["action.visualize"]


def test_stale_or_dirty_behavior_report_is_ignored():
    stale_record = evidence(observation("action.simulate"), revision="stale" * 8)
    dirty_record = {
        "source": {"revision": REVISION, "dirty": True},
        "references": {"bionetgen": {"revision": UPSTREAM}},
        "results": [observation("action.visualize")],
    }
    result = coverage_report(ROWS, LOCK, [stale_record, dirty_record], REVISION)
    assert result["observed_rows"] == {}
    assert result["missing_rows"] == ["action.simulate", "action.visualize"]


def test_unmatched_source_reference_revision_is_ignored():
    mismatched_record = {
        "source": {"revision": REVISION, "dirty": False},
        "references": {"bionetgen": {"revision": "wrong" * 8}},
        "results": [observation("action.simulate")],
    }
    result = coverage_report(ROWS, LOCK, [mismatched_record], REVISION)
    assert result["observed_rows"] == {}
    assert result["missing_rows"] == ["action.simulate", "action.visualize"]

