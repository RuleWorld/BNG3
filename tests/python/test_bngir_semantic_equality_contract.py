"""Focused semantic-equality contract cases for BNGIR (#156).

Covers exact process-equality decisions (not numerical trajectory similarity):
renaming, rate-preserving split/merge, initial-state and observable semantics,
and non-equivalent counterexamples for supported finite-network classes.
"""

import pytest

import bionetgen
from bionetgen.bngir import EqualityUndecided
from bionetgen.model import _cpp


def M(src: str):
    return bionetgen.BioNetGenModel(_cpp.parse_string(src))


def test_semantic_equal_consistent_molecule_type_renaming():
    a = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A(s~u~p)
  B()
end molecule types
begin seed species
  A(s~u) 10
end seed species
begin observables
  Molecules A_u A(s~u)
end observables
begin reaction rules
  A(s~u) -> A(s~p) k
end reaction rules
end model
""")
    b = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  X(s~u~p)
  Y()
end molecule types
begin seed species
  X(s~u) 10
end seed species
begin observables
  Molecules X_u X(s~u)
end observables
begin reaction rules
  X(s~u) -> X(s~p) k
end reaction rules
end model
""")
    assert bionetgen.semantic_equal(a, b) is True


def test_semantic_equal_rate_preserving_split_merge():
    merged = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    split = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  R1: A() -> B() k/3
  R2: A() -> B() 2*k/3
end reaction rules
end model
""")
    assert bionetgen.semantic_equal(merged, split) is True
    bad_split = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  R1: A() -> B() k/3
  R2: A() -> B() k
end reaction rules
end model
""")
    assert bionetgen.semantic_equal(merged, bad_split) is False


def test_semantic_equal_initial_state_semantics():
    a = M(r"""
begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() 1
end reaction rules
end model
""")
    b = M(r"""
begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin reaction rules
  A() -> B() 1
end reaction rules
end model
""")
    assert bionetgen.semantic_equal(a, b) is False


def test_semantic_equal_observable_semantics_distinguished():
    a = M(r"""
begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> B() 1
end reaction rules
end model
""")
    b = M(r"""
begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Btot B()
end observables
begin reaction rules
  A() -> B() 1
end reaction rules
end model
""")
    assert bionetgen.semantic_equal(a, b) is False


def test_semantic_equal_non_equivalent_rule_direction_counterexample():
    a = M(r"""
begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin reaction rules
  A() -> B() 1
end reaction rules
end model
""")
    b = M(r"""
begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin reaction rules
  B() -> A() 1
end reaction rules
end model
""")
    assert bionetgen.semantic_equal(a, b) is False


def test_semantic_equal_requires_explicit_undecided_for_unsupported_case():
    # Unsupported/uncertified symbolic cases must not be guessed as equal or
    # unequal by numerical or trajectory similarity.
    a = M(r"""
begin model
begin parameters
  k1 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin functions
  f() = if(time()>0.5, k1, 0)
end functions
begin reaction rules
  A() -> B() f()
end reaction rules
end model
""")
    b = M(r"""
begin model
begin parameters
  k1 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin functions
  f() = if(time()>0.25, k1, 0)
end functions
begin reaction rules
  A() -> B() f()
end reaction rules
end model
""")
    with pytest.raises(EqualityUndecided):
        bionetgen.semantic_equal(a, b)


def test_semantic_equal_rule_reordering_eq_order_like():
    a = M(r"""
begin model
begin parameters
  k1 1
  k2 2
end parameters
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() k1
  B() -> C() k2
end reaction rules
end model
""")
    b = M(r"""
begin model
begin parameters
  k1 1
  k2 2
end parameters
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  B() -> C() k2
  A() -> B() k1
end reaction rules
end model
""")
    assert bionetgen.semantic_equal(a, b) is True


def test_semantic_equal_undecided_has_structured_diagnostic():
    a = M(r"""
begin model
begin molecule types
  A()
end molecule types
begin functions
  reported(x)=x
end functions
end model
""")
    b = M(r"""
begin model
begin molecule types
  A()
end molecule types
begin functions
  reported(x)=2*x
end functions
end model
""")
    with pytest.raises(EqualityUndecided) as excinfo:
        bionetgen.semantic_equal(a, b)
    assert excinfo.value.diagnostic.get("status") == "undecided"
    assert isinstance(excinfo.value.diagnostic.get("message"), str)


def test_semantic_equal_unobserved_self_loop_noop():
    # Unobserved self-loop firings do not change the ordinary state-process
    # generator (EQ-noop equal case, no reaction-count observation).
    a = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    b = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin reaction rules
  A() -> B() k
  A() -> A() k
end reaction rules
end model
""")
    assert bionetgen.semantic_equal(a, b) is True


def test_semantic_equal_verified_initial_state_counterexample():
    a = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    b = M(r"""
begin model
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
""")
    assert bionetgen.semantic_equal(a, b) is False


def test_semantic_equal_protocol_action_order_requires_witness():
    a = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 1
end seed species
begin reaction rules
  A() -> 0 k
end reaction rules
end model
setParameter("k",1)
setParameter("k",2)
""")
    b = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 1
end seed species
begin reaction rules
  A() -> 0 k
end reaction rules
end model
setParameter("k",2)
setParameter("k",1)
""")
    with pytest.raises(EqualityUndecided) as excinfo:
        bionetgen.semantic_equal(a, b)
    assert excinfo.value.diagnostic["status"] == "undecided"
    assert (
        excinfo.value.diagnostic["left_actions"]
        != excinfo.value.diagnostic["right_actions"]
    )


def test_semantic_equal_protocol_simulate_argument_difference():
    base = r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 1
end seed species
begin reaction rules
  A() -> 0 k
end reaction rules
end model
"""
    a = M(base + '\nsimulate({method=>"ode",t_end=>1,n_steps=>10})\n')
    b = M(base + '\nsimulate({method=>"ode",t_end=>2,n_steps=>10})\n')
    with pytest.raises(EqualityUndecided) as excinfo:
        bionetgen.semantic_equal(a, b)
    diag = excinfo.value.diagnostic
    assert diag["status"] == "undecided"
    assert diag.get("left_actions") != diag.get("right_actions") or diag.get("left_wire_actions") != diag.get("right_wire_actions")


def test_semantic_equal_eq_rename_initial_state_counterexample():
    # EQ-rename differing pair: consistent renaming but changed initial state.
    a = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A(s~u~p)
end molecule types
begin seed species
  A(s~u) 1
end seed species
begin reaction rules
  A(s~u) -> A(s~p) k
end reaction rules
end model
""")
    b = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  X(s~u~p)
end molecule types
begin seed species
  X(s~u) 2
end seed species
begin reaction rules
  X(s~u) -> X(s~p) k
end reaction rules
end model
""")
    assert bionetgen.semantic_equal(a, b) is False


def test_semantic_equal_eq_split_counterexample_rate_sum_differs():
    # EQ-split differing pair: split channels do not sum to the same hazard.
    merged = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    split = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  R1: A() -> B() k/3
  R2: A() -> B() k
end reaction rules
end model
""")
    assert bionetgen.semantic_equal(merged, split) is False


def test_semantic_equal_eq_unknown_raises_undecided_never_false():
    # EQ-unknown: symbolic identity without an available proof certificate must
    # raise EqualityUndecided, never return False.
    a = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin functions
  f() = sin(time())*sin(time()) + cos(time())*cos(time())
end functions
begin reaction rules
  A() -> B() k*f()
end reaction rules
end model
""")
    b = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin functions
  f() = 1
end functions
begin reaction rules
  A() -> B() k*f()
end reaction rules
end model
""")
    with pytest.raises(EqualityUndecided):
        bionetgen.semantic_equal(a, b)
