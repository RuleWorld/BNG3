"""The BNGsim adapter boundary is an executable contract, not prose.

These checks run the generated boundary family and prove that the contract
detects a wrong expectation, so a green result is evidence rather than a
process receipt.
"""

import json

import pytest

from tests.validation import bngsim_boundary as boundary
from tests.validation import integrated_cases


def _rows_by_id(rows):
    return {row["id"]: row for row in rows}


def test_every_generated_case_names_a_route_and_an_independent_expectation():
    cases = boundary.cases()
    assert cases
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["family"] for case in cases} == {"decay", "reversible"}
    assert {case["lowerable"] for case in cases} == {True, False}
    for case in cases:
        assert case["source"].startswith("begin model")
        assert "A()" in case["source"]
        if case["lowerable"]:
            assert case["expected_blocker"] is None
        else:
            assert case["expected_blocker"]
    assert len(boundary.check_ids()) == len(set(boundary.check_ids()))


def test_generated_boundary_family_records_named_routes_and_matches_the_law(
    api, tmp_path
):
    rows = boundary.run(tmp_path)
    observed = _rows_by_id(rows)
    assert set(observed) == set(boundary.check_ids())
    for row in rows:
        assert row["status"] in {"PASS", "UNSUPPORTED"}, json.dumps(row, default=str)[
            :2000
        ]
        assert row["related_issues"] == [144]
        assert isinstance(row["detail"], str) and row["detail"]
    # The BNGsim route is only executable where the adapter is linked; the
    # difference is reported, never hidden.
    from bionetgen import _bionetgen_cpp as cpp

    bngsim_row = observed["bngsim-boundary:differential-bngsim-route"]
    if cpp.bngsim_available():
        assert bngsim_row["status"] == "PASS"
    else:
        assert bngsim_row["status"] == "UNSUPPORTED"
        assert "not linked" in bngsim_row["detail"]
    # Every native route observation reproduced the independent law.
    for row in rows:
        if row["id"].endswith(":independent-law"):
            assert row["status"] == "PASS"
            assert row["first_difference"] is None
        if row["id"].endswith(":route-decision"):
            assert row["status"] == "PASS"
            assert row["route"] in boundary.ROUTES
            assert row["reason"]


def test_a_wrong_source_law_is_detected(api, tmp_path, monkeypatch):
    """The comparison is live: a wrong independent law must fail the check."""
    monkeypatch.setattr(integrated_cases, "RATE", 0.8)
    rows = boundary.run(tmp_path, runs=32)
    failed = [row for row in rows if row["status"] == "FAIL"]
    assert failed, "a wrong source law was not detected"
    identifiers = {row["id"] for row in failed}
    assert any(
        identifier.endswith(":ode:independent-law") for identifier in identifiers
    )
    assert any(
        identifier.endswith(":ssa:independent-law") for identifier in identifiers
    )


def test_an_undeclared_route_is_a_contract_violation(api, tmp_path, monkeypatch):
    """A route outside the declared set is refused rather than accepted."""
    from bionetgen import _bionetgen_cpp as cpp

    original = cpp.finite_backend_decision

    def undeclared(model, network, requested="auto", method="ode"):
        decision = dict(original(model, network, requested=requested, method=method))
        decision["route"] = "native-fallback:undeclared"
        return decision

    monkeypatch.setattr(cpp, "finite_backend_decision", undeclared)
    rows = boundary.run(tmp_path, runs=8)
    failed = [row for row in rows if row["status"] == "FAIL"]
    assert failed, "an undeclared route was accepted"
    assert all(row["id"].endswith(":route-decision") for row in failed)
