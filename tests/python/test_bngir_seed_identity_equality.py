"""Exact equality must use native seed identity, not source bond spellings.

Pinned BNG2 9601746f independently accepts both dimer sources and writes the
same canonical species A(b!1).A(b!1) with populations 10 and 20. The initial
molecule observable is necessarily 20 vs 40, so the two models are not equal.
The prior string-matching extractor left both seeds unmatched (zero) and
certified them equal.
"""

import pytest

import bionetgen
from bionetgen.model import _cpp


def _dimer(bond: int, count: int):
    source = f"""begin model
begin molecule types
 A(b)
end molecule types
begin seed species
 A(b!{bond}).A(b!{bond}) {count}
end seed species
begin observables
 Molecules total A()
end observables
begin reaction rules
 A(b!1).A(b!1) -> 0 1
end reaction rules
end model
"""
    return bionetgen.BioNetGenModel(_cpp.parse_string(source))


def test_renamed_bonds_same_count_are_equal():
    assert bionetgen.semantic_equal(_dimer(2, 10), _dimer(3, 10)) is True


def test_renamed_bonds_different_counts_are_not_equal():
    assert bionetgen.semantic_equal(_dimer(2, 10), _dimer(3, 20)) is False


def _compartmented(bond: int, count: int, left_compartment: str):
    source = f"""begin model
begin compartments
 c1 3 1
 c2 3 1
end compartments
begin molecule types
 A(b~on~off)
end molecule types
begin seed species
 @{left_compartment}:A(b~on!{bond}).A(b~off!{bond}) {count}
end seed species
end model
"""
    return bionetgen.BioNetGenModel(_cpp.parse_string(source))


def test_compartmented_renamed_bonds_different_counts_are_not_equal():
    left = _compartmented(2, 10, "c1")
    right = _compartmented(3, 20, "c1")
    assert bionetgen.semantic_equal(left, right) is False


def test_compartmented_renamed_bonds_different_compartments_stay_undecided():
    # Distinct compartments are not silently equated; the current certificate
    # family declines rather than issuing a false equality proof.
    from bionetgen.bngir import EqualityUndecided

    left = _compartmented(2, 10, "c1")
    right = _compartmented(3, 10, "c2")
    with pytest.raises(EqualityUndecided):
        bionetgen.semantic_equal(left, right)
