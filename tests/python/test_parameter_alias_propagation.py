"""Parameter alias maps must be applied as one simultaneous rewrite.

A raw SBML id can be another raw id's standardized form: ``k-1`` and ``k_1``
both standardize to ``k_1``.  The alias map therefore holds ``k-1 -> k_1``
(the first parameter's canonical id) and ``k_1 -> k_1_2`` (the second's).  The
canonical id of the first is an alias *key* of the second, so an alias map is
a lookup from source spellings to canonical ids and not a chain of renames.
Resolving a token once and never re-examining the replacement is what keeps
each raw id pointing at the parameter it was declared for.
"""

import re

import pytest

from bionetgen.atomizer.modern import SBMLParser, sbml_to_bngl

_CORE_NS = "http://www.sbml.org/sbml/level3/version1/core"
_MATH_NS = "http://www.w3.org/1998/Math/MathML"

_COLLIDING_IDS = ("k-1", "k_1")
_COLLIDING_VALUES = ("1", "7")


def _model(parameter_ids, reaction_refs, local=False):
    """A two-reaction model whose rate laws reference ``reaction_refs``."""

    if local:
        locals_xml = "\n".join(
            f'<localParameter id="{pid}" value="{value}"/>'
            for pid, value in zip(parameter_ids, _COLLIDING_VALUES)
        )
        law_inner = f"<listOfLocalParameters>{locals_xml}</listOfLocalParameters>"
    else:
        parameters_xml = "\n".join(
            f'<parameter id="{pid}" value="{value}" constant="true"/>'
            for pid, value in zip(parameter_ids, _COLLIDING_VALUES)
        )
        law_inner = ""
    reactions_xml = "\n".join(f"""<reaction id="{ref_index}" reversible="false">
              <listOfReactants>
                <speciesReference species="{ref_index}" stoichiometry="1" constant="true"/>
              </listOfReactants>
              <kineticLaw>
                <math xmlns="{_MATH_NS}">
                  <apply><times/><ci>{ref}</ci><ci>{ref_index}</ci></apply>
                </math>
                {law_inner}
              </kineticLaw>
            </reaction>""" for ref_index, ref in zip(("R0", "R1"), reaction_refs))
    species_xml = "\n".join(
        f"""<species id="{sid}" compartment="c" initialConcentration="1"
              hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>"""
        for sid in ("R0", "R1")
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <sbml xmlns="{_CORE_NS}" level="3" version="1">
      <model id="alias_collision">
        <listOfCompartments>
          <compartment id="c" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>{species_xml}</listOfSpecies>
        <listOfParameters>{"" if local else parameters_xml}</listOfParameters>
        <listOfReactions>{reactions_xml}</listOfReactions>
      </model>
    </sbml>
    """


def _rates(sbml):
    bngl = sbml_to_bngl(sbml).bngl
    return dict(re.findall(r"^\s*(R\d+):.*?->\s*0\s+(\S+)\s*$", bngl, re.MULTILINE))


def test_colliding_global_parameter_ids_keep_their_own_rate():
    """``k-1`` must not be retargeted onto the canonical id of ``k_1``."""

    rates = _rates(_model(_COLLIDING_IDS, _COLLIDING_IDS))
    assert rates == {"R0": "1", "R1": "7"}


def test_colliding_global_parameter_ids_resolve_through_the_parsed_model():
    """Each raw id reaches the canonical id of the parameter it declared."""

    model = SBMLParser().parse(_model(_COLLIDING_IDS, _COLLIDING_IDS))
    assert list(model.parameters) == ["k_1", "k_1_2"]
    assert model.reactions["R0"].kinetic_law.math == "k_1 * R0"
    assert model.reactions["R1"].kinetic_law.math == "k_1_2 * R1"


def test_non_colliding_parameter_ids_are_unaffected():
    """No collision means no remap, so the rates must be exactly the values."""

    rates = _rates(_model(("k-1", "k_2"), ("k-1", "k_2")))
    assert rates == {"R0": "1", "R1": "7"}


def test_colliding_local_parameter_ids_keep_their_own_rate():
    """The reaction-local list needs the same exact-id-wins repair."""

    rates = _rates(_model(_COLLIDING_IDS, _COLLIDING_IDS, local=True))
    assert rates == {"R0": "1", "R1": "7"}


def test_colliding_local_parameter_ids_resolve_through_the_parsed_model():
    model = SBMLParser().parse(_model(_COLLIDING_IDS, _COLLIDING_IDS, local=True))
    assert model.reactions["R0"].kinetic_law.math == "k_1 * R0"
    assert model.reactions["R1"].kinetic_law.math == "k_1_2 * R1"


def test_non_colliding_local_parameter_ids_are_unaffected():
    rates = _rates(_model(("k-1", "k_2"), ("k-1", "k_2"), local=True))
    assert rates == {"R0": "1", "R1": "7"}


@pytest.mark.parametrize(
    "formula, expected",
    [
        # A replacement is an output of the map, never a new lookup key.
        ("k-1*A", "k_1*A"),
        ("k_1*A", "k_1_2*A"),
        ("k-1*k_1", "k_1*k_1_2"),
        # Longest alias first: a shorter alias must not eat a longer token.
        ("k_1_2*A", "k_1_2*A"),
        ("k_1_20*A", "k_1_20*A"),
        # Identifiers are never split.
        ("xk-1", "xk-1"),
        ("k-1x", "k-1x"),
    ],
)
def test_normalize_formula_identifiers_resolves_each_token_once(formula, expected):
    aliases = {"k-1": "k_1", "k_1": "k_1_2", "k_1_2": "k_1_2"}
    assert SBMLParser._normalize_formula_identifiers(formula, aliases) == expected
