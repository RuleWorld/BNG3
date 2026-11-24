"""Independent structure evidence for the two Multi compartment-reference rows.

The historical row checks matched warning text and were counted as supported
execution even though one construct is explicitly refused and the other uses an
attribute that SBML Multi does not define on an extended Species. libSBML is
the independent structural oracle here. Warning strings remain diagnostics;
they never establish support.
"""

from __future__ import annotations

import ast
from pathlib import Path

import libsbml

from test_sbml_multi_release import (
    MULTI_COMPARTMENT_XML,
    MULTI_COMP_INSTANCE_XML,
    MULTI_COMP_SPECIES_XML,
)
from bionetgen.atomizer.modern import parse_multi_package

MULTI_NS = "http://www.sbml.org/sbml/level3/version1/multi/version1"


def _constants():
    """Read the shared XML fixtures without importing side-effecting runners."""
    path = Path(__file__).with_name("test_sbml_multi_release.py")
    values = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and isinstance(node.targets[0], ast.Name)
        ):
            values[node.targets[0].id] = node.value.value
    return values


def _document(xml: str):
    doc = libsbml.readSBMLFromString(xml)
    assert doc.getNumErrors() == 0
    return doc


def test_species_type_instance_compartment_reference_structure_is_independent():
    """libSBML sees instance x -> 'inside' -> c2, different from parent c1."""
    doc = _document(_constants()["MULTI_COMP_INSTANCE_XML"])
    plugin = doc.getModel().getPlugin("multi")
    instance = None
    for index in range(plugin.getNumMultiSpeciesTypes()):
        species_type = plugin.getMultiSpeciesType(index)
        for j in range(species_type.getNumSpeciesTypeInstances()):
            candidate = species_type.getSpeciesTypeInstance(j)
            if candidate.getCompartmentReference():
                instance = candidate
                parent = species_type
    assert instance is not None
    assert instance.getCompartmentReference() == "inside"
    cref = (
        doc.getModel()
        .getCompartment(parent.getCompartment())
        .getPlugin("multi")
        .getCompartmentReference(0)
    )
    assert cref.getId() == "inside"
    assert cref.getCompartment() == "c2"
    assert cref.getCompartment() != parent.getCompartment()


def test_species_type_instance_is_explicitly_unsupported_not_a_pass():
    """BNG3 refuses the cross-compartment instance; record that, do not pass it."""
    parsed = parse_multi_package(MULTI_COMP_INSTANCE_XML)
    assert parsed.executable is False
    assert any("different compartment" in w.message for w in parsed.warnings)
    # A dropped refusal is diagnostic evidence only, never supported execution.
    assert all(
        w.severity == "dropped"
        for w in parsed.warnings
        if "different compartment" in w.message
    )


def test_multispecies_compartment_reference_is_not_a_defined_attribute():
    """The libSBML MultiSpecies extension has no compartmentReference attribute."""
    assert not [
        name for name in dir(libsbml.MultiSpeciesPlugin) if "ompartment" in name
    ]
    doc = _document(_constants()["MULTI_COMP_SPECIES_XML"])
    species = doc.getModel().getSpecies(0)
    plugin = species.getPlugin("multi")
    assert plugin.isSetSpeciesType()
    assert not hasattr(plugin, "getCompartmentReference")
    parsed = parse_multi_package(MULTI_COMP_SPECIES_XML)
    assert any("compartmentReference" in w.message for w in parsed.warnings)
    # The correct disposition is a diagnostic about an undefined attribute.
    assert all(
        w.severity == "dropped"
        for w in parsed.warnings
        if "compartmentReference" in w.message
    )


def test_species_reference_compartment_reference_preserves_product_compartment():
    """Positive control: the defined attribute redirects the product to c2."""
    doc = _document(_constants()["MULTI_COMPARTMENT_XML"])
    product = doc.getModel().getReaction(0).getProduct(0)
    assert product.getPlugin("multi").getCompartmentReference() == "inside"
    parsed = parse_multi_package(MULTI_COMPARTMENT_XML)
    assert parsed.executable
    assert parsed.compartment_references["c1"]["inside"] == "c2"


PAIR_BASE = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="m">
    <listOfCompartments>
      <compartment id="c1" size="1" spatialDimensions="3" constant="true" multi:isType="false">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c2" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c1" initialAmount="0" hasOnlySubstanceUnits="true"
        boundaryCondition="false" constant="false" multi:speciesType="AType"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      {bst}
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="c1">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType" {cref}/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""


def _pair_sources():
    same = PAIR_BASE.format(
        bst='<multi:bindingSiteSpeciesType multi:id="xType" multi:compartment="c1"/>',
        cref="",
    )
    nested = PAIR_BASE.format(
        bst='<multi:bindingSiteSpeciesType multi:id="xType" multi:compartment="c2"/>',
        cref='multi:compartmentReference="inside"',
    )
    return same, nested


def test_valid_pair_from_936_is_distinguished_by_representation():
    """The two libSBML-valid sources differ only in binding-site placement.

    PR #936 lowered both to byte-identical BNGL, losing the placement; the
    maintainer closed that lowering. This check requires libSBML to see the
    structural difference and requires the exact-main representation to keep
    the two sources distinguishable, with the nested-reference row recorded as
    explicitly unsupported rather than a silent supported PASS.
    """
    same, nested = _pair_sources()
    placements = []
    for xml in (same, nested):
        doc = _document(xml)
        plugin = doc.getModel().getPlugin("multi")
        cref = None
        for index in range(plugin.getNumMultiSpeciesTypes()):
            species_type = plugin.getMultiSpeciesType(index)
            for j in range(species_type.getNumSpeciesTypeInstances()):
                instance = species_type.getSpeciesTypeInstance(j)
                if instance.getCompartmentReference():
                    cref = instance.getCompartmentReference()
        placements.append(cref)
    assert placements == [None, "inside"]

    same_parsed = parse_multi_package(same)
    nested_parsed = parse_multi_package(nested)
    assert same_parsed.executable is True
    # Exact main distinguishes the pair; the nested placement is not collapsed
    # into a nominally supported row (that was the rejected PR #936 lowering).
    assert nested_parsed.executable is False
    assert any(
        w.severity == "dropped" and "different compartment" in w.message
        for w in nested_parsed.warnings
    )
