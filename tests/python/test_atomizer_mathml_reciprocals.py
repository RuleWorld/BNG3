"""Regression tests for MathML trigonometric reciprocals and numeric fidelity.

MathML defines ``sec``, ``csc``, ``cot``, ``arcsec``, ``arccsc``, ``arccot``,
``arcsech`` and ``arccsch``.  None of them has a BNGL builtin, but each has
an exact rewrite onto the builtins BNGL does define, so a model that uses one
is representable and must not be reported as unsupported.

The rewrites have to be *exact*, and the numbers the Atomizer emits have to
round-trip: an emitted value that is rounded more coarsely than the literal
it is compared against turns a true equality into a false one.  The official
SBML Test Suite case ``semantic/00958`` checks that: ``P7`` is
``piecewise(2, eq(P1, pi), 3)`` with ``P1`` assigned ``pi``, so the equality
must hold.
"""

from __future__ import annotations

import math

import pytest

from bionetgen.atomizer.modern import Atomizer
from bionetgen.atomizer.modern.writer import _number, convert_math_expression


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("sec(x)", "(1/cos(x))"),
        ("csc(x)", "(1/sin(x))"),
        ("cot(x)", "(cos(x)/sin(x))"),
        ("arcsec(x)", "acos(1/(x))"),
        ("arccsc(x)", "asin(1/(x))"),
        ("arccot(x)", "atan(1/(x))"),
        ("arcsech(x)", "acosh(1/(x))"),
        ("arccsch(x)", "asinh(1/(x))"),
    ],
)
def test_trigonometric_reciprocals_lower_onto_bngl_builtins(expression, expected):
    assert convert_math_expression(expression) == expected


def test_trigonometric_reciprocals_are_not_reported_as_unsupported():
    """A reciprocal has an exact BNGL rewrite, so it is representable."""

    sbml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="reciprocals">
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k" value="1" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1"/>
            </listOfReactants>
            <listOfProducts/>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/>
                  <ci>k</ci>
                  <apply><sec/><cn>0.5</cn></apply>
                </apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""

    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(sbml)
    assert result.success, result.error
    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning["category"] == "mathml"
    ], atomizer.model.import_warnings


@pytest.mark.parametrize(
    "value",
    [
        math.pi,
        math.e,
        1.0 / 3.0,
        2.0 / 3.0,
        0.1,
        6.02214179e23,
        1.2345678901234567e-7,
    ],
)
def test_emitted_numbers_round_trip_exactly(value):
    """An emitted literal has to denote the same double it came from."""

    text = _number(value)
    assert float(text) == value


def test_a_parameter_and_the_literal_it_is_compared_with_agree():
    """The official reference of semantic/00958.

    ``P1`` is assigned ``pi`` and ``P7`` is ``piecewise(2, eq(P1, pi), 3)``,
    so the equality must hold.  It only holds when the emitted parameter
    value denotes exactly the same double as the expression literal.
    """

    sbml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="pi_equality">
        <listOfParameters>
          <parameter id="P1" value="3.141592653589793" constant="true"/>
        </listOfParameters>
        <listOfRules>
          <assignmentRule variable="P7">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <piecewise>
                <piece>
                  <cn type="integer"> 2 </cn>
                  <apply><eq/><ci> P1 </ci><pi/></apply>
                </piece>
                <otherwise><cn type="integer"> 3 </cn></otherwise>
              </piecewise>
            </math>
          </assignmentRule>
        </listOfRules>
      </model>
    </sbml>"""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert result.success, result.error
    assert "P1 3.141592653589793" in result.bngl
