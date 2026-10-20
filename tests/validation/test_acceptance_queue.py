"""Acceptance evidence must match independently declared obligations."""

import json
from pathlib import Path

from tests.validation import issue_queue as q

REV = "a" * 40


def obligation(**changes):
    value = dict(
        id="issue:141:reuse",
        criterion="Reuse",
        scope="one route",
        dependencies=[],
        boundaries=["producer", "consumer"],
        required_checks=[
            dict(
                id="consumer:values",
                evidence_kind="supported-execution",
                expectation="fresh agreement",
                identity_requirements=[],
            )
        ],
        test_references=["tests/validation/test_issue_queue.py"],
        completion_condition="all checks",
        decisions=[],
        unmapped_scope=[],
    )
    return dict(value, **changes)


def assess(rows=(), **changes):
    reports = [dict(source=dict(revision=REV, dirty=False), results=list(rows))]
    return q.assess_obligations([obligation(**changes)], reports, REV)


def test_related_pass_does_not_fill_absent_required_consumer():
    result = assess([dict(id="producer", status="PASS", related_issues=[141])])
    assert result["obligations"][0]["status"] == "NOT_TESTED"
    assert result["obligations"][0]["checks"][0]["status"] == "NOT_TESTED"


def test_diagnostic_pass_cannot_establish_supported_execution():
    result = assess(
        [
            dict(
                id="consumer:values",
                status="PASS",
                supported_execution=False,
                evidence_kind="diagnostic-only",
            )
        ]
    )
    assert result["obligations"][0]["status"] == "EVIDENCE_GAP"


def test_exact_pass_and_missing_dependency():
    row = dict(
        id="consumer:values",
        status="PASS",
        supported_execution=True,
        evidence_kind="supported-execution",
    )
    assert assess([row])["obligations"][0]["status"] == "DEMONSTRATED"
    assert (
        assess([row], dependencies=["absent"])["obligations"][0]["status"] == "BLOCKED"
    )


def test_stale_conflicts_and_unsupported_stay_separate():
    base = dict(
        source=dict(revision=REV, dirty=False),
        results=[
            dict(
                id="consumer:values",
                status="PASS",
                supported_execution=True,
                evidence_kind="supported-execution",
            )
        ],
    )
    stale = dict(base, source=dict(revision="b" * 40, dirty=False))
    conflict = dict(base, results=[dict(id="consumer:values", status="FAIL")])
    result = q.assess_obligations([obligation()], [base, stale, conflict], REV)
    assert {r["status"] for r in result["evidence_audit"]} == {"STALE", "CONFLICT"}
    assert result["obligations"][0]["status"] == "CONFLICT"
    assert (
        assess([dict(id="consumer:values", status="UNSUPPORTED")])["obligations"][0][
            "status"
        ]
        == "UNSUPPORTED"
    )


def test_missing_oracle_identity_cannot_demonstrate_check():
    required = [
        dict(
            id="consumer:values",
            evidence_kind="supported-execution",
            expectation="oracle agreement",
            identity_requirements=["references.nfsim.revision"],
        )
    ]
    assert (
        assess(
            [
                dict(
                    id="consumer:values",
                    status="PASS",
                    supported_execution=True,
                    evidence_kind="supported-execution",
                )
            ],
            required_checks=required,
        )["obligations"][0]["status"]
        == "EVIDENCE_GAP"
    )


def test_disposition_is_human_review_not_an_unexecuted_ci_check():
    review = obligation(
        id="issue:179:source-policy",
        criterion="Approve source status and record the supported migration policy.",
        scope="source approval and public migration default",
        required_checks=[
            dict(
                id="qualification:issue:179:source-policy",
                evidence_kind="disposition",
                expectation="Record the maintainer-approved source status.",
                identity_requirements=["source.revision"],
            )
        ],
        decisions=["Maintainer approval is required."],
    )
    result = q.assess_obligations([review], [], REV)["obligations"][0]

    assert review["criterion"] == result["criterion"]
    assert result["status"] == "DECISION_REQUIRED"
    assert result["technical_status"] == "NOT_APPLICABLE"
    assert result["checks"] == []
    assert result["manual_requirements"] == [
        dict(
            id="issue:179:source-policy:manual:1",
            kind="disposition",
            criterion=review["criterion"],
            text="Record the maintainer-approved source status.",
        ),
        dict(
            id="issue:179:source-policy:manual:2",
            kind="human-decision",
            criterion=review["criterion"],
            text="Maintainer approval is required.",
        ),
    ]
    assert result["untested_routes"] == []


def test_issue_185_reviewer_assignment_stays_out_of_behavioral_repair_queue():
    catalog = json.loads(
        (Path(__file__).parents[2] / "provenance/issue-obligations.json").read_text()
    )
    obligations = next(
        issue["obligations"] for issue in catalog["issues"] if issue["number"] == 185
    )

    result = q.assess_obligations(
        obligations,
        [dict(source=dict(revision=REV, dirty=False), results=[])],
        REV,
    )

    assert all(not row["checks"] for row in result["obligations"])
    assert all(row["status"] == "DECISION_REQUIRED" for row in result["obligations"])
    assert all(
        any(req["kind"] == "disposition" for req in row["manual_requirements"])
        for row in result["obligations"]
    )
    assert any(
        "which named people or roles" in decision
        for row in result["obligations"]
        for decision in row["decisions"]
    )


def test_behavioral_check_remains_executable_beside_a_human_decision():
    mixed = obligation(
        required_checks=[
            dict(
                id="consumer:values",
                evidence_kind="supported-execution",
                expectation="Compare the trajectory with the independent oracle.",
                identity_requirements=[],
            ),
            dict(
                id="qualification:issue:141:scope-decision",
                evidence_kind="disposition",
                expectation="Record the approved solver scope.",
                identity_requirements=["source.revision"],
            ),
        ],
        decisions=["Maintainer decision on solver scope is required."],
    )
    row = dict(
        id="consumer:values",
        status="PASS",
        supported_execution=True,
        evidence_kind="supported-execution",
    )
    report = dict(source=dict(revision=REV, dirty=False), results=[row])

    result = q.assess_obligations([mixed], [report], REV)["obligations"][0]

    assert result["technical_status"] == "DEMONSTRATED"
    assert result["status"] == "DECISION_REQUIRED"
    assert [check["id"] for check in result["checks"]] == ["consumer:values"]
    assert result["decision_status"] == "REQUIRED"
    assert (
        result["manual_requirements"][0]["text"] == "Record the approved solver scope."
    )


def test_manual_requirements_are_isolated_per_obligation_in_both_orders():
    technical = obligation(id="issue:141:technical")
    governance = obligation(
        id="issue:141:governance",
        required_checks=[
            dict(
                id="qualification:scope-decision",
                evidence_kind="disposition",
                expectation="Record the scope decision.",
                identity_requirements=[],
            )
        ],
        decisions=["A maintainer must choose the supported scope."],
    )
    row = dict(
        id="consumer:values",
        status="PASS",
        supported_execution=True,
        evidence_kind="supported-execution",
    )
    report = dict(source=dict(revision=REV, dirty=False), results=[row])

    for rows in ([technical, governance], [governance, technical]):
        assessed = q.assess_obligations(rows, [report], REV)["obligations"]
        by_id = {item["id"]: item for item in assessed}
        assert by_id["issue:141:technical"]["status"] == "DEMONSTRATED"
        assert by_id["issue:141:technical"]["manual_requirements"] == []
        assert by_id["issue:141:governance"]["status"] == "DECISION_REQUIRED"
        assert by_id["issue:141:governance"]["technical_status"] == "NOT_APPLICABLE"
        assert all(
            item["id"].startswith("issue:141:governance:manual:")
            for item in by_id["issue:141:governance"]["manual_requirements"]
        )


def test_governance_does_not_hide_failures_or_enter_technical_campaign_queue():
    from pathlib import Path
    from tests.validation import reporting

    failing = obligation(
        id="issue:155:slice:rule-product-type-name-id-disagreement",
        required_checks=[
            dict(
                id="bngir-adversarial:rule-product-type-name-id-disagreement",
                evidence_kind="diagnostic-only",
                expectation="Refuse the malformed name/id cross-reference.",
                identity_requirements=[],
            ),
            dict(
                id="qualification:maintainer-disposition",
                evidence_kind="disposition",
                expectation="Record maintainer disposition.",
                identity_requirements=[],
            ),
        ],
        decisions=["Maintainer disposition is required."],
    )
    row = dict(
        id="bngir-adversarial:rule-product-type-name-id-disagreement",
        status="FAIL",
        supported_execution=False,
        evidence_kind="diagnostic-only",
    )
    report = dict(source=dict(revision=REV, dirty=False), results=[row])
    result = q.assess_obligations([failing], [report], REV)
    assessed = result["obligations"][0]
    assert assessed["status"] == "DECISION_REQUIRED"
    assert assessed["technical_status"] == "FAIL"
    assert q.select_campaign([assessed])[0]["id"] == "native-bngir-adversarial"

    task = reporting.investigation_tasks(
        dict(
            source=dict(revision=REV, dirty=False),
            subject=dict(sha256="c" * 64),
            references={},
            configuration={},
            results=[
                dict(row, stage="native-import", first_difference="type_id=1, type=A")
            ],
        ),
        Path("."),
        obligations=result,
    )[0]
    assert task["case_id"] == row["id"]
    assert task["observation"] == "type_id=1, type=A"
    assert task["affected_obligations"][0]["id"] == failing["id"]


def test_absent_generated_rule_product_check_stays_not_tested():
    row = obligation(
        id="issue:155:slice:rule-product-type-name-id-disagreement",
        required_checks=[
            dict(
                id="bngir-adversarial:rule-product-type-name-id-disagreement",
                evidence_kind="diagnostic-only",
                expectation="Refuse the malformed name/id cross-reference.",
                identity_requirements=[],
            ),
            dict(
                id="bngir-adversarial:compartment-parent-reference-out-of-range",
                evidence_kind="diagnostic-only",
                expectation="Refuse an unsupported compartment-parent reference.",
                identity_requirements=[],
            ),
        ],
    )
    report = dict(
        source=dict(revision=REV, dirty=False),
        results=[
            dict(
                id="bngir-adversarial:compartment-parent-reference-out-of-range",
                status="UNSUPPORTED",
                evidence_kind="diagnostic-only",
            )
        ],
    )
    assessed = q.assess_obligations([row], [report], REV)["obligations"][0]
    checks = {item["id"]: item for item in assessed["checks"]}
    assert (
        checks["bngir-adversarial:rule-product-type-name-id-disagreement"]["status"]
        == "NOT_TESTED"
    )
    assert (
        checks["bngir-adversarial:rule-product-type-name-id-disagreement"]["executed"]
        is False
    )
    assert (
        checks["bngir-adversarial:compartment-parent-reference-out-of-range"]["status"]
        == "UNSUPPORTED"
    )


def test_campaign_is_bounded_and_representative():
    obligations = [
        obligation(
            required_checks=[
                dict(
                    id="v1-n20-r0-a0:reuse:reset",
                    evidence_kind="supported-execution",
                    expectation="reset",
                    identity_requirements=[],
                )
            ]
        )
    ]
    result = q.select_campaign(obligations, max_families=1)
    assert len(result) == 1
    assert result[0]["obligation_ids"] == ["issue:141:reuse"]
    assert result[0]["authorization"] == "PLAN_ONLY"
    assert result[0]["complete_corpus_coverage"] is False


def test_scope_edits_and_new_issue_remain_visible():
    import hashlib

    issue = dict(number=141, body="**Acceptance criteria**\n- [ ] Reuse\n")
    catalog = dict(
        issues=[
            dict(
                number=141,
                body_sha256=hashlib.sha256(issue["body"].encode()).hexdigest(),
                obligations=[obligation()],
            )
        ]
    )
    assert q.obligation_inventory([issue], catalog)[0]["scope_status"] == "CURRENT"
    changed = dict(issue, body=issue["body"] + "- [ ] New scope\n")
    rows = q.obligation_inventory([changed], catalog)
    assert rows[0]["scope_status"] == "STALE_SCOPE"
    assert any(
        r["scope_status"] == "UNMAPPED" and r["criterion"] == "New scope" for r in rows
    )


def test_dashboard_ranks_named_failures_and_keeps_closure_disabled():
    issue = dict(number=141, state="OPEN", body="")
    row = dict(id="consumer:values", status="FAIL")
    assessment = assess([row])
    assessment["obligations"][0]["issue"] = 141
    queue = q.acceptance_dashboard(q.build_queue([issue], [], REV), assessment, [])
    assert queue[0]["ranking_basis"]["confirmed_failures"] == 1
    assert queue[0]["rank"] == 1
    assert queue[0]["closure_eligible"] is False


def test_shared_family_never_counts_unknown_required_check_as_covered():
    source = obligation(
        required_checks=[
            dict(id="qualification:unknown", evidence_kind="supported-execution")
        ]
    )
    assert q.select_campaign([source]) == []


def test_consumer_evidence_annotation_never_promotes_process_or_rejection():
    from tests.validation.integrated import annotate_acceptance_evidence

    rows = [
        dict(id="v1-n20-r0-a0:reuse:reset", check="reset", status="PASS"),
        dict(id="v1-n20-r0-a0:reuse", status="PASS"),
        dict(
            id="reject",
            check="refusal",
            status="PASS",
            supported_execution=False,
            evidence_kind="diagnostic-only",
        ),
    ]
    annotate_acceptance_evidence(rows)
    assert rows[0]["evidence_kind"] == "supported-execution"
    assert "evidence_kind" not in rows[1]
    assert rows[2]["evidence_kind"] == "diagnostic-only"


def test_unidentified_failure_is_observed_but_not_confirmed():
    required = [
        dict(
            id="consumer:values",
            evidence_kind="supported-execution",
            expectation="independent agreement",
            identity_requirements=["references.nfsim.revision"],
        )
    ]
    result = assess(
        [dict(id="consumer:values", status="FAIL")], required_checks=required
    )
    check = result["obligations"][0]["checks"][0]
    assert check["status"] == "EVIDENCE_GAP"
    assert check["observation"]["status"] == "FAIL"


def test_live_slice_runs_inventory_audit_selection_packets_and_dashboard(tmp_path):
    import json
    from tests.validation import reporting

    catalog = json.loads((q.ROOT / "provenance/issue-obligations.json").read_text())
    issues = [
        dict(
            number=i["number"],
            state="OPEN",
            body="**Acceptance criteria**\n"
            + "\n".join(
                "- [ ] " + text
                for text in dict.fromkeys(o["criterion"] for o in i["obligations"])
            ),
        )
        for i in catalog["issues"]
        if i["number"] in {141, 151, 155}
    ]
    # Fixture receipt has reviewed fixture body hashes; never reuse live evidence.
    import hashlib

    reviewed = dict(
        issues=[
            dict(
                i,
                body_sha256=hashlib.sha256(
                    next(
                        x["body"] for x in issues if x["number"] == i["number"]
                    ).encode()
                ).hexdigest(),
            )
            for i in catalog["issues"]
            if i["number"] in {141, 151, 155}
        ]
    )
    obligations = q.obligation_inventory(issues, reviewed)
    rows = []
    for o in obligations:
        if ":slice:" in o["id"]:
            c = o["required_checks"][0]
            rows.append(
                dict(
                    id=c["id"],
                    status="PASS",
                    stage="fixture",
                    check=c["id"],
                    supported_execution=c["evidence_kind"] != "diagnostic-only",
                    evidence_kind=c["evidence_kind"],
                )
            )
    rows = [
        r
        for r in rows
        if not r["id"].endswith("compartment-parent-reference-out-of-range")
    ]
    failure = next(r for r in rows if r["id"].endswith("reuse:reset"))
    failure["status"] = "FAIL"
    report = dict(
        subject=dict(binary="fixture", sha256="c" * 64),
        source=dict(revision=REV, dirty=False),
        references=dict(nfsim=dict(revision="b" * 40, sha256="d" * 64)),
        results=rows,
        configuration={},
        capabilities=[],
        replay_commands={
            failure["id"]: ["python", "-m", "tests.validation.integrated"]
        },
    )
    assessment = q.assess_obligations(obligations, [report], REV)
    campaigns = q.select_campaign(assessment["obligations"])
    dashboard = q.acceptance_dashboard(
        q.build_queue(issues, [report], REV), assessment, campaigns
    )
    assert {r["number"] for r in dashboard} == {141, 151, 155}
    assert dashboard[0]["number"] == 141
    assert all(r["remaining_obligations"] for r in dashboard)
    assert {f["id"] for f in campaigns} == {
        "generated-decay",
        "native-bngir-adversarial",
        "quantity-source-laws",
    }
    packets = reporting.investigation_tasks(report, tmp_path, obligations=assessment)
    assert packets[0]["affected_obligations"][0]["id"] == "issue:141:slice:reset"
    assert any(
        o["status"] == "DEMONSTRATED" and ":slice:" in o["id"]
        for o in assessment["obligations"]
    )
    assert all(
        o["status"] != "DEMONSTRATED"
        for o in assessment["obligations"]
        if ":slice:" not in o["id"]
    )
    # Required named checks live independently of any report leaf.
    absent = q.assess_obligations(obligations, [], REV)
    assert all(o["status"] != "DEMONSTRATED" for o in absent["obligations"])


def test_inventory_preserves_all_snapshot_issues_and_missing_scope():
    import json

    catalog = json.loads((q.ROOT / "provenance/issue-obligations.json").read_text())
    assert {i["number"] for i in catalog["issues"]} == set(
        catalog["snapshot"]["issue_numbers"]
    )
    assert {141, 151, 155} <= set(catalog["snapshot"]["issue_numbers"])
    all_obligations = [o for i in catalog["issues"] for o in i["obligations"]]
    assert len({o["id"] for o in all_obligations}) == len(all_obligations)
    missing = []
    for issue in catalog["issues"]:
        assert len(issue["body_sha256"]) == 64
        for obligation in issue["obligations"]:
            assert obligation["criterion"] and obligation["scope"]
            assert obligation["completion_condition"]
            for ref in obligation["test_references"]:
                assert (q.ROOT / ref.split("::")[0]).exists(), ref
            for check in obligation["required_checks"]:
                if check["id"].startswith("qualification:"):
                    assert obligation["unmapped_scope"]
                    missing.append(check["id"])
    assert missing
    assessment = q.assess_obligations(all_obligations, [], REV)
    assert not any(o["status"] == "DEMONSTRATED" for o in assessment["obligations"])


def test_missing_revision_is_unverifiable_and_never_a_pass():
    result = q.assess_obligations([obligation()], [dict(source=None, results=[])], REV)
    assert result["evidence_audit"][0]["status"] == "UNVERIFIABLE"
    assert result["obligations"][0]["status"] == "NOT_TESTED"


def test_packet_identity_contract_accepts_subject_and_rejects_stale_assessment():
    from tests.validation import reporting

    report = dict(source=dict(revision=REV, dirty=False), subject=dict(sha256="c" * 64))
    check = dict(
        id="consumer:values",
        status="FAIL",
        candidate_identity=report["source"],
        identity_requirements=["subject.sha256"],
    )
    o = obligation()
    o["required_checks"][0]["identity_requirements"] = ["subject.sha256"]
    o["checks"] = [check]
    row = dict(id="consumer:values", status="FAIL", stage="consumer")
    affected = reporting._affected_obligations(row, [o], report)
    assert affected[0]["missing_identities"] == []
    check["candidate_identity"] = dict(revision="b" * 40, dirty=False)
    affected = reporting._affected_obligations(row, [o], report)
    assert affected[0]["missing_identities"]


def test_known_finding_selects_family_without_claiming_obligation_coverage():
    rows = [
        dict(
            id="dimerization-v3-n20-r1-a0:nf-marginals:embedded.source-cdf",
            status="FAIL",
            related_issues=[151],
        )
    ]
    plans = q.select_campaign([obligation()], findings=rows, max_families=1)
    assert plans[0]["id"] == "generated-dimerization"
    assert plans[0]["obligation_ids"] == []
    assert plans[0]["known_finding_ids"] == [rows[0]["id"]]
    assert plans[0]["confirmed_failures"] == 0


def test_unexecuted_qualifications_cannot_claim_supported_execution():
    from tests.validation.integrated import annotate_acceptance_evidence

    rows = [
        dict(id="v1-n20-r0-a0:protocol:lifecycle-topology-unavailable", status=status)
        for status in ("UNSUPPORTED", "NOT_TESTED", "HARNESS_ERROR")
    ]
    annotate_acceptance_evidence(rows)
    assert all(row.get("supported_execution") is not True for row in rows)


def test_undeclared_finding_does_not_select_an_unexecutable_check():
    rows = [
        dict(
            id="dimerization-v3-n20-r1-a0:retired-check",
            status="FAIL",
            related_issues=[151],
        )
    ]
    assert q.select_campaign([obligation()], findings=rows, max_families=1) == []


def test_closed_and_unobserved_issues_retain_evidence_without_active_ranks():
    from tests.validation.ci_report import acceptance_markdown

    issues = [dict(number=141, state="OPEN"), dict(number=151, state="CLOSED")]
    rows = [dict(id="closed:failure", status="FAIL", related_issues=[151, 155])]
    queue = q.acceptance_dashboard(
        q.build_queue(
            issues, [dict(source=dict(revision=REV, dirty=False), results=rows)], REV
        ),
        dict(obligations=[], evidence_audit=[]),
        [],
    )
    assert [(r["number"], r["rank"]) for r in queue] == [
        (141, 1),
        (151, None),
        (155, None),
    ]
    assert queue[1]["outcomes"] == {"FAIL": 1}
    markdown = acceptance_markdown(
        dict(
            revision=REV,
            queue=queue,
            acceptance=dict(evidence_audit=[]),
            campaign_selection=[],
        )
    )
    table = [line for line in markdown.splitlines() if line.startswith("| ")]
    assert any("#141" in line for line in table)
    assert not any("#151" in line or "#155" in line for line in table)


def test_campaign_does_not_schedule_closed_only_obligations_or_findings():
    closed = obligation(
        issue=151,
        required_checks=[
            dict(id="v1-n20-r0-a0:reuse:reset", evidence_kind="supported-execution")
        ],
    )
    finding = dict(id="v1-n20-r0-a0:reuse:reset", status="FAIL", related_issues=[151])
    assert q.select_campaign([closed], findings=[finding], active_issues={141}) == []
    shared = dict(finding, related_issues=[141, 151])
    plans = q.select_campaign([], findings=[shared], active_issues={141})
    assert plans and plans[0]["issues"] == [141]
