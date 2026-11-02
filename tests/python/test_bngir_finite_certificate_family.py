"""Bounded, hand-enumerated process-equality certificate cases."""

from fractions import Fraction

import pytest

import bionetgen
from bionetgen.model import _cpp


def _model(source):
    return bionetgen.BioNetGenModel(_cpp.parse_string(source))


def _conversion_source(*, a="A", b="B", seed=1, rules=None, observables=""):
    if rules is None:
        rules = [f"{a}() -> {b}() k"]
    rendered_rules = "\n".join(f"    {rule}" for rule in rules)
    types = "\n".join(f"    {name}()" for name in (a, b))
    return f"""
begin model
begin parameters
    k 0.1
    k1 0.025
    k2 0.075
end parameters
begin molecule types
{types}
end molecule types
begin seed species
    {a}() {seed}
end seed species
{observables}
begin reaction rules
{rendered_rules}
end reaction rules
end model
"""


def test_finite_one_molecule_conversion_certificate_covers_split_and_renaming():
    # Independent exact enumeration for the authored source family: the only
    # reachable count states are (A,B)=(1,0) and (0,1), with one directed
    # transition of hazard 1/10 from the first state to the second.
    reachable = {(1, 0), (0, 1)}
    transitions = {((1, 0), (0, 1)): Fraction(1, 10)}
    assert reachable == {(1, 0), (0, 1)}
    assert transitions[((1, 0), (0, 1))] == Fraction(1, 10)

    observable = "begin observables\n    Molecules A_count A()\nend observables"
    whole = _model(_conversion_source())
    observed_whole = _model(_conversion_source(observables=observable))
    observed_split = _model(
        _conversion_source(
            rules=["r1: A() -> B() k1", "r2: A() -> B() k2"],
            observables=observable,
        )
    )
    renamed = _model(_conversion_source(a="X", b="Y", rules=["X() -> Y() k"]))
    changed_rate = _model(_conversion_source(rules=["A() -> B() 0.11"]))
    changed_initial = _model(_conversion_source(seed=2))

    # The exact source law is additive across directed channels. The
    # observable's kind and unit weight are retained in this same-name pair.
    assert bionetgen.semantic_equal(observed_whole, observed_split)
    assert bionetgen.semantic_equal(whole, renamed)
    assert bionetgen.semantic_equal(whole, changed_rate) is False
    assert bionetgen.semantic_equal(whole, changed_initial) is False


def test_equal_initial_ode_drift_does_not_certify_equal_jump_processes():
    first_order = _model(
        """begin model
begin parameters
    k 1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 2
end seed species
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""
    )
    paired_jump = _model(
        """begin model
begin parameters
    k 0.5
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 2
end seed species
begin reaction rules
    A() + A() -> B() + B() k
end reaction rules
end model
"""
    )

    network_a = first_order.generate_network()
    network_b = paired_jump.generate_network()
    rhs_a = _cpp._validation_ode_rhs(first_order._model, network_a, 0.0, [2.0, 0.0])
    rhs_b = _cpp._validation_ode_rhs(paired_jump._model, network_b, 0.0, [2.0, 0.0])
    assert rhs_a == pytest.approx([-2.0, 2.0])
    assert rhs_b == pytest.approx(rhs_a)

    # The independent exact jump law has different destinations and hazards:
    # one A converts at rate 2, while the two-A channel jumps directly to 2B
    # at rate (1/2) * choose(2, 2) = 1/2.
    exact_first = {((2, 0), (1, 1)): Fraction(2, 1)}
    exact_paired = {((2, 0), (0, 2)): Fraction(1, 2)}
    assert exact_first != exact_paired
    assert bionetgen.semantic_equal(first_order, paired_jump) is False
