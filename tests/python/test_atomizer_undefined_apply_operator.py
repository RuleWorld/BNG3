"""Regression tests for a MathML ``<apply>`` whose operator names no function.

MathML names the operator of an ``<apply>`` with its first child.  When that
child is a ``<ci>``, the operator is a function call, and SBML only defines
such a call for a declared ``<functionDefinition>`` (or for the factor laws
the writer supports).  A kinetic law whose operator is a parameter name is
not a rate expression: the model states no rate at all.

The Atomizer used to translate the call faithfully, which produced a rule
that called an undeclared function and therefore did not parse.  The parser
now reports the construct as an explicit loss, so the record is classified as
unsupported instead of producing a document that cannot be compiled.
"""

from __future__ import annotations

from bionetgen.atomizer.modern import Atomizer

_SBML = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="undefined_apply_operator">
    <listOfCompartments>
      <compartment id="C" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="1"
               hasOnlySubstanceUnits="true" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J0" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <ci>LOWER_BOUND</ci>
              <ci>FLUX_VALUE</ci>
            </apply>
          </math>
          <listOfParameters>
            <parameter id="LOWER_BOUND" value="-999999" constant="true"/>
            <parameter id="FLUX_VALUE" value="0.5" constant="true"/>
          </listOfParameters>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""


def _mathml_warnings(atomizer) -> list[str]:
    return [
        warning["message"]
        for warning in atomizer.model.import_warnings
        if warning["category"] == "mathml"
    ]


def test_undefined_apply_operator_is_reported_as_a_loss():
    """A kinetic law with no declared function must not pass silently."""

    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(_SBML)

    assert result.success, result.error
    warnings = _mathml_warnings(atomizer)
    assert warnings, "the undefined operator was not reported"
    assert any("LOWER_BOUND" in message for message in warnings), warnings
    assert all(
        warning["severity"] in {"dropped", "approximated"}
        for warning in atomizer.model.import_warnings
        if warning["category"] == "mathml"
    )


def test_declared_function_definitions_are_not_reported():
    """A ``<ci>`` operator that names a declared function is valid SBML."""

    sbml = _SBML.replace(
        """<apply>
              <ci>LOWER_BOUND</ci>
              <ci>FLUX_VALUE</ci>
            </apply>""",
        """<apply>
              <ci>rate_law</ci>
              <ci>FLUX_VALUE</ci>
            </apply>""",
    ).replace(
        "</model>",
        """<listOfFunctionDefinitions>
      <functionDefinition id="rate_law">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <lambda>
            <bvar><ci>x</ci></bvar>
            <apply><times/><ci>x</ci><cn>2</cn></apply>
          </lambda>
        </math>
      </functionDefinition>
    </listOfFunctionDefinitions>
  </model>""",
    )
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(sbml)

    assert result.success, result.error
    assert not _mathml_warnings(atomizer), _mathml_warnings(atomizer)
