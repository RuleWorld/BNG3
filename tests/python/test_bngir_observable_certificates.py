"""Independent specification and test contracts for BNGIR observable certificates.

Verifies exact process equality under observable renaming, molecule renaming,
and ensures models with missing or mismatching observable definitions are not
falsely certified.
"""

import pytest

import bionetgen
from bionetgen.bngir import from_bngir, semantic_equal, to_bngir
from bionetgen.model import _cpp


def _model(source: str) -> bionetgen.BioNetGenModel:
    return bionetgen.BioNetGenModel(_cpp.parse_string(source))


def test_semantic_equal_certifies_renamed_observables_identical_species():
    src_a = """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules obs_A A()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""
    src_b = """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules count_A A()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""
    ma = _model(src_a)
    mb = _model(src_b)
    # The physical quantities observed are identical: both measure A() count.
    # Renaming the output label must be certified as semantically equal.
    assert semantic_equal(ma, mb) is True


def test_semantic_equal_certifies_renamed_observables_renamed_types():
    src_a = """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules obs_A A()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""
    src_b = """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
    Y()
end molecule types
begin seed species
    X() 10
end seed species
begin observables
    Molecules obs_X X()
end observables
begin reaction rules
    X() -> Y() k
end reaction rules
end model
"""
    ma = _model(src_a)
    mb = _model(src_b)
    # Under bijection A -> X, B -> Y, obs_A (A()) maps to obs_X (X()).
    assert semantic_equal(ma, mb) is True


def test_semantic_equal_rejects_missing_observables_in_renamed_types():
    src_with_obs = """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules obs_A A()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""
    src_without_obs = """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
    Y()
end molecule types
begin seed species
    X() 10
end seed species
begin reaction rules
    X() -> Y() k
end reaction rules
end model
"""
    ma = _model(src_with_obs)
    mb = _model(src_without_obs)
    # A model observing A() cannot be certified equal to a model with no observables.
    with pytest.raises(bionetgen.EqualityUndecided):
        semantic_equal(ma, mb)


def test_semantic_equal_rejects_wrong_observable_pattern_in_renamed_types():
    src_a = """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A(x~u~p)
end molecule types
begin seed species
    A(x~u) 10
end seed species
begin observables
    Molecules obs A(x~u)
end observables
begin reaction rules
    A(x~u) -> A(x~p) k
end reaction rules
end model
"""
    src_b = """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X(x~u~p)
end molecule types
begin seed species
    X(x~u) 10
end seed species
begin observables
    Molecules obs X(x~p)
end observables
begin reaction rules
    X(x~u) -> X(x~p) k
end reaction rules
end model
"""
    ma = _model(src_a)
    mb = _model(src_b)
    # ma observes unphosphorylated state (10 -> 0), mb observes phosphorylated state (0 -> 10).
    # These distinct observable processes must never be certified equal.
    with pytest.raises(bionetgen.EqualityUndecided):
        semantic_equal(ma, mb)


def test_semantic_equal_certifies_multiple_permuted_renamed_observables():
    src_a = """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules o1 A()
    Molecules o2 B()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""
    src_b = """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
    Y()
end molecule types
begin seed species
    X() 10
end seed species
begin observables
    Molecules oY Y()
    Molecules oX X()
end observables
begin reaction rules
    X() -> Y() k
end reaction rules
end model
"""
    ma = _model(src_a)
    mb = _model(src_b)
    # Under A -> X, B -> Y: o1 (A()) -> oX (X()), o2 (B()) -> oY (Y()).
    assert semantic_equal(ma, mb) is True


def test_renamed_observable_model_bngir_v02_round_trip_and_native_execution():
    src = """
begin model
begin parameters
    k 0.5
end parameters
begin molecule types
    A(x~u~p)
    B()
end molecule types
begin seed species
    A(x~u) 10
end seed species
begin observables
    Molecules unphos A(x~u)
    Molecules phos   A(x~p)
end observables
begin reaction rules
    A(x~u) -> A(x~p) + B() k
end reaction rules
end model
"""
    orig = _model(src)
    doc_v02 = to_bngir(orig, version="0.2")
    restored = from_bngir(doc_v02)
    assert semantic_equal(orig, restored, version="0.2") is True

    # Native simulation of restored model produces matching observable trajectories
    res_orig = orig.simulate(method="ode", t_end=2.0, n_steps=10)
    res_restored = restored.simulate(method="ode", t_end=2.0, n_steps=10)
    for obs_name in ("unphos", "phos"):
        assert obs_name in dict(res_orig.observables)
        assert obs_name in dict(res_restored.observables)
        diff = max(
            abs(a - b)
            for a, b in zip(
                dict(res_orig.observables)[obs_name],
                dict(res_restored.observables)[obs_name],
            )
        )
        assert diff < 1e-10
