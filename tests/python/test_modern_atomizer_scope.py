"""Focused regressions for the Atomizer's import diagnostics and scope refusals.

Two product properties are pinned here.

* Every import diagnostic records the unsupported-construct class it belongs
  to, so a refusal is never an unnamed one (BNG3 issue #160).
* A reaction whose kinetic law references another reaction's local parameter
  is refused by name instead of emitting a rule with an undeclared symbol in
  its rate law.  The emitted model used to carry that symbol into the rule,
  which left the generated model unable to compile.
"""

from __future__ import annotations

import pytest

from bionetgen.atomizer.modern import Atomizer, SBMLParser
from bionetgen.atomizer.modern.types import (
    SUPPORT_GROUPS,
    SBMLImportWarning,
    diagnostic_group,
)

_HEAD = """<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="scope_model">
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true"/>
      <species id="B" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.5" constant="true"/>
    </listOfParameters>
{body}
  </model>
</sbml>
"""

_LOCAL_PARAMETER_REACTION = """    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>lr</ci></math>
          <listOfParameters>
            <parameter id="lr" value="2" constant="true"/>
          </listOfParameters>
        </kineticLaw>
      </reaction>
      <reaction id="R2" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>lr</ci></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
"""


def _atomize(body):
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(_HEAD.format(body=body))
    assert result.success, result.error
    return atomizer, result


def test_every_import_diagnostic_records_an_unsupported_construct_class():
    atomizer, _ = _atomize("""    <listOfReactions>
      <reaction id="R1" reversible="false" fast="true">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
""")

    warnings = atomizer.get_model().import_warnings
    assert warnings
    for warning in warnings:
        assert warning.get("group"), warning
        assert warning.get("group") != "other", warning


def test_the_fast_reaction_diagnostic_records_its_construct_class():
    atomizer, _ = _atomize("""    <listOfReactions>
      <reaction id="R1" reversible="false" fast="true">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
""")

    warning = next(
        record
        for record in atomizer.get_model().import_warnings
        if record["category"] == "fastReaction"
    )
    assert warning["group"] == "fast-reactions"
    assert warning["group"] in SUPPORT_GROUPS


def test_a_diagnostic_without_a_category_still_records_a_class():
    warning = SBMLImportWarning(
        category="brandNewConstruct", message="m", count=1, severity="dropped"
    )

    assert warning.get("group") == "other"
    assert diagnostic_group("brandNewConstruct") == "other"
    assert diagnostic_group("package:fbc") == "packages"


def test_a_reaction_using_another_reaction_local_parameter_is_refused_by_name():
    atomizer, result = _atomize(_LOCAL_PARAMETER_REACTION)

    warning = next(
        record
        for record in atomizer.get_model().import_warnings
        if record["category"] == "scope"
    )
    assert '"R2"' in warning["message"]
    assert '"lr"' in warning["message"]
    assert '"R1"' in warning["message"]
    assert warning["group"] == "symbol-scope"
    # The reaction that cannot be represented is not emitted at all: the
    # generated rule would carry a symbol that no BNGL scope declares.
    assert "R1:" in result.bngl
    assert "R2:" not in result.bngl


def test_the_emitted_model_of_a_refused_scope_still_compiles(tmp_path):
    import bionetgen

    atomizer, result = _atomize(_LOCAL_PARAMETER_REACTION)

    source = tmp_path / "emitted.bngl"
    source.write_text(result.bngl, encoding="utf-8")

    model = bionetgen.load(str(source))
    network = model.generate_network()

    assert network.num_reactions >= 1


def test_the_parser_records_the_class_of_every_warning_it_emits():
    model = SBMLParser().parse(_HEAD.format(body="""    <listOfRules>
      <algebraicRule>
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0</cn></math>
      </algebraicRule>
    </listOfRules>
"""))

    algebraic = next(
        record
        for record in model.import_warnings
        if record["category"] == "algebraicRule"
    )
    assert algebraic["group"] == "algebraic-constraints"
    assert algebraic["group"] in SUPPORT_GROUPS


@pytest.mark.parametrize(
    ("category", "group"),
    [
        ("algebraicRule", "algebraic-constraints"),
        ("constraint", "algebraic-constraints"),
        ("event", "events"),
        ("fastReaction", "fast-reactions"),
        ("speciesAssignmentRule", "dynamic-rules"),
        ("stoichiometry", "stoichiometry"),
        ("package:fbc", "packages"),
        ("delay", "history"),
    ],
)
def test_every_named_construct_class_is_reachable_from_its_category(category, group):
    assert diagnostic_group(category) == group
    assert group in SUPPORT_GROUPS
