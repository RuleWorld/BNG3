"""A speciesTypeInstance compartmentReference names a nested sub-compartment.

Regression for SBML Multi L3V1 sections 3.6 and 3.11.3: a compartmentReference
declared by the containing compartment identifies a sub-compartment of that
composite, so a binding-site instance placed there remains part of the BNGL
molecule in the parent compartment.
"""

from __future__ import annotations

import libsbml

from bionetgen.atomizer.modern import Atomizer, parse_multi_package

SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="cross_comp_instance">
    <listOfCompartments>
      <compartment id="c1" size="1" spatialDimensions="3" constant="true" multi:isType="false">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c2" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c1" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType" multi:compartment="c2"/>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="c1">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType" multi:compartmentReference="inside"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""


def test_nested_compartment_reference_is_representable():
    document = libsbml.readSBMLFromString(SOURCE)
    assert document.getNumErrors() == 0
    model = document.getModel()
    plugin = model.getCompartment("c1").getPlugin("multi")
    reference = plugin.getCompartmentReference(0)
    assert reference.getId() == "inside"
    assert reference.getCompartment() == "c2"

    parsed = parse_multi_package(SOURCE)
    assert parsed.executable
    assert not [w for w in parsed.warnings if w.severity == "dropped"]

    atomized = Atomizer(atomize=True, quiet_mode=True).atomize(SOURCE)
    assert atomized.success
    bngl = str(atomized.bngl)
    assert "M_A(xType)" in bngl
    assert "M_A()@c1" in bngl
