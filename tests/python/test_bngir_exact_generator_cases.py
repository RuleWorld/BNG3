"""Bounded exact-generator and BNGIR semantic equality regressions."""


import json
from fractions import Fraction

import pytest

import bionetgen
from bionetgen.bngir import EqualityUndecided, to_bngir
from bionetgen.model import _cpp


def M(src: str):
    return bionetgen.BioNetGenModel(_cpp.parse_string(src))


def _model(rules, *, molecules="  A()\n  B()\n", seed="  A() 10\n", extra=""):
    return M(
        "begin model\n"
        "begin parameters\n  k 1\nend parameters\n"
        "begin molecule types\n" + molecules + "end molecule types\n"
        "begin seed species\n"
        + seed
        + "end seed species\n"
        + extra
        + "begin reaction rules\n"
        + rules
        + "end reaction rules\nend model\n"
    )


def _generator_unimodel(rate_terms, n0=4):
    """Independent master-equation row for A -> B with summed rate terms.

    Explicit rational generator: A(n) -> A(n-1),B(n+1) at (sum rates)*n.
    Used as the oracle for EQ-split; it does not call the product equality API.
    """
    k = sum((Fraction(num, den) for num, den in rate_terms), Fraction(0))
    return {n: {"to": n - 1, "rate": k * n} for n in range(1, n0 + 1)}


def test_eq_rename():
    # A consistent molecule-type rename (with arbitrary bond-label spelling)
    # preserves the process; a different initial amount is a decisive witness.
    def typed(name: str, count: int = 10):
        return M(
            "begin model\n"
            "begin parameters\n  k 1\nend parameters\n"
            "begin molecule types\n  " + name + "(s~u~p)\n  B()\nend molecule types\n"
            "begin seed species\n  "
            + name
            + "(s~u) "
            + str(count)
            + "\nend seed species\n"
            "begin observables\n  Molecules n " + name + "(s~u)\nend observables\n"
            "begin reaction rules\n  "
            + name
            + "(s~u) -> "
            + name
            + "(s~p) k\nend reaction rules\n"
            "end model\n"
        )

    assert bionetgen.semantic_equal(typed("A"), typed("X")) is True
    assert bionetgen.semantic_equal(typed("A"), typed("A", 11)) is False


def test_eq_split_against_independent_generator():
    merged = _model("  A() -> B() k\n")
    split = _model("  R1: A() -> B() k/3\n  R2: A() -> B() 2*k/3\n")
    bad = _model("  R1: A() -> B() k/3\n  R2: A() -> B() k\n")
    # Independent answer: k = 1 vs 1/3 + 2/3 = 1 vs 1/3 + 1 = 4/3.
    left = _generator_unimodel([(1, 1)])
    equal_right = _generator_unimodel([(1, 3), (2, 3)])
    different_right = _generator_unimodel([(1, 3), (1, 1)])
    assert left == equal_right
    assert left != different_right
    assert bionetgen.semantic_equal(merged, split) is True
    assert bionetgen.semantic_equal(merged, bad) is False


def test_eq_initial_state_and_observables():
    a = _model("  A() -> B() k\n", seed="  A() 10\n")
    b = _model("  A() -> B() k\n", seed="  A() 11\n")
    assert bionetgen.semantic_equal(a, b) is False
    obs = "begin observables\n  Molecules n A()\nend observables\n"
    a_obs = _model("  A() -> B() k\n", extra=obs)
    b_obs = _model("  A() -> B() k\n", extra=obs)
    assert bionetgen.semantic_equal(a_obs, b_obs) is True


def test_eq_unknown_is_undecided_not_false():
    left = _model("  A() -> B() sin(k)\n")
    right = _model("  A() -> B() exp(k)\n")
    with pytest.raises(EqualityUndecided) as info:
        bionetgen.semantic_equal(left, right)
    assert str(info.value)


def test_eq_serialization_versions_and_loss():
    # Exact rational rates keep this case decidable by the independent oracle;
    # function-valued rates are outside that oracle's arithmetic domain.
    a = _model("  A() -> B() k\n", seed="  A() 4\n")
    v01 = bionetgen.from_bngir(to_bngir(a, version="0.1"))
    v02 = bionetgen.from_bngir(to_bngir(a, version="0.2"))
    assert bionetgen.semantic_equal(v01, v02, version="0.2") is True
    # Changing the initial amount is execution-relevant and must not be
    # declared equal merely because the serialized documents nearly match.
    import copy

    payload = json.loads(to_bngir(a, version="0.2"))
    changed_payload = copy.deepcopy(payload)
    changed_payload["model"]["seeds"][0]["amount"]["value"] = 5.0
    changed = bionetgen.from_bngir(json.dumps(changed_payload))
    assert bionetgen.semantic_equal(a, changed) is False


def test_eq_catalogue_families():
    """Equal / different / undecided outcomes from the EQ-* design catalogue."""

    def build(rules, molecules="  A()\n  B()\n  C()\n", seed="  A() 4\n", extra=""):
        return M(
            "begin model\n"
            "begin parameters\n  k 1\nend parameters\n"
            "begin molecule types\n" + molecules + "end molecule types\n"
            "begin seed species\n"
            + seed
            + "end seed species\n"
            + extra
            + "begin reaction rules\n"
            + rules
            + "end reaction rules\nend model\n"
        )

    eq = bionetgen.semantic_equal
    # Reordering independent rules does not change the generator.
    assert (
        eq(
            build("  A() -> B() k\n  B() -> A() k\n"),
            build("  B() -> A() k\n  A() -> B() k\n"),
        )
        is True
    )
    # EQ-refine: wildcard vs the exhaustive partition.
    mols = "  A(s~u~p)\n  B()\n  C()\n"
    assert (
        eq(
            build("  A(s) -> B() k\n", molecules=mols, seed="  A(s~u) 4\n"),
            build(
                "  A(s~u) -> B() k\n  A(s~p) -> B() k\n",
                molecules=mols,
                seed="  A(s~u) 4\n",
            ),
        )
        is True
    )
    # A change in multiplicity changes the process.
    assert (
        eq(build("  A() + A() -> B() k\n"), build("  A() + A() -> B() 2*k\n")) is False
    )
    assert eq(build("  A() -> B() k\n"), build("  A() -> B() 2*k\n")) is False
    assert (
        eq(build("  A() -> B() k\n"), build("  A() -> B() k\n  A() -> B() k\n"))
        is False
    )
    # EQ-functions and EQ-noop are exact identities, not numerical similarity.
    assert eq(build("  A() -> B() k\n"), build("  A() -> B() 2*k/2\n")) is True
    assert (
        eq(build("  A() -> B() k\n"), build("  A() -> B() k\n  A() -> A() k\n")) is True
    )
    # EQ-observables: Molecules vs Species is not the same observation.
    obs_molecules = "begin observables\n  Molecules n A()\nend observables\n"
    obs_species = "begin observables\n  Species n A()\nend observables\n"
    assert (
        eq(
            build("  A() -> B() k\n", extra=obs_molecules),
            build("  A() -> B() k\n", extra=obs_species),
        )
        is False
    )
    # EQ-reachability: a rule on an unreachable species is not observable.
    assert (
        eq(build("  A() -> B() k\n"), build("  A() -> B() k\n  C() -> C() k\n")) is True
    )
    # EQ-time / EQ-unknown: outside the rational oracle, must be UNDECIDED.
    for rhs in ("sin(k)", "exp(k)"):
        with pytest.raises(EqualityUndecided) as info:
            eq(build("  A() -> B() k\n"), build("  A() -> B() " + rhs + "\n"))
        assert str(info.value)
