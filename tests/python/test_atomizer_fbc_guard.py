"""Regression test for the FBC guard in the deterministic flux lowering.

An SBML model that carries the ``fbc`` package is a constraint-based
flux-balance model, not a kinetic time-course model, so the Atomizer does not
import it.  The parser names that diagnostic ``package:fbc``, and the
writer's guards have to recognise the same name: a guard written against the
bare package name never fires, and a reaction whose stoichiometry a BNGL
pattern cannot spell is then lowered deterministically although the model
never had the semantics for it.
"""

from __future__ import annotations

from bionetgen.atomizer.modern import Atomizer

_FBC_MODEL = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
    xmlns:fbc="http://www.sbml.org/sbml/level3/version1/fbc/version1">
  <model id="fbc_fractional_stoichiometry">
    <listOfCompartments>
      <compartment id="C" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="1"
               hasOnlySubstanceUnits="true" constant="false"/>
      <species id="S2" compartment="C" initialAmount="0"
               hasOnlySubstanceUnits="true" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J0" reversible="false">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="0.4" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="S2" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn> 0.5 </cn></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <fbc:listOfFluxBounds>
      <fbc:fluxBound operation="lessEqual" value="10" reaction="J0"/>
    </fbc:listOfFluxBounds>
  </model>
</sbml>"""


def _atomize():
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(_FBC_MODEL)
    assert result.success, result.error
    return atomizer, result


def test_the_package_diagnostic_is_named_package_fbc():
    """The parser's package diagnostic carries the package name."""

    atomizer, _result = _atomize()

    categories = {str(warning.category) for warning in atomizer.model.import_warnings}
    assert "package:fbc" in categories
    assert "fbc" not in categories


def test_the_fbc_guard_omits_a_reaction_the_flux_lowering_cannot_spell():
    """The FBC guard has to fire for a reaction with a fractional stoichiometry."""

    atomizer, result = _atomize()

    # The deterministic flux lowering would emit a species-specific rule for
    # the reaction; the FBC guard has to keep it out of the model.
    assert "J0_consume_S1:" not in result.bngl
    assert "J0_produce_S2:" not in result.bngl

    messages = [
        warning.message
        for warning in atomizer.model.import_warnings
        if warning.category == "stoichiometry"
    ]
    assert any("FBC semantics" in message for message in messages), messages
