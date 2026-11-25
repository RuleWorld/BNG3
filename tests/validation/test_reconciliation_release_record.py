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


def test_complete_inventory_with_a_semantic_failure_blocks_release():
    from scripts.ci.record_reconciliation_release import canonical_gaps

    reports = [
        evidence(
            observation("action.simulate"),
            observation("action.visualize", status="FAIL", supported_execution=False),
        )
    ]
    coverage = coverage_report(ROWS, LOCK, reports, REVISION)
    assert coverage["missing_rows"] == []
    assert canonical_gaps(coverage) == ["Canonical behavior failed: action.visualize."]


def test_issue471_bridge_consumes_valid_receipts_and_fails_closed(tmp_path):
    import json
    from scripts.ci.record_reconciliation_release import issue471_behavior_reports

    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    valid_receipt = {
        "schema_version": 2,
        "kind": "release-oracle-consumer-receipt",
        "capability_id": "action.simulate",
        "check_id": "release-capability[action.simulate]",
        "source_revision": REVISION,
        "product_revision": REVISION,
        "oracle": {
            "source_id": "bng2",
            "revision": UPSTREAM,
            "expected_origin": "external-source",
        },
    }
    (receipts_dir / "action.simulate.json").write_text(
        json.dumps(valid_receipt), encoding="utf-8"
    )
    stale_receipt = {**valid_receipt, "capability_id": "action.visualize"}
    stale_receipt["check_id"] = "release-capability[action.visualize]"
    stale_receipt["source_revision"] = "c" * 40
    (receipts_dir / "action.visualize.json").write_text(
        json.dumps(stale_receipt), encoding="utf-8"
    )

    oracle_report = {
        "check_id": "release-oracle-independence",
        "revision": REVISION,
        "evidence_scope": "ARTIFACT_CHECKS_ENABLED",
        "owned_comparisons": [
            {
                "capability_id": "action.simulate",
                "id": "release-oracle-net-canonical-v1",
                "receipt_valid": True,
                "consumer_equals_oracle": True,
            },
            {
                "capability_id": "action.visualize",
                "id": "release-oracle-net-canonical-v1",
                "receipt_valid": True,
                "consumer_equals_oracle": True,
            },
        ],
    }
    bridged = issue471_behavior_reports(oracle_report, receipts_dir, REVISION, LOCK)
    cov = coverage_report(ROWS, LOCK, bridged, REVISION)
    assert cov["observed_rows"] == {"action.simulate": "PASS"}
    assert cov["missing_rows"] == ["action.visualize"]

    # Negative controls: declaration-only scope, receipt_valid=False, wrong oracle revision.
    decl_only = {**oracle_report, "evidence_scope": "DECLARATION_ONLY"}
    assert issue471_behavior_reports(decl_only, receipts_dir, REVISION, LOCK) == []

    invalid_comp = {
        **oracle_report,
        "owned_comparisons": [
            {**oracle_report["owned_comparisons"][0], "receipt_valid": False}
        ],
    }
    assert issue471_behavior_reports(invalid_comp, receipts_dir, REVISION, LOCK) == []

    wrong_oracle = json.loads(json.dumps(valid_receipt))
    wrong_oracle["oracle"]["revision"] = "d" * 40
    (receipts_dir / "action.simulate.json").write_text(
        json.dumps(wrong_oracle), encoding="utf-8"
    )
    assert issue471_behavior_reports(oracle_report, receipts_dir, REVISION, LOCK) == []
