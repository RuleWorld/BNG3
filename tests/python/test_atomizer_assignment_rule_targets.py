"""Regression tests for assignment rules whose target is a parameter.

SBML Level 3 Version 2 Core (Sec. 4.8) says that a species identifier in a
mathematical expression denotes the species' *amount* or *concentration*,
depending on its ``hasOnlySubstanceUnits`` attribute.  An assignment rule
whose target is a parameter therefore carries that quantity, and the Atomizer
has to report it exactly.

No BNGL observable can report a concentration: a ``Molecules`` observable
counts molecules, and a ``Species`` observable of a pattern reports the same
count.  The concentration is the amount divided by the compartment's current
size, which the Atomizer already exposes as the ``_c_<species>()`` helper.  A
rule whose value is a concentration is therefore lowered to a BNGL function
rather than to an observable.

The official SBML Test Suite cases ``semantic/00999``, ``01198``, ``01205``,
``01206``, ``01207``, ``01208``, ``01478`` and ``01796`` check exactly this,
and the SBML Test Suite case ``semantic/01207`` also checks that a reference
to a rate-ruled compartment uses the compartment's *current* size.
"""

from __future__ import annotations

import pytest

from bionetgen.atomizer.modern import Atomizer


def _model(species: str, rules: str) -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="assignment_target">
        <listOfCompartments>
          <compartment id="C" size="0.5" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>{species}</listOfSpecies>
        <listOfRules>{rules}</listOfRules>
      </model>
    </sbml>"""


def _bngl(species: str, rules: str) -> str:
    result = Atomizer(atomize=False, quiet_mode=True).atomize(_model(species, rules))
    assert result.success, result.error
    return result.bngl


def test_concentration_valued_operand_is_lowered_to_a_function():
    # ``x = S1`` with a concentration-valued S1 names the concentration, so
    # the rule has to be a function; no observable reports a concentration.
    bngl = _bngl(
        '<species id="S1" compartment="C" initialAmount="3" '
        'hasOnlySubstanceUnits="false" constant="false"/>',
        '<assignmentRule variable="x">'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><ci> S1 </ci></math>'
        "</assignmentRule>",
    )

    assert "x() = _c_S1()" in bngl
    assert "Molecules x " not in bngl
    assert "Species x " not in bngl


def test_amount_valued_operand_stays_an_observable():
    # An amount-valued species denotes the amount, which a ``Molecules``
    # observable reports exactly.
    bngl = _bngl(
        '<species id="S1" compartment="C" initialAmount="3" '
        'hasOnlySubstanceUnits="true" constant="false"/>',
        '<assignmentRule variable="x">'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><ci> S1 </ci></math>'
        "</assignmentRule>",
    )

    assert "Molecules x " in bngl
    assert "x() =" not in bngl


def test_rate_ruled_compartment_uses_its_current_size():
    # A compartment whose size is driven by a rule has no constant BNGL
    # volume parameter, so a reference to it must name the state that
    # carries the current size.
    bngl = _bngl(
        '<species id="S1" compartment="C" initialAmount="3" '
        'hasOnlySubstanceUnits="true" constant="false"/>',
        '<rateRule variable="C">'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn> 0.2 </cn></math>'
        "</rateRule>"
        '<assignmentRule variable="x">'
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<apply><divide/><ci> S1 </ci><ci> C </ci></apply>"
        "</math></assignmentRule>",
    )

    assert "x() = S1 / C_amt" in bngl
    assert "__compartment_C__" not in bngl.split("begin functions")[1]


def test_species_without_a_compartment_keeps_the_amount_reading():
    # A species with no compartment has no volume, so its symbol has no
    # concentration form and the amount is the only quantity it can denote.
    bngl = _bngl(
        '<species id="S1" initialAmount="3" constant="false"/>',
        '<assignmentRule variable="x">'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><ci> S1 </ci></math>'
        "</assignmentRule>",
    )

    assert "Molecules x " in bngl
    assert "x() =" not in bngl
