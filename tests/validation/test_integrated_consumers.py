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
