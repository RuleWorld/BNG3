"""SBML event setters retain parameter identity and changing reaction rates."""

import libsbml
import numpy as np
import pytest
import roadrunner
from _extdep import require_extension

from bionetgen.atomizer.modern import Atomizer

cpp = require_extension()

SOURCE = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
  level="3" version="2"><model id="parameter_switch">
  <listOfCompartments>
    <compartment id="cell" size="1" spatialDimensions="3" constant="true"/>
  </listOfCompartments>
  <listOfSpecies>
    <species id="X" compartment="cell" initialAmount="1"
      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    <species id="Y" compartment="cell" initialAmount="2"
      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    <species id="Z" compartment="cell" initialAmount="1"
      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
  </listOfSpecies>
  <listOfParameters>
    <parameter id="k" value="0.75" constant="false"/>
    <parameter id="r" value="0.25" constant="true"/>
  </listOfParameters>
  <listOfReactions>
    <reaction id="consume" reversible="false">
      <listOfReactants>
        <speciesReference species="X" stoichiometry="1" constant="true"/>
        <speciesReference species="Y" stoichiometry="2" constant="true"/>
      </listOfReactants>
      <listOfProducts><speciesReference species="Z" stoichiometry="1" constant="true"/></listOfProducts>
      <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
        <apply><times/><ci>k</ci><ci>X</ci><ci>Y</ci></apply>
      </math></kineticLaw>
    </reaction>
    <reaction id="release" reversible="false">
      <listOfReactants><speciesReference species="Z" stoichiometry="1" constant="true"/></listOfReactants>
      <listOfProducts>
        <speciesReference species="X" stoichiometry="1" constant="true"/>
        <speciesReference species="Y" stoichiometry="1" constant="true"/>
      </listOfProducts>
      <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
        <apply><times/><ci>r</ci><ci>Z</ci></apply>
      </math></kineticLaw>
    </reaction>
  </listOfReactions>
  <listOfEvents><event id="switch" useValuesFromTriggerTime="true">
    <trigger initialValue="false" persistent="true">
      <math xmlns="http://www.w3.org/1998/Math/MathML">
        <apply><lt/><ci>X</ci><cn>0.75</cn></apply>
      </math>
    </trigger>
    <listOfEventAssignments><eventAssignment variable="k">
      <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
    </eventAssignment></listOfEventAssignments>
  </event></listOfEvents>
</model></sbml>"""


def _read_valid_sbml(source):
    document = libsbml.readSBMLFromString(source)
    document.checkConsistency()
    errors = [
        document.getError(i).getMessage()
        for i in range(document.getNumErrors())
        if document.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors
    return document


@pytest.mark.parametrize("parameter_name", ["k", "S1"])
def test_exported_parameter_event_changes_the_rate_in_its_consumer(
    tmp_path, parameter_name
):
    # S1 also checks the writer's ID collision with generated network species.
    source = (
        SOURCE.replace('id="k"', f'id="{parameter_name}"')
        .replace("<ci>k</ci>", f"<ci>{parameter_name}</ci>")
        .replace('variable="k"', f'variable="{parameter_name}"')
    )
    _read_valid_sbml(source)
    source_oracle = roadrunner.RoadRunner(source)
    selections = ["time", "X", "Y", "Z", parameter_name]
    source_oracle.integrator.setValue("relative_tolerance", 1e-9)
    source_oracle.integrator.setValue("absolute_tolerance", 1e-12)
    expected = source_oracle.simulate(0, 2, 21, selections=selections)
    assert expected[-1, -1] == 1.0, "the independent source event did not fire"

    result = Atomizer(atomize=False, quiet_mode=True).atomize(source)
    assert result.success, result.error
    assert "begin bng3_events" in result.bngl
    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model, max_iter=5)
    output = tmp_path / "switched.xml"
    cpp.io.write_sbml(model, network, str(output))

    document = _read_valid_sbml(output.read_text())
    exported = document.getModel()
    parameter = next(
        p for p in exported.getListOfParameters() if p.getName() == parameter_name
    )
    assert not parameter.getConstant()
    assert exported.getParameter("r").getConstant()
    assignment = exported.getEvent(0).getEventAssignment(0)
    assert assignment.getVariable() == parameter.getId()

    written_oracle = roadrunner.RoadRunner(output.read_text())
    selections[-1] = parameter.getId()
    written_oracle.integrator.setValue("relative_tolerance", 1e-9)
    written_oracle.integrator.setValue("absolute_tolerance", 1e-12)
    actual = written_oracle.simulate(0, 2, 21, selections=selections)
    np.testing.assert_allclose(actual, expected, rtol=2e-6, atol=1e-8)


def test_export_does_not_freeze_parameters_depending_on_an_event_target(tmp_path):
    result = Atomizer(atomize=False, quiet_mode=True).atomize(SOURCE)
    assert result.success, result.error
    # A BNGL dependent parameter changes when k is set by the native event.
    # Until the writer emits its dependency as a rule, it must refuse export.
    bngl = result.bngl.replace("r 0.25", "r k / 3")
    assert bngl != result.bngl
    model = cpp.parse_string(bngl)
    network = cpp.generate_network(model, max_iter=5)
    with pytest.raises(RuntimeError, match="event-dependent parameter 'r'"):
        cpp.io.write_sbml(model, network, str(tmp_path / "dependent.xml"))
