"""Regression for #162: atomized name-derived complexes must stay connected.

A species name such as ``B.C`` is inferred as a two-molecule complex in the
atomized translation.  Without a bond, network generation splits its product
into fragments and rejects a rule that also deletes a molecule, so the source
reaction silently disappears.  The identity markers added for #162 keep the
source species exact; connecting the inferred molecules keeps the rule
executable without changing its stoichiometry or rate law.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from atomizer_structural_harness import (  # noqa: E402
    _reaction_xml,
    _translate,
    build_sbml,
    compare_flat_and_atomized,
)


def _deleting_complex_model() -> str:
    """``A + BC -> B'C`` with ``BC`` and ``B'C`` named as ``B.C``."""

    return build_sbml(
        "atomized_unbound_complex_deletion",
        [
            ("a", "A", 1.0, None),
            ("bc", "B.C", 1.0, None),
            ("bcp", "B.C", 0.0, None),
        ],
        [_reaction_xml("convert", ["a", "bc"], ["bcp"], "k")],
        [("k", 1.0)],
    )


def test_atomized_unbound_complex_product_generates_the_source_reaction():
    report = compare_flat_and_atomized(
        _deleting_complex_model(), t_end=2.0, n_steps=5
    )

    assert report["flat_success"], report["flat_error"]
    assert report["atomized_success"], report["atomized_error"]
    assert report["flat_species"] == report["atomized_species"] == 3
    assert report["flat_reactions"] == report["atomized_reactions"] == 1
    assert report["flat_rules"] == report["atomized_rules"] == 1
    assert report["equivalent"], report


def test_atomized_complex_is_connected_with_exact_identity_markers():
    result = _translate(_deleting_complex_model(), atomize=True)

    assert result.success, result.error
    assert "__link1!1" in result.bngl
    assert "__sp~bc" in result.bngl
    assert "__sp~bcp" in result.bngl
    for species_id in ("bc", "bcp"):
        sites = result.structural_inference["species"][species_id]["sites"]
        bonds = result.structural_inference["species"][species_id]["bonds"]
        assert "__link" not in "".join(sites)
        assert "__link" not in "".join("".join(bond) for bond in bonds)


def test_flat_translation_is_unchanged():
    result = _translate(_deleting_complex_model(), atomize=False)

    assert result.success, result.error
    assert "__link" not in result.bngl
    assert "__sp" not in result.bngl


def test_without_species_identity_marker_reproduces_missing_reaction(monkeypatch):
    """Negative control: an unbound complex product loses the source reaction."""

    import bionetgen.atomizer.modern.core as core

    monkeypatch.setattr(core, "_connect_unbound_molecules", lambda structure: None)
    report = compare_flat_and_atomized(
        _deleting_complex_model(), t_end=2.0, n_steps=5
    )

    assert report["flat_success"], report["flat_error"]
    assert report["atomized_success"], report["atomized_error"]
    assert report["flat_reactions"] == 1
    assert report["atomized_reactions"] == 0
    assert not report["equivalent"]
    assert any("reaction count differs" in problem for problem in report["problems"])


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
