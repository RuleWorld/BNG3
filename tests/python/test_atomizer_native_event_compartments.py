"""Source-derived compartment values must reach native event expressions."""

import libsbml
import numpy as np
import pytest
import roadrunner
from _extdep import require_extension

from bionetgen.atomizer.modern import Atomizer

cpp = require_extension()


def _source(*, piecewise=False, compartment_size=2.0):
    increment = "<apply><plus/><ci>S</ci><apply><divide/><cn>1</cn><ci>cell</ci></apply></apply>"
    value = (
        f"<piecewise><piece>{increment}<apply><gt/><ci>S</ci><cn>0</cn></apply></piece>"
        "<otherwise><cn>0</cn></otherwise></piecewise>"
        if piecewise
        else increment
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="static_event_compartment" timeUnits="second">
 <listOfCompartments><compartment id="cell" size="{compartment_size}" constant="true"/></listOfCompartments>
 <listOfSpecies><species id="S" compartment="cell" initialConcentration="0"
   hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/></listOfSpecies>
 <listOfReactions><reaction id="inflow" reversible="false">
  <listOfProducts><speciesReference species="S" stoichiometry="1" constant="true"/></listOfProducts>
  <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>cell</ci></math></kineticLaw>
 </reaction>
 <reaction id="outflow" reversible="false">
  <listOfReactants><speciesReference species="S" stoichiometry="1" constant="true"/></listOfReactants>
  <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
   <apply><times/><ci>cell</ci><apply><power/><ci>S</ci><cn>3</cn></apply></apply>
  </math></kineticLaw>
 </reaction></listOfReactions>
 <listOfEvents><event id="pulse" useValuesFromTriggerTime="true">
  <trigger initialValue="false" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
   <apply><gt/><ci>S</ci><cn>0.5</cn></apply>
  </math></trigger>
  <listOfEventAssignments><eventAssignment variable="S">
   <math xmlns="http://www.w3.org/1998/Math/MathML">{value}</math>
  </eventAssignment></listOfEventAssignments>
 </event></listOfEvents>
</model></sbml>"""


@pytest.mark.parametrize("piecewise", [False, True], ids=["arithmetic", "piecewise"])
@pytest.mark.parametrize("compartment_size", [2.0, 4.0])
def test_atomizer_native_event_compartment_matches_source_law(
    tmp_path, piecewise, compartment_size
):
    """S'=1-S^3; the event adds 1/cell to concentration, hence one to amount."""
    source = _source(piecewise=piecewise, compartment_size=compartment_size)
    document = libsbml.readSBMLFromString(source)
    document.checkConsistency()
    errors = [
        document.getError(i).getMessage()
        for i in range(document.getNumErrors())
        if document.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors
    times = np.array([0.0, 0.25, 0.75, 1.0])
    oracle = roadrunner.RoadRunner(source)
    oracle.integrator.setValue("relative_tolerance", 1e-10)
    oracle.integrator.setValue("absolute_tolerance", 1e-12)
    expected = np.asarray(oracle.simulate(times=times, selections=["time", "S"]))
    assert 0 < expected[1, 1] < compartment_size * times[1]
    assert expected[2, 1] > compartment_size * 0.5

    result = Atomizer(atomize=False, quiet_mode=True).atomize(source)
    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model, max_iter=5)
    actual = cpp.simulate_ode(model, network, times.tolist(), rtol=1e-10, atol=1e-12)
    np.testing.assert_allclose(
        actual["observables"]["S_amt"], expected[:, 1], rtol=1e-7, atol=1e-9
    )
