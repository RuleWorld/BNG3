"""A species initial assignment in a unit-scaled compartment seeds the right amount.

Regression for BioModels BIOMD0000000978: a 1 L compartment is normalized to
0.001 m^3 and a concentration assigned from a parameter is normalized by 1000.
The writer multiplies the resolved assignment by the compartment size to obtain
a BNGL amount seed. An extra division by the compartment factor made the seed
1000x too large (3.6196938e10 instead of 3.6196938e7).
"""

from __future__ import annotations

import pytest

from bionetgen.atomizer.modern import Atomizer

SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="scaled_initial_assignment" substanceUnits="substance"
         volumeUnits="volume" timeUnits="time" extentUnits="substance">
    <listOfUnitDefinitions>
      <unitDefinition id="substance"><listOfUnits><unit kind="item" exponent="1" scale="0" multiplier="1"/></listOfUnits></unitDefinition>
      <unitDefinition id="volume"><listOfUnits><unit kind="litre" exponent="1" scale="-3" multiplier="1"/></listOfUnits></unitDefinition>
      <unitDefinition id="time"><listOfUnits><unit kind="second" exponent="1" scale="0" multiplier="1"/></listOfUnits></unitDefinition>
    </listOfUnitDefinitions>
    <listOfCompartments>
      <compartment id="C" size="1" spatialDimensions="3" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="C" initialConcentration="1000"
               hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="N" value="1000" constant="true"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="S"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>N</ci></math></initialAssignment>
    </listOfInitialAssignments>
    <listOfReactions>
      <reaction id="decay" reversible="false">
        <listOfReactants><speciesReference species="S" stoichiometry="1" constant="true"/></listOfReactants>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>C</ci><cn>0.1</cn><ci>S</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""


def test_parameter_only_initial_assignment_seed_is_not_double_scaled():
    result = Atomizer(atomize=True, quiet_mode=True).atomize(SOURCE)
    assert result.success, result.error
    bngl = str(result.bngl)
    assert "C 3 0.001" in bngl
    seed = [
        line.strip()
        for line in bngl.splitlines()
        if line.strip().startswith("@C:M_S() ")
    ]
    assert len(seed) == 1
    assert float(seed[0].split()[-1]) == pytest.approx(1000, rel=1e-12)
