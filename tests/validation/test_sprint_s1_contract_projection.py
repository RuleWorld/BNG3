"""Focused S1 checks for live-contract mapping and consumer evidence."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.validation import issue_queue


def test_live_body_digest_scopes_each_obligation_without_relabeling_history():
    issue = {
        "number": 472,
        "title": "Documentation contract",
        "state": "OPEN",
        "body": "## Acceptance criteria\n- [ ] `release-docs-links`: links resolve.\n",
    }
    live_digest = hashlib.sha256(issue["body"].encode()).hexdigest()
    catalog = {
        "issues": [
            {
                "number": 472,
                "body_sha256": "a" * 64,
                "obligations": [
                    {
                        "id": "issue:472:historical-scope",
                        "criterion": "Earlier accepted scope",
                        "scope": "Earlier accepted scope",
                        "dependencies": [],
                        "boundaries": [],
                        "required_checks": [],
                        "test_references": [],
                        "completion_condition": "Historical check remains recorded.",
                        "decisions": [],
                        "unmapped_scope": [],
                    },
                    {
                        "id": "issue:472:acceptance:release-docs-links",
                        "criterion": "`release-docs-links`: links resolve.",
                        "scope": "`release-docs-links`: links resolve.",
                        "live_body_sha256": live_digest,
                        "dependencies": [],
                        "boundaries": [],
                        "required_checks": [
                            {
                                "id": "release-docs-links",
                                "evidence_kind": "supported-execution",
                                "expectation": "Links resolve.",
                                "selector": "tests/validation/release/cases/issue-472/docs_checks.py#release-docs-links",
                                "receipt_producer": ".github/workflows/issue-472-docs-acceptance.yml",
                            }
                        ],
                        "test_references": [
                            "tests/validation/release/cases/issue-472/docs_checks.py"
                        ],
                        "completion_condition": "Exact-revision result satisfies this obligation.",
                        "decisions": [],
                        "unmapped_scope": [],
                    },
                ],
            }
        ]
    }

    obligations = issue_queue.obligation_inventory([issue], catalog)

    historical = next(
        row for row in obligations if row["id"] == "issue:472:historical-scope"
    )
    current = next(
        row
        for row in obligations
        if row["id"] == "issue:472:acceptance:release-docs-links"
    )
    assert historical["scope_status"] == "STALE_SCOPE"
    assert current["scope_status"] == "CURRENT"
    assert not any(row["id"].startswith("issue:472:unmapped:") for row in obligations)


def test_live_check_attached_to_old_obligation_does_not_refresh_its_old_scope():
    issue = {
        "number": 472,
        "title": "Documentation contract",
        "state": "OPEN",
        "body": "## Acceptance criteria\n- [ ] `release-docs-links`: links resolve.\n",
    }
    live_digest = hashlib.sha256(issue["body"].encode()).hexdigest()
    historical = {
        "id": "issue:472:historical-scope",
        "criterion": "Earlier accepted scope",
        "scope": "Earlier accepted scope",
        "dependencies": [],
        "boundaries": [],
        "required_checks": [
            {
                "id": "release-docs-links",
                "evidence_kind": "supported-execution",
                "expectation": "Links resolve.",
                "identity_requirements": ["source.revision"],
                "selector": "python tests/validation/release/cases/issue-472/docs_checks.py#release-docs-links",
                "selector_status": "COLLECTED",
                "receipt_producer": ".github/workflows/issue-472-docs-acceptance.yml",
                "receipt_producer_status": "MISSING_CONSUMER",
                "missing_evidence": ["No issue_queue-compatible consumer receipt."],
            }
        ],
        "live_acceptance_criteria": [
            {
                "id": "issue:472:acceptance:1",
                "check_id": "release-docs-links",
                "text": "`release-docs-links`: links resolve.",
                "live_body_sha256": live_digest,
            }
        ],
        "test_references": [],
        "completion_condition": "Historical scope remains under review.",
        "decisions": [],
        "unmapped_scope": [],
    }
    catalog = {
        "issues": [
            {"number": 472, "body_sha256": "a" * 64, "obligations": [historical]}
        ]
    }

    obligations = issue_queue.obligation_inventory([issue], catalog)

    old = next(row for row in obligations if row["id"] == "issue:472:historical-scope")
    live = next(
        row
        for row in obligations
        if row["id"] == "issue:472:live-acceptance:release-docs-links"
    )
    assert old["scope_status"] == "STALE_SCOPE"
    assert live["scope_status"] == "CURRENT"
    assert live["criterion"] == "`release-docs-links`: links resolve."


def test_acceptance_parser_keeps_transferred_checks_after_bold_labels():
    issue = {
        "number": 157,
        "body": (
            "## Acceptance criteria\n"
            "- [ ] `release-events-roots`: roots match.\n"
            "**Inventory rows:**\n"
            "- [ ] `release-capability-coverage-158`: transferred rows execute.\n"
            "## Dependencies\n"
            "#140\n"
        ),
    }

    criteria = issue_queue.acceptance_criteria(issue)

    assert [row["text"].split("`", 2)[1] for row in criteria] == [
        "release-events-roots",
        "release-capability-coverage-158",
    ]


def test_producer_artifact_without_required_consumer_result_stays_open():
    revision = "a" * 40
    obligations = [
        {
            "id": "issue:155:producer-consumer",
            "criterion": "A separate consumer consumes the exported artifact.",
            "scope": "A separate consumer consumes the exported artifact.",
            "dependencies": [],
            "boundaries": ["producer artifact", "consumer execution"],
            "required_checks": [
                {
                    "id": "producer:artifact",
                    "evidence_kind": "supported-execution",
                    "expectation": "Producer emits an artifact.",
                    "identity_requirements": [],
                },
                {
                    "id": "consumer:artifact",
                    "evidence_kind": "supported-execution",
                    "expectation": "Independent consumer consumes the artifact.",
                    "identity_requirements": [],
                },
            ],
            "test_references": [],
            "completion_condition": "Both exact checks pass.",
            "decisions": [],
            "unmapped_scope": [],
        }
    ]
    reports = [
        {
            "source": {"revision": revision, "dirty": False},
            "results": [
                {
                    "id": "producer:artifact",
                    "status": "PASS",
                    "supported_execution": True,
                    "evidence_kind": "supported-execution",
                }
            ],
        }
    ]

    result = issue_queue.assess_obligations(obligations, reports, revision)

    assessed = result["obligations"][0]
    assert assessed["status"] == "NOT_TESTED"
    assert {row["id"]: row["status"] for row in assessed["checks"]} == {
        "producer:artifact": "PASS",
        "consumer:artifact": "NOT_TESTED",
    }


def test_catalog_maps_new_issue_checks_and_keeps_missing_selectors_explicit():
    root = Path(__file__).resolve().parents[2]
    catalog = json.loads((root / "provenance/issue-obligations.json").read_text())
    by_number = {row["number"]: row for row in catalog["issues"]}
    expected = {
        471: {
            "release-oracle-independence",
            "release-oracle-tamper",
            "release-ci-topology",
        },
        472: {"release-docs-links", "release-docs-decisions"},
        473: {"release-jax-ode", "release-jax-ssa", "release-jax-install"},
        474: {
            "release-metal-device",
            "release-metal-performance",
            "release-cuda-device",
            "release-cuda-performance",
            "release-nf-gpu",
            "release-capability-coverage-474",
        },
        475: {"release-delay-ode", "release-delay-ssa", "release-delay-formats"},
    }
    for number, identities in expected.items():
        rows = [
            obligation
            for obligation in by_number[number]["obligations"]
            if obligation.get("live_body_sha256")
        ]
        checks = [check for row in rows for check in row["required_checks"]]
        assert {check["id"] for check in checks} == identities
        assert all(check.get("selector_status") for check in checks)
        assert all(check.get("receipt_producer_status") for check in checks)
        assert all(row.get("live_body_sha256") for row in rows)
        assert all(row.get("capability_rows") for row in rows)
        assert all(row.get("consumer_requirements") for row in rows)
    assert "bngir.v01" in " ".join(
        by_number[475]["obligations"][-1]["missing_row_mapping"]
    )


def test_uncollected_selector_cannot_be_promoted_by_a_pass_receipt():
    revision = "a" * 40
    obligations = [
        {
            "id": "issue:473:acceptance:release-jax-ssa",
            "criterion": "The required JAX SSA check.",
            "scope": "The required JAX SSA check.",
            "dependencies": [],
            "boundaries": [],
            "required_checks": [
                {
                    "id": "release-jax-ssa",
                    "evidence_kind": "supported-execution",
                    "expectation": "Independent distribution comparison.",
                    "selector_status": "MISSING_SELECTOR",
                    "receipt_producer_status": "MISSING_PRODUCER",
                }
            ],
            "test_references": [],
            "completion_condition": "Exact-revision result satisfies this obligation.",
            "decisions": [],
            "unmapped_scope": [],
        }
    ]
    report = {
        "source": {"revision": revision, "dirty": False},
        "results": [
            {
                "id": "release-jax-ssa",
                "status": "PASS",
                "supported_execution": True,
                "evidence_kind": "supported-execution",
            }
        ],
    }

    result = issue_queue.assess_obligations(obligations, [report], revision)

    assert result["obligations"][0]["status"] == "EVIDENCE_GAP"
    assert "selector:MISSING_SELECTOR" in result["obligations"][0]["missing_evidence"]
    assert (
        "receipt_producer:MISSING_PRODUCER"
        in result["obligations"][0]["missing_evidence"]
    )


def test_collected_selector_claim_requires_a_selector_value():
    obligation = {
        "id": "issue:472:acceptance:release-docs-links",
        "criterion": "The required docs check.",
        "scope": "The required docs check.",
        "dependencies": [],
        "boundaries": [],
        "required_checks": [
            {
                "id": "release-docs-links",
                "evidence_kind": "supported-execution",
                "expectation": "Resolve links.",
                "selector_status": "COLLECTED",
            }
        ],
        "test_references": [],
        "completion_condition": "Exact-revision result satisfies this obligation.",
        "decisions": [],
        "unmapped_scope": [],
    }

    with pytest.raises(ValueError, match="needs an executable selector"):
        issue_queue.assess_obligations([obligation], [], "a" * 40)


def _issue142_receipt(revision="a" * 40):
    return {
        "schema_version": 1,
        "acceptance_check": "release-obligation-142",
        "source_revision": revision,
        "source_dirty": False,
        "checks": {
            "release-graph-identity": {
                "status": "PASS",
                "independent_isomorphism_oracle_sha256": "1" * 64,
                "subject_sha256": "2" * 64,
                "report_sha256": "3" * 64,
                "case_count": 9,
                "exhaustive_case_count": 116,
            },
            "release-graph-observables": {
                "status": "PASS",
                "bng2_revision": "4" * 40,
                "bng2_script_sha256": "5" * 64,
                "nfsim_revision": "6" * 40,
                "nfsim_binary_sha256": "7" * 64,
                "subject_sha256": "8" * 64,
                "report_sha256": "9" * 64,
                "run_count": 200,
                "dkw_alpha": 0.005,
            },
            "release-obligation-142": {"status": "PASS"},
        },
    }


def _issue142_reports(tmp_path, receipt=None, *, artifact_run_id=None):
    import copy

    import hashlib

    import json

    tmp_path.mkdir(parents=True, exist_ok=True)
    receipt = copy.deepcopy(receipt or _issue142_receipt())
    revision = receipt["source_revision"]
    catalog = json.loads(
        (issue_queue.ROOT / "provenance/issue-obligations.json").read_text()
    )
    from tests.validation.graph_identity_contract import CASES, CHECKS

    identity_ids = sorted(
        f"graph-identity-contract:{case['id']}:{check}"
        for case in CASES
        for check in CHECKS
    )
    identity_report = {
        "acceptance_check": "release-graph-identity",
        "source_revision": revision,
        "source_dirty": False,
        "independent_isomorphism_oracle_sha256": receipt["checks"][
            "release-graph-identity"
        ]["independent_isomorphism_oracle_sha256"],
        "subject_sha256": receipt["checks"]["release-graph-identity"]["subject_sha256"],
        "case_count": 9,
        "exhaustive_case_count": 116,
        "results": [
            {
                "id": check_id,
                "check": check_id.rsplit(":", 1)[-1],
                "status": "PASS",
                "evidence_kind": "supported-execution",
                "detail": "bounded independent identity fixture",
            }
            for check_id in identity_ids
        ],
    }
    observables_source = receipt["checks"]["release-graph-observables"]
    observables_report = {
        "acceptance_check": "release-graph-observables",
        "source_revision": revision,
        "source_dirty": False,
        "bng2_revision": observables_source["bng2_revision"],
        "bng2_script_sha256": observables_source["bng2_script_sha256"],
        "nfsim_revision": observables_source["nfsim_revision"],
        "nfsim_binary_sha256": observables_source["nfsim_binary_sha256"],
        "model_source_sha256": observables_source["subject_sha256"],
        "run_count": 200,
        "dkw_alpha": 0.005,
    }
    identity_path = tmp_path / "identity-report.json"
    observables_path = tmp_path / "observables-report.json"
    identity_path.write_text(json.dumps(identity_report, indent=2) + "\n")
    observables_path.write_text(json.dumps(observables_report, indent=2) + "\n")
    receipt["checks"]["release-graph-identity"]["report_sha256"] = hashlib.sha256(
        identity_path.read_bytes()
    ).hexdigest()
    receipt["checks"]["release-graph-observables"]["report_sha256"] = hashlib.sha256(
        observables_path.read_bytes()
    ).hexdigest()
    reports = issue_queue.issue142_receipt_reports(
        receipt,
        identity_path,
        observables_path,
        revision,
        artifact_run_id=artifact_run_id,
    )
    return receipt, reports, identity_path, observables_path


def test_issue142_receipt_projects_named_consumed_results_with_pins(tmp_path):
    _, reports, _, _ = _issue142_reports(tmp_path)
    identity, observables, receipt = reports
    rows = {
        row["id"]: row
        for report in reports
        for row in report["results"]
        if row["id"] in issue_queue.ISSUE_142_CHECKS
    }
    catalog_component_ids = {
        row["id"] for row in identity["results"] if row["id"].startswith("graph-")
    }
    expected_catalog_component_ids = {
        check["id"]
        for issue in json.loads(
            (issue_queue.ROOT / "provenance/issue-obligations.json").read_text()
        )["issues"]
        if issue["number"] == 142
        for obligation in issue["obligations"]
        for check in obligation["required_checks"]
        if check["id"].startswith("graph-identity-contract:")
    }
    assert len(catalog_component_ids) == 36
    assert expected_catalog_component_ids <= catalog_component_ids
    assert set(rows) == {
        "release-graph-identity",
        "release-graph-observables",
        "release-obligation-142",
    }
    assert rows["release-graph-identity"]["supported_execution"] is True
    assert rows["release-graph-observables"]["supported_execution"] is True
    assert rows["release-obligation-142"]["evidence_kind"] == "disposition"
    assert any(
        row["id"] == "qualification:issue:142:closure-record"
        and row["evidence_kind"] == "disposition"
        for row in receipt["results"]
    )
    assert observables["references"]["bionetgen"]["revision"] == "4" * 40
    assert observables["references"]["nfsim"]["sha256"] == "7" * 64
    assert receipt["checks"]["release-obligation-142"]["status"] == "PASS"


def test_issue142_receipt_retains_named_run_artifact_replay_references(tmp_path):
    import hashlib

    _, reports, identity_path, observables_path = _issue142_reports(
        tmp_path, artifact_run_id="41430154858"
    )
    report = reports[-1]

    assert report["replay_references"] == {
        "workflow_run_id": "41430154858",
        "identity": {
            "artifact_name": "issue142-release-graph-identity-41430154858",
            "file": "identity-report.json",
            "sha256": hashlib.sha256(identity_path.read_bytes()).hexdigest(),
        },
        "observables": {
            "artifact_name": "issue142-release-graph-observables-41430154858",
            "file": "observables-report.json",
            "sha256": hashlib.sha256(observables_path.read_bytes()).hexdigest(),
        },
    }


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda r: r.update(source_revision="b" * 40), "stale"),
        (lambda r: r.update(source_dirty=True), "clean"),
        (lambda r: r["checks"].pop("release-graph-observables"), "missing"),
        (
            lambda r: r["checks"]["release-graph-identity"].update(status="SKIP"),
            "did not pass",
        ),
        (
            lambda r: r["checks"]["release-graph-identity"].update(
                independent_isomorphism_oracle_sha256="not-a-hash"
            ),
            "identity",
        ),
    ],
)
def test_issue142_receipt_rejects_stale_dirty_missing_skipped_or_bad_identity(
    tmp_path, change, message
):
    receipt, _, identity_path, observables_path = _issue142_reports(tmp_path)
    change(receipt)

    with pytest.raises(ValueError, match=message):
        issue_queue.issue142_receipt_reports(
            receipt, identity_path, observables_path, "a" * 40
        )


def test_issue142_missing_consumer_result_does_not_demonstrate_live_contract(tmp_path):
    receipt, _, identity_path, observables_path = _issue142_reports(tmp_path)
    receipt["checks"].pop("release-obligation-142")
    with pytest.raises(ValueError, match="missing"):
        issue_queue.issue142_receipt_reports(
            receipt, identity_path, observables_path, "a" * 40
        )


def test_issue142_conflicting_exact_receipts_do_not_demonstrate_live_contract(tmp_path):
    _, first, _, _ = _issue142_reports(tmp_path / "first")
    # The receipt hashes must match each exact raw report; the differing
    # component detail therefore represents a conflicting producer result.
    _, second, _, _ = _issue142_reports(tmp_path / "second")
    second_identity = second[0]
    component = next(
        row
        for row in second_identity["results"]
        if row["id"]
        == "graph-identity-contract:symmetric-ring-3:network-canonical-label"
    )
    component["detail"] = "a conflicting producer result"
    obligations = [
        {
            "id": "issue:142:live-acceptance:release-graph-identity",
            "issue": 142,
            "criterion": "identity check",
            "scope": "identity check",
            "dependencies": [],
            "boundaries": [],
            "required_checks": [
                {
                    "id": "graph-identity-contract:symmetric-ring-3:network-canonical-label",
                    "evidence_kind": "supported-execution",
                    "expectation": "independent graph identity",
                    "identity_requirements": ["source.revision", "subject.sha256"],
                }
            ],
            "test_references": [],
            "completion_condition": "Exact revision passes.",
            "decisions": [],
            "unmapped_scope": [],
            "scope_status": "CURRENT",
        }
    ]

    result = issue_queue.assess_obligations(
        [obligations[0]], [first[0], second_identity], "a" * 40
    )

    assert result["obligations"][0]["status"] == "CONFLICT"


def test_issue142_absent_receipt_leaves_live_contract_not_tested():
    obligations = [
        {
            "id": "issue:142:live-acceptance:release-graph-identity",
            "issue": 142,
            "criterion": "identity check",
            "scope": "identity check",
            "dependencies": [],
            "boundaries": [],
            "required_checks": [
                {
                    "id": "release-graph-identity",
                    "evidence_kind": "supported-execution",
                    "expectation": "independent graph identity",
                    "identity_requirements": ["source.revision"],
                    "selector_status": "COLLECTED",
                    "selector": "tests/validation/test_graph_identity_contract.py",
                    "receipt_producer_status": "CONSUMER_READY",
                    "receipt_producer": ".github/workflows/parity.yml#release-obligation-142",
                }
            ],
            "test_references": [],
            "completion_condition": "Exact revision passes.",
            "decisions": [],
            "unmapped_scope": [],
            "scope_status": "CURRENT",
        }
    ]

    result = issue_queue.assess_obligations(obligations, [], "a" * 40)

    assert result["obligations"][0]["status"] == "NOT_TESTED"


def test_issue142_live_criteria_bind_to_historical_checks_without_relabeling_scope():
    import copy
    import hashlib
    import json

    catalog = json.loads(
        (issue_queue.ROOT / "provenance/issue-obligations.json").read_text()
    )
    issue = next(row for row in catalog["issues"] if row["number"] == 142)
    live = [row for row in issue["obligations"] if row.get("live_acceptance_criteria")]
    assert {
        criterion["check_id"]
        for row in live
        for criterion in row["live_acceptance_criteria"]
    } == {
        "release-graph-identity",
        "release-graph-observables",
        "release-obligation-142",
    }
    current_texts = {
        criterion["text"]
        for row in live
        for criterion in row["live_acceptance_criteria"]
    }
    assert all(row["criterion"] not in current_texts for row in live)
    assert all(row.get("decisions") == [] for row in live)
    issue_snapshot = {
        "number": 142,
        "state": "OPEN",
        "body": "## Acceptance criteria\n"
        + "\n".join(f"- [ ] {text}" for text in current_texts)
        + "\n",
    }
    fixture_catalog = copy.deepcopy(catalog)
    fixture_issue = next(
        row for row in fixture_catalog["issues"] if row["number"] == 142
    )
    fixture_digest = hashlib.sha256(issue_snapshot["body"].encode()).hexdigest()
    for obligation in fixture_issue["obligations"]:
        for mapping in obligation.get("live_acceptance_criteria", []):
            mapping["live_body_sha256"] = fixture_digest
    projected = issue_queue.obligation_inventory([issue_snapshot], fixture_catalog)
    current = [row for row in projected if row.get("scope_status") == "CURRENT"]
    assert {row["required_checks"][0]["id"] for row in current} == {
        "release-graph-identity",
        "release-graph-observables",
        "release-obligation-142",
    }
    assert all(row.get("decisions") == [] for row in current)


def test_issue142_criteria_show_consumed_status_but_do_not_enable_closure():
    issue = {
        "number": 142,
        "title": "Graph identity",
        "state": "OPEN",
        "body": (
            "## Acceptance criteria\n"
            "- [ ] `release-graph-identity`: independent check.\n"
            "- [ ] `release-graph-observables`: bounded check.\n"
            "- [ ] `release-obligation-142`: consume both.\n"
        ),
    }
    rows = [
        dict(
            id=check_id,
            status="PASS",
            check=check_id,
            supported_execution=True,
            evidence_kind=(
                "disposition"
                if check_id == "release-obligation-142"
                else "supported-execution"
            ),
            related_issues=[142],
        )
        for check_id in (
            "release-graph-identity",
            "release-graph-observables",
            "release-obligation-142",
        )
    ]
    obligations = [
        {
            "id": f"issue:142:live-acceptance:{check_id}",
            "issue": 142,
            "criterion": criterion,
            "live_acceptance_criteria": [{"text": criterion, "check_id": check_id}],
            "scope_status": "CURRENT",
            "status": "DEMONSTRATED",
            "checks": [{"id": check_id, "status": "PASS", "executed": True}],
            "decisions": [],
            "unmapped_scope": [],
            "boundaries": [],
        }
        for criterion, check_id in zip(
            issue_queue.acceptance_criteria(issue),
            (
                "release-graph-identity",
                "release-graph-observables",
                "release-obligation-142",
            ),
        )
        for criterion in [criterion["text"]]
    ]
    queue = issue_queue.build_queue(
        [issue],
        [{"source": {"revision": "a" * 40, "dirty": False}, "results": rows}],
        "a" * 40,
    )
    dashboard = issue_queue.acceptance_dashboard(
        queue, {"obligations": obligations}, []
    )

    assert [row["evidence_status"] for row in dashboard[0]["acceptance_criteria"]] == [
        "PASS",
        "PASS",
        "PASS",
    ]
    assert dashboard[0]["closure_eligible"] is False


def test_issue142_real_obligation_projection_consumes_receipt_without_closing_issue(
    tmp_path,
):
    import copy
    import hashlib
    import json

    catalog = json.loads(
        (issue_queue.ROOT / "provenance/issue-obligations.json").read_text()
    )
    fixture = copy.deepcopy(catalog)
    issue_definition = next(row for row in fixture["issues"] if row["number"] == 142)
    mappings = [
        mapping
        for row in issue_definition["obligations"]
        for mapping in row.get("live_acceptance_criteria", [])
    ]
    body = (
        "## Acceptance criteria\n"
        + "\n".join(f"- [ ] {mapping['text']}" for mapping in mappings)
        + "\n"
    )
    digest = hashlib.sha256(body.encode()).hexdigest()
    for row in issue_definition["obligations"]:
        for mapping in row.get("live_acceptance_criteria", []):
            mapping["live_body_sha256"] = digest
    issue = {"number": 142, "title": "Graph identity", "state": "OPEN", "body": body}
    revision = "a" * 40
    _, reports, _, _ = _issue142_reports(tmp_path, _issue142_receipt(revision))
    obligations = issue_queue.obligation_inventory([issue], fixture)
    assessment = issue_queue.assess_obligations(obligations, reports, revision)
    queue = issue_queue.build_queue([issue], reports, revision)
    dashboard = issue_queue.acceptance_dashboard(queue, assessment, [])

    live = [
        row for row in assessment["obligations"] if row.get("scope_status") == "CURRENT"
    ]
    assert {row["id"] for row in live} == {
        "issue:142:live-acceptance:release-graph-identity",
        "issue:142:live-acceptance:release-graph-observables",
        "issue:142:live-acceptance:release-obligation-142",
    }
    assert all(row["status"] == "DEMONSTRATED" for row in live)
    current_issue = dashboard[0]
    assert [row["evidence_status"] for row in current_issue["acceptance_criteria"]] == [
        "PASS",
        "PASS",
        "PASS",
    ]
    assert current_issue["closure_eligible"] is False
    assert current_issue["remaining_obligations"]


def test_stale_scope_reconciliation_is_not_reported_as_a_new_maintainer_decision():
    issue = {"number": 142, "title": "Graph identity", "state": "OPEN", "body": ""}
    obligation = {
        "id": "issue:142:historical-scope",
        "issue": 142,
        "criterion": "Earlier graph scope",
        "scope": "Earlier graph scope",
        "scope_status": "STALE_SCOPE",
        "required_checks": [],
        "checks": [],
        "decisions": [],
        "unmapped_scope": ["Broader complex family is not in the bounded receipt."],
        "boundaries": [],
        "status": "DECISION_REQUIRED",
    }
    queue = issue_queue.build_queue([issue], [], "a" * 40)

    dashboard = issue_queue.acceptance_dashboard(
        queue, {"obligations": [obligation]}, []
    )

    assert dashboard[0]["maintainer_decision_required"] is False
    assert dashboard[0]["decisions_required"] == []
    assert dashboard[0]["scope_reconciliation_required"] == [
        {
            "obligation": "issue:142:historical-scope",
            "scope_status": "STALE_SCOPE",
            "unmapped_scope": ["Broader complex family is not in the bounded receipt."],
        }
    ]


def test_issue_queue_downloads_and_consumes_same_run_issue142_receipt():
    import yaml

    workflow = yaml.safe_load(
        (issue_queue.ROOT / ".github/workflows/parity.yml").read_text()
    )
    job = workflow["jobs"]["integrated-semantic-validation"]
    assert "release-obligation-142" in job["needs"]
    steps = job["steps"]
    download = next(
        step
        for step in steps
        if step.get("name") == "Download Issue 142 receipt for issue queue"
    )
    assert download["uses"] == "actions/download-artifact@v4"
    assert (
        download["with"]["name"]
        == "issue142-release-obligation-142-${{ github.run_id }}"
    )
    for name, artifact in (
        (
            "Download Issue 142 identity components for issue queue",
            "issue142-release-graph-identity-${{ github.run_id }}",
        ),
        (
            "Download Issue 142 observable replay for issue queue",
            "issue142-release-graph-observables-${{ github.run_id }}",
        ),
    ):
        child_download = next(step for step in steps if step.get("name") == name)
        assert child_download["uses"] == "actions/download-artifact@v4"
        assert child_download["with"]["name"] == artifact
    queue_step = next(
        step
        for step in steps
        if step.get("name")
        == "Build exact-revision issue and provenance evidence queue"
    )
    assert "--issue142-release-record" in queue_step["run"]
    assert "--issue142-identity-report" in queue_step["run"]
    assert "--issue142-observables-report" in queue_step["run"]
