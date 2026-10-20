"""Regression tests for compartment references in SBML rules.

A compartment whose size is set by an ``initialAssignment`` does not have a
constant size: SBML Level 3 Version 2 Core (Sec. 4.8) lets an initial
assignment override the compartment's ``size`` attribute, and the Atomizer
therefore emits the compartment's size as a BNGL function rather than as the
``__compartment_<id>__`` volume parameter.

A rule that names such a compartment must use that function.  Rewriting the
name to the volume parameter produced the invalid text
``__compartment_<id>__()``: a call to an undeclared function, which the BNG3
compiler rejects with an unresolved expression symbol.
"""

from __future__ import annotations

import re

from bionetgen.atomizer.modern import Atomizer

from _extdep import require_extension


_SBML = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="compartment_initial_assignment">
    <listOfCompartments>
      <compartment id="Outer" size="4" constant="true" spatialDimensions="3"/>
      <compartment id="Inner" size="1" constant="true" spatialDimensions="3"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="Inner" initialAmount="2"
               hasOnlySubstanceUnits="true" constant="false"/>
      <species id="B" compartment="Inner" initialAmount="0"
               hasOnlySubstanceUnits="true" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="MW" value="2" constant="true"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="Inner">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>0.25</cn><ci>Outer</ci></apply>
        </math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfRules>
      <assignmentRule variable="A">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <times/>
            <apply>
              <divide/>
              <ci>B</ci>
              <ci>Inner</ci>
            </apply>
            <ci>MW</ci>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>"""


def _rule_body(bngl: str, name: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(name)}\(\)\s*=\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(bngl)
    assert match is not None, f"rule {name} is missing from the generated model"
    return match.group(1)


def test_rule_referencing_a_compartment_with_an_initial_assignment_uses_its_function():
    """A rule-driven compartment must not become an invalid parameter call."""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(_SBML)

    assert result.success, result.error
    body = _rule_body(result.bngl, "A")
    assert "__compartment_Inner__()" not in body, body
    assert "Inner()" in body, body


def test_generated_model_with_a_compartment_initial_assignment_compiles():
    """The emitted model must not contain an unresolved expression symbol."""

    extension = require_extension()
    result = Atomizer(atomize=False, quiet_mode=True).atomize(_SBML)

    assert result.success, result.error
    model = extension.parse_string(result.bngl)
    network = extension.generate_network(model, max_iter=100)
    assert network.num_species > 0
