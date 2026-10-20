"""Fault controls for the differential graph-identity qualification (#168).

The qualification compares the production network with a network the canonical
Perl BNG2 generates for the same source, using the harness's own reader and
its own graph matcher.  These tests inject the faults that would make such a
comparison meaningless: a production network that keeps a duplicate species, a
production species the reference does not have, an independent construction
that cannot express the case, and a case that falls outside the declared
domain.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from tests.validation import graph_differential


def _tmp_path():
    return Path(tempfile.mkdtemp())


def test_every_generated_case_declares_its_scope():
    cases = graph_differential.CASES
    assert cases
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert case["text"].startswith("begin model")
        assert case["text"].rstrip().endswith("end model")
        assert case["seed_species"]
        assert case["rule_count"] == len(
            [line for line in case["text"].splitlines() if "->" in line]
        )
        assert case["purpose"]


def test_the_generated_family_covers_the_identity_stress_shapes():
    identifiers = {case["id"] for case in graph_differential.CASES}
    assert {
        "symmetric-dimer-2",
        "symmetric-dimer-3",
        "molecule-order-swap",
        "state-flip-u-p",
        "state-flip-on-off",
        "compartment-dimer",
        "no-rule-outside-domain",
    } == identifiers
    # The molecule-order case is the identity stress: two rules whose products
    # are isomorphic under a different molecule order.
    swap = next(
        case for case in graph_differential.CASES if case["id"] == "molecule-order-swap"
    )
    assert "A(b!1).B(b!1)" in swap["text"]
    assert "B(b!1).A(b!1)" in swap["text"]


def test_the_named_check_identities_are_unique_and_named():
    ids = graph_differential.check_ids()
    assert len(ids) == len(set(ids))
    assert "campaign:graph-differential" not in ids
    assert set(ids) <= set(
        f"graph-differential:{case['id']}:{name}"
        for case in graph_differential.CASES
        for name in graph_differential.CHECKS
    )


def test_the_bijection_check_rejects_a_production_network_with_an_extra_species():
    differences = graph_differential._bijection_differences(
        ["A(b)", "B(b)", "C(b)"],
        ["A(b)", "B(b)"],
    )
    assert differences
    assert differences[0]["field"] == "network.species.count"


def test_the_bijection_check_rejects_a_species_the_reference_does_not_have():
    differences = graph_differential._bijection_differences(
        ["A(b)", "Z(b)"],
        ["A(b)", "B(b)"],
    )
    assert differences
    assert differences[0]["field"] == "network.species.unmatched"


def test_the_bijection_check_accepts_an_isomorphic_species_under_another_spelling():
    assert (
        graph_differential._bijection_differences(
            ["A(b!1).B(b!1)"],
            ["B(b!1).A(b!1)"],
        )
        == []
    )


def test_the_relation_check_rejects_a_production_network_with_a_duplicate():
    differences = graph_differential._relation_differences(
        ["A(b!1).B(b!1)", "B(b!1).A(b!1)"],
        ["A(b!1).B(b!1)"],
    )
    assert differences
    assert differences[0]["field"].startswith("relation.")
    assert "one representative per identity class" == differences[0]["expected"]


def test_the_relation_check_rejects_a_species_with_two_isomorphic_partners():
    differences = graph_differential._relation_differences(
        ["A(b!1).B(b!1)"],
        ["A(b!1).B(b!1)", "B(b!1).A(b!1)"],
    )
    assert differences
    assert differences[0]["field"].startswith("relation.")
    assert differences[0]["expected"] == "one representative per identity class"


def test_the_relation_check_accepts_two_networks_that_correspond():
    assert (
        graph_differential._relation_differences(
            ["A(b!1).B(b!1)"],
            ["B(b!1).A(b!1)"],
        )
        == []
    )


def test_the_matching_is_deterministic():
    left = ["A(b)", "B(b)"]
    right = ["B(b)", "A(b)"]
    first = graph_differential._match(left, right)
    assert first == graph_differential._match(left, right)


def test_a_case_without_a_rule_is_outside_the_declared_domain():
    case = next(
        case
        for case in graph_differential.CASES
        if case["id"] == "no-rule-outside-domain"
    )
    violations = graph_differential._domain_violations(case, [], [])
    assert violations
    assert "no reaction rule" in violations[0]


def test_isomorphic_seed_species_leave_the_declared_domain():
    case = next(
        case for case in graph_differential.CASES if case["id"] == "symmetric-dimer-2"
    )
    duplicated = dict(case, seed_species=["A(b)", "A(b)"])
    violations = graph_differential._domain_violations(duplicated, [], [])
    assert any("isomorphic" in violation for violation in violations)


def test_a_network_above_the_size_bound_leaves_the_declared_domain():
    case = next(
        case for case in graph_differential.CASES if case["id"] == "symmetric-dimer-2"
    )
    violations = graph_differential._domain_violations(
        case, ["A(b)"] * (graph_differential.MAX_SPECIES + 1), []
    )
    assert any("species" in violation for violation in violations)


def test_a_case_outside_the_domain_is_refused_and_never_passed():
    rows = graph_differential.run_worker(_tmp_path())
    refused = [
        row
        for row in rows
        if row["id"].startswith("graph-differential:no-rule-outside-domain")
    ]
    assert refused
    assert {row["status"] for row in refused} == {"UNSUPPORTED"}
    assert not any(row["status"] == "PASS" for row in refused)
    assert all(row["supported_execution"] is False for row in refused)


def test_an_independent_construction_that_cannot_express_the_case_is_refused(
    monkeypatch,
):
    def refuse(directory, case, source):
        return None, None, "the canonical Perl BNG2 refused the case: synthetic"

    monkeypatch.setattr(graph_differential, "_oracle_network", refuse)
    rows = graph_differential.run_worker(_tmp_path())
    assert rows
    assert {row["status"] for row in rows} == {"UNSUPPORTED"}
    assert not any(row["status"] == "PASS" for row in rows)
    judged = [row for row in rows if "no-rule-outside-domain" not in row["id"]]
    assert judged
    assert all("synthetic" in row["detail"] for row in judged)


def test_a_production_network_that_cannot_be_generated_is_a_harness_error(
    monkeypatch,
):
    def fail(directory, case, source):
        raise RuntimeError("synthetic production failure")

    monkeypatch.setattr(graph_differential, "_production_network", fail)
    rows = graph_differential.run_worker(_tmp_path())
    assert rows
    judged = [row for row in rows if "no-rule-outside-domain" not in row["id"]]
    assert judged
    assert {row["status"] for row in judged} == {"HARNESS_ERROR"}
    assert not any(row["status"] == "PASS" for row in judged)
    assert all("synthetic production failure" in row["detail"] for row in judged)


def test_the_worker_emits_one_named_row_per_check_and_case():
    rows = graph_differential.run_worker(_tmp_path())
    assert [row["id"] for row in rows] == graph_differential.check_ids()
    for row in rows:
        assert row["status"] in {
            "PASS",
            "FAIL",
            "HARNESS_ERROR",
            "UNSUPPORTED",
        }
        assert row["related_issues"] == [168]
        assert isinstance(row["detail"], str) and row["detail"]
        if row["status"] == "FAIL":
            assert row["first_difference"] is not None


def test_the_declared_domain_and_bounds_are_stated():
    assert "reaction rules" in graph_differential.DOMAIN
    assert "isomorphic" in graph_differential.DOMAIN
    assert graph_differential.MAX_SPECIES == 8
    assert graph_differential.MAX_REACTIONS == 12
    assert graph_differential.MAX_VERTICES == 12
    assert graph_differential.MAX_ITERATIONS == 100
    assert "termination argument" in graph_differential.__doc__
