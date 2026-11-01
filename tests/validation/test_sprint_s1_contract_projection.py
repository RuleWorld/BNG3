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
        474: {"release-cuda-device", "release-cuda-performance"},
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
