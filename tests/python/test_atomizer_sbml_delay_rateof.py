"""Regression tests for the SBML ``delay`` and ``rateOf`` csymbols.

SBML Level 2 Version 4 and Level 3 Version 2 Core Sec. 3.4.6 define ``delay(x, d)`` as the value
of ``x`` at time ``t - d`` and defines ``rateOf(x)`` as the
instantaneous derivative of ``x``.  Both are MathML ``<csymbol>`` operators,
not MathML operator elements, and libSBML 5.21.1 serializes them in exactly
that form.

Three boundaries matter here:

* the C++ SBML writer must emit the canonical csymbol form, so a document
  that carries a delay or a rateOf stays valid SBML;
* the modern Atomizer must fold a delay away whenever the delayed history is
  exactly reproducible, and must not report such a model as unsupported;
* a delay whose history cannot be reproduced must stay explicitly
  unsupported, because neither the BNG3 engine nor libRoadRunner can
  evaluate SBML delay semantics.
"""

from __future__ import annotations

import pytest

from bionetgen.atomizer.modern import Atomizer

_cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
libsbml = pytest.importorskip("libsbml")


_DELAY_MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="delayed">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="x" compartment="C" hasOnlySubstanceUnits="false"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="y" constant="false"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="x">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <sin/>
            <apply>
              <times/>
              <cn type="integer">10</cn>
              <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol>
            </apply>
          </apply>
        </math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfRules>
      <assignmentRule variable="y">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <plus/>
            <cn type="integer">2</cn>
            <apply>
              <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay"> delay </csymbol>
              <ci> x </ci>
              <cn>0.2</cn>
            </apply>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="J0" reversible="false">
        <listOfProducts>
          <speciesReference species="x" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn type="integer">1</cn></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""


_UNFOLDABLE_DELAY_MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="unfoldable">
    <listOfParameters>
      <parameter id="z" constant="false"/>
      <parameter id="x" value="0" constant="false"/>
      <parameter id="y" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="z">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay"> delay </csymbol>
            <ci> x </ci>
            <cn type="integer">1</cn>
          </apply>
        </math>
      </assignmentRule>
      <rateRule variable="x">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn type="integer">1</cn></math>
      </rateRule>
      <assignmentRule variable="y">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay"> delay </csymbol>
            <ci> x </ci>
            <ci> z </ci>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>
"""


_RATE_OF_LOCAL_PARAMETER_MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="local_rate_of">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="1" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="k1">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn type="integer">2</cn></math>
      </rateRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="J0" reversible="true">
        <listOfProducts>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf"> rateOf </csymbol>
              <ci> k1 </ci>
            </apply>
          </math>
          <listOfLocalParameters>
            <localParameter id="k1" value="3"/>
          </listOfLocalParameters>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""


def _warnings(atomizer) -> list[str]:
    return [
        str(warning.get("message", "")) for warning in atomizer.model.import_warnings
    ]


def test_cpp_writer_emits_the_libsbml_canonical_delay_and_rateof_csymbol(tmp_path):
    """The C++ writer must emit the csymbol form libSBML accepts."""

    base = """
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 2
end seed species
begin reaction rules
  J0: A() -> 0 1
end reaction rules
end model
"""
    model = _cpp.parse_string(base)
    network = _cpp.generate_network(model, max_iter=100)

    extended = base.replace(
        "begin reaction rules",
        "begin functions\n"
        "  y() = delay(k, 1)\n"
        "  z() = rateOf(k)\n"
        "end functions\n"
        "begin reaction rules",
    )
    extended_model = _cpp.parse_string(extended)
    output = tmp_path / "delay.xml"
    _cpp.io.write_sbml(extended_model, network, str(output))
    text = output.read_text(encoding="utf-8")

    assert (
        '<csymbol encoding="text" '
        'definitionURL="http://www.sbml.org/sbml/symbols/delay"> delay </csymbol>'
    ) in text
    assert (
        '<csymbol encoding="text" '
        'definitionURL="http://www.sbml.org/sbml/symbols/rateOf"> rateOf </csymbol>'
    ) in text
    # MathML has no delay/rateOf operator elements.
    assert "<delay/>" not in text
    assert "<rateOf/>" not in text

    document = libsbml.readSBMLFromString(text)
    assert document.getNumErrors() == 0, [str(e) for e in document.getErrors()]

    model = document.getModel()
    rules = model.getListOfRules()
    operators = {rules.get(i).getMath().getType() for i in range(rules.size())}
    assert libsbml.AST_FUNCTION_DELAY in operators
    assert libsbml.AST_FUNCTION_RATE_OF in operators


def test_delayed_reaction_sbml_has_valid_split_gated_and_zero_delay_forms(tmp_path):
    def export(rule: str, filename: str, start_time: float = 0.0, level: int = 3):
        source = f"""
begin model
begin parameters
  k 0.5
  tau 2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  {rule}
end reaction rules
end model
"""
        model = _cpp.parse_string(source)
        network = _cpp.generate_network(model, max_iter=100)
        destination = tmp_path / filename
        _cpp.io.write_sbml(
            model, network, str(destination), start_time=start_time, level=level
        )
        document = libsbml.readSBML(str(destination))
        assert document.getNumErrors() == 0, [
            str(error) for error in document.getErrors()
        ]
        document.checkConsistency()
        errors = [
            document.getError(i).getMessage()
            for i in range(document.getNumErrors())
            if document.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
        ]
        assert not errors, errors
        return document.getModel()

    def delay_nodes(node):
        if node.getType() == libsbml.AST_FUNCTION_DELAY:
            yield node
        for index in range(node.getNumChildren()):
            yield from delay_nodes(node.getChild(index))

    consuming = export("A() + A() -> B() k delay=tau", "consuming.xml", 5.0)
    assert consuming.getNumReactions() == 2
    initiation = consuming.getReaction(0)
    completion = consuming.getReaction(1)
    assert initiation.getNumReactants() == 1
    assert initiation.getReactant(0).getStoichiometry() == 2
    assert initiation.getNumProducts() == 0
    assert completion.getNumReactants() == 0
    assert completion.getNumProducts() == 1
    assert completion.getNumModifiers() == 1
    assert (
        completion.getModifier(0).getSpecies() == initiation.getReactant(0).getSpecies()
    )
    initiation_formula = libsbml.formulaToL3String(initiation.getKineticLaw().getMath())
    assert "0.5" in initiation_formula, initiation_formula
    completion_delays = list(delay_nodes(completion.getKineticLaw().getMath()))
    assert len(completion_delays) == 1
    assert (
        libsbml.formulaToL3String(completion_delays[0].getChild(0))
        == initiation_formula
    )
    assert "5" in libsbml.formulaToL3String(completion.getKineticLaw().getMath())

    non_consuming = export(
        "A() -> A() + B() 0.5 delay=tau NonConsuming", "nonconsuming.xml"
    )
    assert non_consuming.getNumReactions() == 1
    delayed = non_consuming.getReaction(0)
    assert delayed.getNumReactants() == 1
    assert delayed.getNumProducts() == 2
    assert len(list(delay_nodes(delayed.getKineticLaw().getMath()))) == 1

    zero_delay = export("A() -> B() k delay=0", "zero.xml")
    assert zero_delay.getNumReactions() == 1
    assert zero_delay.getReaction(0).getNumReactants() == 1
    assert zero_delay.getReaction(0).getNumProducts() == 1
    assert not list(delay_nodes(zero_delay.getReaction(0).getKineticLaw().getMath()))

    source = export("0 -> B() k delay=tau", "source.xml")
    assert source.getNumReactions() == 1
    assert source.getReaction(0).getNumReactants() == 0
    assert source.getReaction(0).getNumProducts() == 1
    assert source.getReaction(0).getId() == "R1_complete"

    sink = export("A() -> 0 k delay=tau", "sink.xml")
    assert sink.getNumReactions() == 1
    assert sink.getReaction(0).getNumReactants() == 1
    assert sink.getReaction(0).getNumProducts() == 0
    assert sink.getReaction(0).getId() == "R1_init"

    level2 = export("A() -> B() k delay=tau", "level2.xml", level=2)
    assert level2.getLevel() == 2
    assert level2.getNumReactions() == 2
    assert len(list(delay_nodes(level2.getReaction(1).getKineticLaw().getMath()))) == 1


def test_delay_with_a_reproducible_history_is_not_reported_as_unsupported():
    """An exactly foldable delay must not be refused."""

    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(_DELAY_MODEL)
    assert result.success, result.error

    messages = _warnings(atomizer)
    assert not [
        message
        for message in messages
        if "not losslessly representable" in message and "delay" in message
    ]
    assert "delay(" not in result.bngl

    # SBML keeps an initialAssignment in effect before t = 0, so the delayed
    # value of x at time t - 0.2 is sin(10 * (t - 0.2)), not x's value at t = 0.
    assert "sin((10 * (time() - 0.2)))" in result.bngl


def test_delay_without_a_reproducible_history_stays_unsupported():
    """A delay whose history is not reproducible must stay refused."""

    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(_UNFOLDABLE_DELAY_MODEL)
    assert result.success, result.error

    messages = [
        message
        for message in _warnings(atomizer)
        if "not losslessly representable" in message and "delay" in message
    ]
    assert messages, _warnings(atomizer)
    assert "libRoadRunner" in messages[0]


def test_rate_of_a_reaction_local_parameter_is_zero():
    """A reaction-local parameter shadows the global parameter of that name.

    SBML Level 3 Version 2 Core Sec. 3.4.6: the ``rateOf`` of a symbol
    declared constant is zero, and ``LocalParameter`` objects are always
    constant.  The global ``k1`` rate rule must therefore not be used.
    """

    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        _RATE_OF_LOCAL_PARAMETER_MODEL
    )
    assert result.success, result.error

    reaction_rules = result.bngl.split("begin reaction rules", 1)[1]
    j0 = [
        line for line in reaction_rules.splitlines() if line.strip().startswith("J0:")
    ]
    assert j0, result.bngl
    # The reaction flux is the zero rate of the local parameter, not the
    # global rate rule value 2.
    assert j0[0].rstrip().endswith("0 TotalRate"), j0[0]
