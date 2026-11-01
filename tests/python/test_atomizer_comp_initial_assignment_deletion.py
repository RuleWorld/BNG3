"""External SBML comp deletion of an InitialAssignment affects execution."""

from __future__ import annotations

import math

import libsbml

import bionetgen
from bionetgen.atomizer.modern import Atomizer


def _write_model(tmp_path):
    core = "http://www.sbml.org/sbml/level3/version2/core"
    comp = "http://www.sbml.org/sbml/level3/version1/comp/version1"
    mathml = "http://www.w3.org/1998/Math/MathML"
    child = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="{core}" level="3" version="2">
  <model id="component">
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
    <listOfInitialAssignments>
      <initialAssignment metaid="initial-rate" symbol="k">
        <math xmlns="{mathml}"><cn>0.2</cn></math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfReactions>
      <reaction id="decay" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="{mathml}">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    parent = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="{core}" xmlns:comp="{comp}" level="3" version="2"
      comp:required="true">
  <model id="root">
    <comp:listOfSubmodels>
      <comp:submodel comp:id="child" comp:modelRef="componentRef">
        <comp:listOfDeletions>
          <comp:deletion comp:metaIdRef="initial-rate"/>
        </comp:listOfDeletions>
      </comp:submodel>
    </comp:listOfSubmodels>
  </model>
  <comp:listOfExternalModelDefinitions>
    <comp:externalModelDefinition comp:id="componentRef"
        comp:source="component.xml" comp:modelRef="component"/>
  </comp:listOfExternalModelDefinitions>
</sbml>"""
    child_path = tmp_path / "component.xml"
    child_path.write_text(child, encoding="utf-8")
    parent_path = tmp_path / "parent.xml"
    parent_path.write_text(parent, encoding="utf-8")
    return parent, parent_path


def test_external_comp_deletes_metaid_referenced_initial_assignment(tmp_path):
    source, source_path = _write_model(tmp_path)
    document = libsbml.readSBMLFromFile(str(source_path))
    errors = [
        document.getError(index).getMessage()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors, errors

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=1, n_steps=10).atomize(
        source, source_path=source_path
    )
    assert atomized.success, atomized.error
    model_path = tmp_path / "external_comp_initial_assignment_deletion.bngl"
    model_path.write_text(atomized.bngl, encoding="utf-8")
    result = bionetgen.run(str(model_path), "ode", 1.0, 10)

    amounts_a = result.observables["child__A_amt"]
    amounts_b = result.observables["child__B_amt"]
    assert len(amounts_a) == len(amounts_b) == 11
    # The deletion removes k's 0.2 initial assignment, leaving its declared
    # value 0.1. The independent exact solution is A=10*exp(-0.1*t), B=10-A.
    for index, (amount_a, amount_b) in enumerate(zip(amounts_a, amounts_b)):
        time = index / 10
        expected_a = 10 * math.exp(-0.1 * time)
        assert math.isclose(float(amount_a), expected_a, rel_tol=2e-6, abs_tol=1e-8)
        assert math.isclose(
            float(amount_b), 10 - expected_a, rel_tol=2e-6, abs_tol=1e-8
        )
