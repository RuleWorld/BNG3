"""Acceptance evidence must match independently declared obligations."""

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
            not_reapplied = set(
                obligation.get("not_reapplied_from_recorded_revision", [])
            )
            assert obligation["criterion"] and obligation["scope"]
            assert obligation["completion_condition"]
            for ref in obligation["test_references"]:
                path_exists = (q.ROOT / ref.split("::")[0]).exists()
                assert path_exists or ref in not_reapplied, ref
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


def test_issue160_requires_full_execution_scope_not_dispositions():
    """#160 retains all Core/comp rows and the three live acceptance checks."""
    import json

    catalog = json.loads((q.ROOT / "provenance/issue-obligations.json").read_text())
    issue = next(item for item in catalog["issues"] if item["number"] == 160)
    matrix = json.loads((q.ROOT / "provenance/capability-matrix.yml").read_text())
    rows = [row for row in matrix["rows"] if row["issue"] == 160]
    release_obligations = [
        o for o in issue["obligations"] if o["id"].startswith("issue:160:release-")
    ]
    historical_ids = {
        "issue:160:group-current-unsupported-cases-by-dynamic-rules-events-history",
        "issue:160:for-each-class-implement-a-semantics-preserving-supported-subset",
        "issue:160:closure-record",
    }
    assert historical_ids <= {o["id"] for o in issue["obligations"]}
    historical_checks = {
        check["id"]
        for o in issue["obligations"]
        if o["id"] in historical_ids
        for check in o["required_checks"]
    }
    assert historical_checks == {
        "sbml-support-boundary:species-assignment-rule:named-diagnostic",
        "sbml-support-boundary:state-dependent-event:named-diagnostic",
        "sbml-support-boundary:delayed-history:named-diagnostic",
        "sbml-support-boundary:algebraic-rule:named-diagnostic",
        "sbml-support-boundary:sbml-constraint:named-diagnostic",
        "sbml-support-boundary:negative-stoichiometry:named-diagnostic",
        "sbml-support-boundary:fast-reaction:named-diagnostic",
        "sbml-support-boundary:fbc-package:named-diagnostic",
        "sbml-support-boundary:spatial-package:named-diagnostic",
        "sbml-support-boundary:corpus:every-refusal-classified",
        "qualification:issue:160:for-each-class-implement-a-semantics-preserving-supported-subset",
        "qualification:issue:160:closure-record",
    }
    historical_obligations = [
        o for o in issue["obligations"] if o["id"] in historical_ids
    ]
    assert all(o.get("scope_status") == "STALE_SCOPE" for o in historical_obligations)
    historical_report = dict(
        source=dict(revision=REV, dirty=False),
        results=[
            dict(id=check_id, status="PASS", evidence_kind="disposition")
            for check_id in historical_checks
        ],
    )
    historical_result = q.assess_obligations(
        historical_obligations, [historical_report], REV
    )
    assert {result["status"] for result in historical_result["obligations"]} == {
        "DECISION_REQUIRED"
    }
    required = [check for o in release_obligations for check in o["required_checks"]]
    expected = {
        "release-sbml-core-comp",
        "release-sbml-source-fidelity",
        "release-capability-coverage-160",
        *(f"release-capability[{row['id']}]" for row in rows),
    }
    assert len(rows) == 117
    assert {check["id"] for check in required} == expected
    assert all(check["evidence_kind"] == "supported-execution" for check in required)
    assert all(
        set(c["identity_requirements"])
        == {
            "source.revision",
            "subject.sha256",
            "references.sbml.revision",
            "references.sbml.sha256",
        }
        for c in required
    )
    # Matching, optimistically labelled receipts still need both independent
    # oracle identity and the exact subject artifact, not just a git revision.
    report = dict(
        source=dict(revision=REV, dirty=False),
        results=[
            dict(
                id=c["id"],
                status="PASS",
                supported_execution=True,
                evidence_kind="supported-execution",
            )
            for c in required
        ],
    )
    result = q.assess_obligations(release_obligations, [report], REV)
    assert {o["status"] for o in result["obligations"]} == {"EVIDENCE_GAP"}

    # Even reusing every required identity cannot promote a diagnostic pass or
    # an unsupported required input into successful scientific execution.
    for status, kind, expected_status in (
        ("PASS", "diagnostic-only", "EVIDENCE_GAP"),
        ("PASS", None, "EVIDENCE_GAP"),  # ordinary/historical pytest pass
        ("UNSUPPORTED", "diagnostic-only", "UNSUPPORTED"),
    ):
        report = dict(
            source=dict(revision=REV, dirty=False),
            results=[
                dict(
                    id=c["id"],
                    status=status,
                    evidence_kind=kind,
                    supported_execution=False,
                )
                for c in required
            ],
        )
        result = q.assess_obligations(release_obligations, [report], REV)
        assert {o["status"] for o in result["obligations"]} == {expected_status}
    result = q.assess_obligations(release_obligations, [], REV)
    assert {o["status"] for o in result["obligations"]} == {"NOT_TESTED"}


def test_supported_execution_labels_cannot_override_recorded_loss():
    for severity in (
        "dropped",
        "approximated",
        "unsupported",
        "untranslated",
        "error",
        "ERROR",
    ):
        row = dict(
            id="consumer:values",
            status="PASS",
            supported_execution=True,
            evidence_kind="supported-execution",
            diagnostics=[
                dict(
                    category="mathml",
                    severity=severity,
                    message="required semantics lost",
                )
            ],
        )
        result = assess([row])["obligations"][0]
        assert result["status"] == "EVIDENCE_GAP"
        assert (
            "loss diagnostics prevent supported execution" in result["missing_evidence"]
        )
    row["diagnostics"][0]["severity"] = "info"
    assert assess([row])["obligations"][0]["status"] == "DEMONSTRATED"
