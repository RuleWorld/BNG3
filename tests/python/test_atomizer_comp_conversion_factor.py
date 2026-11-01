"""Execute SBML comp replacement conversion factors against an analytic law."""

from __future__ import annotations

import math

import libsbml

import bionetgen
from bionetgen.atomizer.modern import Atomizer

_COMPOSED_MODEL = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
    xmlns:comp="http://www.sbml.org/sbml/level3/version1/comp/version1"
    level="3" version="2" comp:required="true">
  <model id="root">
    <listOfParameters>
      <parameter id="k_host" value="0.2" constant="true">
        <comp:listOfReplacedElements>
          <comp:replacedElement comp:submodelRef="child" comp:idRef="k"
                                comp:conversionFactor="cf"/>
        </comp:listOfReplacedElements>
      </parameter>
      <parameter id="cf" value="2" constant="true"/>
    </listOfParameters>
    <comp:listOfSubmodels>
      <comp:submodel comp:id="child" comp:modelRef="component"/>
    </comp:listOfSubmodels>
  </model>
  <comp:listOfModelDefinitions>
    <comp:modelDefinition id="component">
      <listOfCompartments>
        <compartment id="c" size="1" constant="true"/>
      </listOfCompartments>
      <listOfSpecies>
        <species id="A" compartment="c" initialAmount="10"
                 hasOnlySubstanceUnits="true" boundaryCondition="false"
                 constant="false"/>
        <species id="B" compartment="c" initialAmount="0"
                 hasOnlySubstanceUnits="true" boundaryCondition="false"
                 constant="false"/>
      </listOfSpecies>
      <listOfParameters>
        <parameter id="k" value="0.1" constant="true"/>
      </listOfParameters>
      <listOfReactions>
        <reaction id="decay" reversible="false">
          <listOfReactants>
            <speciesReference species="A" stoichiometry="1" constant="true"/>
          </listOfReactants>
          <listOfProducts>
            <speciesReference species="B" stoichiometry="1" constant="true"/>
          </listOfProducts>
          <kineticLaw>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci>k</ci><ci>A</ci></apply>
            </math>
          </kineticLaw>
        </reaction>
      </listOfReactions>
    </comp:modelDefinition>
  </comp:listOfModelDefinitions>
</sbml>"""


def test_comp_parameter_replacement_conversion_factor_executes_exactly(tmp_path):
    source_document = libsbml.readSBMLFromString(_COMPOSED_MODEL)
    source_errors = [
        source_document.getError(index).getMessage()
        for index in range(source_document.getNumErrors())
        if source_document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not source_errors, source_errors

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=1, n_steps=10).atomize(
        _COMPOSED_MODEL
    )
    assert atomized.success, atomized.error
    assert "k_host / cf" in atomized.bngl

    model_path = tmp_path / "comp_replacement.bngl"
    model_path.write_text(atomized.bngl, encoding="utf-8")
    result = bionetgen.run(str(model_path), "ode", 1.0, 10)

    amounts_a = result.observables["child__A_amt"]
    amounts_b = result.observables["child__B_amt"]
    assert len(amounts_a) == len(amounts_b) == 11
    # comp:conversionFactor defines one unit of the replaced value times cf
    # as one unit of the replacement value: k_child = k_host / cf = 0.1.
    # Thus dA/dt = -0.1 A and dB/dt = +0.1 A.
    for index, (amount_a, amount_b) in enumerate(zip(amounts_a, amounts_b)):
        time = index / 10
        expected_a = 10 * math.exp(-0.1 * time)
        assert math.isclose(float(amount_a), expected_a, rel_tol=2e-6, abs_tol=1e-8)
        assert math.isclose(
            float(amount_b), 10 - expected_a, rel_tol=2e-6, abs_tol=1e-8
        )
