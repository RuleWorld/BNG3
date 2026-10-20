"""Energy extension qualification (#177).

Issue #177 asks for analytic expectations and an independent reference for
the detailed-balance/affinity, reversal, unit and exporter claims, and asks
for the experimental opt-in to stay explicit until the supported extension
surface has execution evidence.

``tests/validation/energy_qualification.py`` qualifies that surface on a
fixed generated corpus. These tests keep the qualification honest: the
corpus must stay fixed, a wrong analytic expectation must fail instead of
passing quietly, the experimental gate must actually refuse, the canonical
oracle must be used only for the subset it implements, and the catalog must
name the checks this family executes.
"""

from __future__ import annotations

import hashlib
import json
import math

import pytest

from tests.validation import campaign

from tests.validation import energy_qualification as qualification

ISSUES = (177,)


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    directory = tmp_path_factory.mktemp("energy-qualification")
    return qualification.run_worker(directory)


def _by_id(rows):
    return {row["id"]: row for row in rows}


def test_the_corpus_is_fixed_and_recorded():
    """The corpus must be the same generated cases on every run."""
    record = qualification.corpus_record()
    assert record["cases"], "the qualification needs a fixed corpus"
    assert qualification.corpus_digest() == qualification.corpus_digest()
    assert len(record["cases"]) == len(qualification.cases())
    for case in record["cases"]:
        assert (
            case["bngl_sha256"]
            == hashlib.sha256(qualification.case_source(case).encode()).hexdigest()
        )
        assert case["population"] > 0
        assert record["ensemble_runs"] >= 8
        assert record["statistical_sigma"] > 0


def test_check_identities_are_stable_and_unique():
    ids = qualification.check_ids()
    assert len(ids) == len(set(ids))
    assert all(item.startswith("energy-qualification:") for item in ids)
    assert "energy-qualification:family:environment-record" in ids
    assert "energy-qualification:family:experimental-opt-in" in ids
    assert "energy-qualification:family:canonical-oracle-boundary" in ids
    assert "energy-qualification:family:driven-cycle-affinity" in ids
    for case in qualification.cases():
        assert f"energy-qualification:{case['id']}:detailed-balance" in ids
        assert f"energy-qualification:{case['id']}:reversal" in ids
        assert f"energy-qualification:{case['id']}:units" in ids
        assert f"energy-qualification:{case['id']}:exporter-semantics" in ids
    # The independent reference exists only where the canonical oracle
    # implements the subset; the extension subset has no canonical oracle.
    reference_cases = {
        case["id"] for case in qualification.cases() if case["reference"]
    }
    for case in qualification.cases():
        identity = f"energy-qualification:{case['id']}:independent-reference"
        assert (identity in ids) == (case["id"] in reference_cases)
    assert reference_cases, "the corpus must exercise the referenceable subset"


def test_every_named_check_reaches_an_observation(rows):
    assert {row["id"] for row in rows} == set(qualification.check_ids())
    for row in rows:
        assert row["status"] in campaign.STATUSES
        assert row["related_issues"] == list(ISSUES)
        assert row["detail"]
        if ":family:" in row["id"]:
            continue
        assert row["source_artifact"].endswith(".bngl")
        assert len(row["source_sha256"]) == 64


def test_the_analytic_controls_hold(rows):
    """Every rate claim must reproduce the closed-form law of its case."""
    failures = [
        row for row in rows if row["status"] != "PASS" and ":family:" not in row["id"]
    ]
    assert not failures, json.dumps(failures, indent=2)


def test_the_environment_and_corpus_are_recorded_with_the_evidence(rows):
    row = _by_id(rows)["energy-qualification:family:environment-record"]
    assert row["status"] == "PASS"
    assert "corpus " in row["detail"]
    assert "revision " in row["detail"]
    assert "canonical oracle" in row["detail"]


def test_the_experimental_opt_in_is_explicit(rows):
    """The extension must refuse when the gate is unset."""
    row = _by_id(rows)["energy-qualification:family:experimental-opt-in"]
    assert row["status"] == "PASS"
    assert row["evidence_kind"] == "diagnostic-only"
    assert row["supported_execution"] is False
    assert qualification.GATE in row["detail"]


def test_the_canonical_oracle_boundary_is_named(rows):
    """The canonical oracle must not be used as proof for the extension."""
    row = _by_id(rows)["energy-qualification:family:canonical-oracle-boundary"]
    assert row["status"] == "PASS"
    assert row["evidence_kind"] == "diagnostic-only"
    assert row["supported_execution"] is False
    assert "analytic law alone" in row["detail"]


def test_the_driven_cycle_carries_a_nonzero_affinity(rows):
    """A driven cycle must be distinguishable from an equilibrium cycle."""
    row = _by_id(rows)["energy-qualification:family:driven-cycle-affinity"]
    assert row["status"] == "PASS"
    assert row["supported_execution"] is True
    affinity = qualification.cycle_affinity()
    assert affinity != 0.0
    assert "not equilibrium-compatible" in row["detail"]


def test_the_extension_subset_has_no_canonical_reference(rows):
    """Only the referenceable subset may claim an independent reference."""
    for case in qualification.cases():
        identity = f"energy-qualification:{case['id']}:independent-reference"
        if identity not in _by_id(rows):
            continue
        row = _by_id(rows)[identity]
        assert row["status"] == "PASS"
        assert row["supported_execution"] is True
        assert "canonical Perl BNG2 oracle" in row["detail"]


def test_a_wrong_expectation_is_refused_instead_of_recorded(tmp_path, monkeypatch):
    """A wrong analytic expectation must fail, not pass quietly."""
    original = qualification.analytic_rates

    def broken(case):
        forward, reverse = original(case)
        return forward * 1.5, reverse * 1.5

    monkeypatch.setattr(qualification, "analytic_rates", broken)
    broken_rows = _by_id(qualification.run_worker(tmp_path))
    for case in qualification.cases():
        for name in ("detailed-balance", "network-free-agreement"):
            row = broken_rows[f"energy-qualification:{case['id']}:{name}"]
            assert row["status"] == "FAIL", row
            assert row["first_difference"], row


def test_a_wrong_affinity_expectation_is_refused(tmp_path, monkeypatch):
    """A wrong effective-difference expectation must fail the affinity control."""
    original = qualification.analytic_effective_delta_g
    monkeypatch.setattr(
        qualification,
        "analytic_effective_delta_g",
        lambda case: original(case) + 0.5,
    )
    broken_rows = _by_id(qualification.run_worker(tmp_path))
    for case in qualification.cases():
        row = broken_rows[f"energy-qualification:{case['id']}:transition-affinity"]
        assert row["status"] == "FAIL", row
        assert row["first_difference"], row


def test_a_wrong_gate_state_is_refused(tmp_path, monkeypatch):
    """A gate that does not refuse must fail the opt-in control."""
    monkeypatch.setattr(
        qualification,
        "check_experimental_opt_in",
        lambda directory: qualification._correctness(
            False,
            "the network writer accepted a driven rule with the gate unset",
        ),
    )
    rows = _by_id(qualification.run_worker(tmp_path))
    row = rows["energy-qualification:family:experimental-opt-in"]
    assert row["status"] == "FAIL"
    assert row["detail"]


def test_the_evaluator_rejects_an_unknown_parameter():
    """The independent evaluator must not silently accept a bad expression."""
    from tests.validation.energy_qualification import (
        ExpressionError,
        evaluate_expression,
    )

    assert evaluate_expression(
        "exp((-(Ea+phi)))", {"Ea": 1.0, "phi": 0.5}
    ) == pytest.approx(math.exp(-1.5))
    with pytest.raises(ExpressionError):
        evaluate_expression("exp((-(Ea+missing)))", {"Ea": 1.0})
    with pytest.raises(ExpressionError):
        evaluate_expression("exp((-(Ea+phi)))", {"Ea": 1.0})


def test_the_campaign_import_emits_the_declared_identities(tmp_path, monkeypatch):
    """The campaign import must accept the rows the worker emits."""
    from argparse import Namespace

    from tests.validation import integrated_extensions as extensions

    monkeypatch.chdir(tmp_path)
    args = Namespace(report_dir=tmp_path, ensemble_runs=32)
    emitted = extensions.run_worker("energy-qualification", args)
    assert [row["id"] for row in emitted] == extensions.check_ids(
        "energy-qualification"
    )
    for row in emitted:
        assert row["check"] == row["id"].rsplit(":", 1)[-1]
        assert row["status"] in campaign.STATUSES
        assert isinstance(row["detail"], str) and row["detail"]
        assert row["related_issues"] and all(
            isinstance(number, int) and number >= 1 for number in row["related_issues"]
        )


def test_the_catalog_names_the_new_checks_for_issue_177(rows):
    """The #177 obligations must name the checks this family executes."""
    from tests.validation import issue_queue

    catalog = json.loads(
        (issue_queue.ROOT / "provenance/issue-obligations.json").read_text(
            encoding="utf-8"
        )
    )
    issue = next(row for row in catalog["issues"] if row["number"] == 177)
    named = {
        check["id"]
        for obligation in issue["obligations"]
        for check in obligation["required_checks"]
    }
    executed = {row["id"] for row in rows}
    assert executed <= named, sorted(executed - named)
    assert "energy-qualification:equilibrium-arrhenius:detailed-balance" in named
    assert "energy-qualification:equilibrium-arrhenius:independent-reference" in named
    assert "energy-qualification:family:experimental-opt-in" in named
    assert "energy-qualification:family:environment-record" in named
