"""Regression tests for reaction ids used as rates inside SBML rules.

SBML Level 3 Version 2 Core (Sec. 4.11.8) and the libSBML ``Reaction``
documentation state that a reaction's ``id`` may be used in mathematical
formulas elsewhere in the model to represent *the rate of that reaction*.
BioModels records use that form: an assignment or rate rule can name several
reactions and combine their rates.

Every such reference has to be replaced by the reaction's own rate
expression.  A reaction id that survives into the emitted BNGL is an
unresolved expression symbol, so the generated model does not compile.
"""

from __future__ import annotations

import re

import pytest

from bionetgen.atomizer.modern import Atomizer

from _extdep import require_extension


def _model(reaction_count: int) -> str:
    """Return an SBML model whose rule names every reaction id."""

    reactions = []
    for index in range(reaction_count):
        reactions.append(f"""
          <reaction id="rx{index}" reversible="false">
            <listOfReactants>
              <speciesReference species="S" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="P" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>k</ci><ci>S</ci></apply>
              </math>
            </kineticLaw>
          </reaction>""")
    references = " + ".join(f"<ci>rx{index}</ci>" for index in range(reaction_count))
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="reaction_rate_references">
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S" compartment="C" initialAmount="2"
                   hasOnlySubstanceUnits="true" constant="false"/>
          <species id="P" compartment="C" initialAmount="0"
                   hasOnlySubstanceUnits="true" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k" value="0.5" constant="true"/>
          <parameter id="total" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <assignmentRule variable="total">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><plus/>{references}</apply>
            </math>
          </assignmentRule>
        </listOfRules>
        <listOfReactions>{"".join(reactions)}
        </listOfReactions>
      </model>
    </sbml>"""


def _rule_body(bngl: str, name: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(name)}\(\)\s*=\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(bngl)
    assert match is not None, f"rule {name} is missing from the generated model"
    return match.group(1)


def test_every_reaction_id_in_a_rule_is_replaced_by_its_rate():
    """A rule naming more reactions than one pass must not leak an id."""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(_model(7))

    assert result.success, result.error
    body = _rule_body(result.bngl, "total")
    for index in range(7):
        assert not re.search(
            rf"\brx{index}\b", body
        ), f"reaction id rx{index} survived into the emitted rule: {body}"
    # The rate of each reaction is ``k * S``; the rule sums seven of them.
    assert body.count("0.5 * S_amt") == 7, body


def test_generated_model_with_reaction_rate_references_compiles():
    """The emitted model must not contain an unresolved expression symbol."""

    extension = require_extension()
    result = Atomizer(atomize=False, quiet_mode=True).atomize(_model(7))

    assert result.success, result.error
    model = extension.parse_string(result.bngl)
    network = extension.generate_network(model, max_iter=100)
    assert network.num_reactions > 0


@pytest.mark.parametrize("reaction_count", [1, 2, 4, 5, 9])
def test_reaction_rate_reference_count_is_independent(reaction_count: int):
    """The number of inlined reaction rates must not depend on the count."""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(_model(reaction_count))

    assert result.success, result.error
    body = _rule_body(result.bngl, "total")
    for index in range(reaction_count):
        assert not re.search(rf"\brx{index}\b", body), body
