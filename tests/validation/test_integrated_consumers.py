"""Small contract checks for integrated consumer evidence, no engine runs."""

from tests.validation import integrated_consumers as consumers


def _checks(operation, case="generated-case", status="PASS"):
    return [
        {
            "id": f"{case}:{operation}:{name}",
            "name": name,
            "status": status,
            "detail": "synthetic contract row",
            "first_difference": None,
            "issue_ids": list(consumers.ISSUES[operation]),
        }
        for name in consumers.CHECKS[operation]
    ]


def test_every_operation_declares_named_checks_with_issue_links():
    ids = consumers.expected_check_ids(["case-a", "case-b"])
    assert len(ids) == len(set(ids))
    for operation in consumers.OPERATIONS:
        rows = _checks(operation)
        assert consumers.validate_checks("generated-case", operation, rows) == []
        assert consumers.status_from_checks("generated-case", operation, rows) == "PASS"


def test_missing_duplicate_or_misidentified_consumer_checks_are_harness_errors():
    rows = _checks("bngir-v02")[:-1]
    assert (
        consumers.status_from_checks("generated-case", "bngir-v02", rows)
        == "HARNESS_ERROR"
    )

    rows = _checks("bngir-v02")
    rows.append(dict(rows[0]))
    assert (
        consumers.status_from_checks("generated-case", "bngir-v02", rows)
        == "HARNESS_ERROR"
    )

    rows = _checks("bngl-reload")
    rows[0]["id"] = "other:case"
    assert (
        consumers.status_from_checks("generated-case", "bngl-reload", rows)
        == "HARNESS_ERROR"
    )


def test_failed_and_unsupported_checks_remain_distinct():
    failed = _checks("reuse")
    failed[1]["status"] = "FAIL"
    failed[1]["first_difference"] = {"field": "k", "left": 0.6, "right": 0.4}
    assert consumers.status_from_checks("generated-case", "reuse", failed) == "FAIL"

    unsupported = _checks("sbml-reload")
    unsupported[1]["status"] = "UNSUPPORTED"
    unsupported[2]["status"] = "NOT_TESTED"
    assert (
        consumers.status_from_checks("generated-case", "sbml-reload", unsupported)
        == "UNSUPPORTED"
    )

    missing_dependency = _checks("sbml-reload")
    missing_dependency[1]["status"] = "HARNESS_ERROR"
    missing_dependency[1]["detail"] = "required dependency unavailable"
    missing_dependency[2]["status"] = "NOT_TESTED"
    assert (
        consumers.status_from_checks(
            "generated-case", "sbml-reload", missing_dependency
        )
        == "HARNESS_ERROR"
    )


def test_native_rhs_comparison_aligns_species_graphs_before_values():
    from tests.validation.integrated_worker import _network_difference

    left = dict(
        num_species=2,
        num_reactions=1,
        species=["A()", "B()"],
        unit_state_probe=dict(state=[1, 1], ode_rhs=[-1, 1]),
    )
    right = dict(
        num_species=2,
        num_reactions=1,
        species=["B()", "A()"],
        unit_state_probe=dict(state=[1, 1], ode_rhs=[1, -1]),
    )
    assert _network_difference(left, right) is None
    right["unit_state_probe"]["ode_rhs"] = [2, -1]
    assert _network_difference(left, right)["field"] == "unit_state_probe.ode_rhs"


def test_semantic_difference_reports_the_first_structural_path():
    from tests.validation.integrated_worker import _document_difference

    assert _document_difference(
        {"model": {"seeds": [{"compartment": "cell"}]}}, {"model": {"seeds": [{}]}}
    ) == {
        "field": "/model/seeds/0/compartment",
        "left": "cell",
        "right_missing": True,
    }
    assert _document_difference({"a": [1, 2]}, {"a": [1, 3]}) == {
        "field": "/a/1",
        "left": 2,
        "right": 3,
    }
    assert _document_difference({"a": 1}, {"a": 1}) is None


def test_failed_peer_contract_does_not_block_a_completed_artifact_handoff():
    parent = dict(id="case:bngl-reload", status="FAIL")
    rows = [
        dict(
            id="case:bngl-reload:semantic-equality",
            name="semantic-equality",
            status="FAIL",
        ),
        dict(id="case:bngl-reload:simulation", name="simulation", status="PASS"),
    ]
    assert consumers.handoff_dependency(parent, rows, "simulation") == rows[1]
    assert consumers.handoff_dependency(parent, rows, "network") == parent
    broken_identity = dict(parent, status="HARNESS_ERROR")
    assert (
        consumers.handoff_dependency(broken_identity, rows, "simulation")
        == broken_identity
    )


def test_process_summaries_do_not_duplicate_findings_or_hide_process_errors():
    rows = [dict(id="case:stage:values", status="FAIL")]
    parent = dict(id="case:stage", status="FAIL")
    consumers.mark_process_summary(parent, rows)
    assert parent["aggregate"] is True
    assert parent["child_ids"] == ["case:stage:values"]
    crashed = dict(id="case:stage", status="HARNESS_ERROR")
    consumers.mark_process_summary(crashed, rows)
    assert not crashed.get("aggregate")
    missing = dict(id="case:stage", status="FAIL")
    consumers.mark_process_summary(missing, [])
    assert not missing.get("aggregate")


def test_non_pass_rollup_states_the_reason_its_children_give():
    """A rollup that is not a pass must explain itself.

    The consumer matrix requires every non-pass cell to carry an
    explanation, and the rollup row is the cell the matrix reads.
    """
    parent = dict(id="case:stage", status="UNSUPPORTED", detail="")
    consumers.mark_process_summary(
        parent,
        [
            dict(
                id="case:stage:semantic-equality",
                status="UNSUPPORTED",
                detail="native BNGIR does not support model.functions",
            ),
            dict(id="case:stage:simulation", status="NOT_TESTED", detail="blocked"),
        ],
    )
    assert parent["aggregate"] is True
    assert parent["detail"] == "native BNGIR does not support model.functions"

    passing = dict(id="case:stage", status="PASS", detail="")
    consumers.mark_process_summary(
        passing, [dict(id="case:stage:values", status="PASS", detail="ok")]
    )
    assert passing["detail"] == ""
