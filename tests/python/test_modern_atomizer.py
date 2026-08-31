"""Acceptance tests for the Python port of the Playground atomizer.

These expectations are intentionally derived from the public TypeScript
atomizer in RuleWorld/bngplayground, rather than from BNG3's legacy
translator.  Keep the fixture small so each inferred relationship is
discriminating and easy to compare with the source implementation.
"""

from __future__ import annotations

from collections import OrderedDict

import pytest

libsbml = pytest.importorskip("libsbml")


SBML_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns:bqbiol="http://biomodels.net/biology-qualifiers/"
      level="3" version="1">
  <model id="playground_fixture" name="Playground fixture">
    <listOfUnitDefinitions>
      <unitDefinition id="mM">
        <listOfUnits><unit kind="mole" scale="-3" exponent="1" multiplier="1"/></listOfUnits>
      </unitDefinition>
    </listOfUnitDefinitions>
    <listOfCompartments>
      <compartment id="cell" name="cell" spatialDimensions="3" size="2" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" name="A" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false">
        <annotation><rdf:RDF><rdf:Description rdf:about="#A">
          <bqbiol:is><rdf:Bag><rdf:li rdf:resource="urn:miriam:uniprot:P12345"/></rdf:Bag></bqbiol:is>
        </rdf:Description></rdf:RDF></annotation>
      </species>
      <species id="B" name="B" compartment="cell" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
      <species id="C" name="A_P" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
      <species id="D" name="AB" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="kf" value="0.1" constant="true"/>
      <parameter id="kp" value="0.2" constant="true"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="B"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>4</cn></math></initialAssignment>
    </listOfInitialAssignments>
    <listOfReactions>
      <reaction id="bind" name="binding" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="A" constant="false"/>
          <speciesReference species="B" constant="false"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="D" constant="false"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>kf</ci><ci>A</ci><ci>B</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="modify" name="phosphorylation" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A" constant="false"/></listOfReactants>
        <listOfProducts><speciesReference species="C" constant="false"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>kp</ci><ci>A</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""


def test_playground_structures_preserve_states_bonds_and_compartments():
    from bionetgen.atomizer.modern import Component, read_from_string

    species = read_from_string("@cell::A(site~P!1).B(bind!1)@mem")

    assert [m.name for m in species.molecules] == ["A", "B"]
    assert species.molecules[0].compartment == "cell"
    assert species.molecules[1].compartment == "mem"
    assert species.molecules[0].components[0].active_state == "P"
    assert species.molecules[0].components[0].bonds == ["1"]
    assert species.molecules[1].components[0].bonds == ["1"]
    assert str(species) == "A(site!1~P)@cell.B(bind!1)@mem"

    component = Component("site")
    component.add_state("P")
    assert component.states == ["P", "0"]
    assert component.str2() == "site~P~0"


def test_playground_reaction_classification_is_stoichiometry_aware():
    from bionetgen.atomizer.modern import SBMLReaction, SBMLSpeciesReference
    from bionetgen.atomizer.modern import classify_reaction

    binding = SBMLReaction(
        id="r1",
        name="",
        reversible=False,
        fast=False,
        reactants=[SBMLSpeciesReference("A"), SBMLSpeciesReference("B")],
        products=[SBMLSpeciesReference("D")],
        modifiers=[],
        kinetic_law={"math": "kf*A*B", "mathML": "", "localParameters": []},
    )
    unbinding = SBMLReaction(
        id="r2",
        name="",
        reversible=False,
        fast=False,
        reactants=[SBMLSpeciesReference("D")],
        products=[SBMLSpeciesReference("A"), SBMLSpeciesReference("B")],
        modifiers=[],
        kinetic_law={"math": "kr*D", "mathML": "", "localParameters": []},
    )

    assert classify_reaction(binding).type == "binding"
    assert classify_reaction(binding).reactants == ["A", "B"]
    assert classify_reaction(unbinding).type == "unbinding"
    assert classify_reaction(unbinding).products == ["A", "B"]


def test_playground_parser_preserves_annotations_initial_assignments_and_rates():
    from bionetgen.atomizer.modern import SBMLParser

    model = SBMLParser().parse(SBML_FIXTURE)

    assert model.id == "playground_fixture"
    assert list(model.species) == ["A", "B", "C", "D"]
    assert model.species["A"].initial_amount == 2
    assert model.species["B"].initial_amount_set is False
    assert model.species["A"].annotations[0].resources == ["urn:miriam:uniprot:P12345"]
    assert model.initial_assignments[0].symbol == "B"
    assert model.initial_assignments[0].math == "4"
    assert model.reactions["bind"].kinetic_law["math"] == "kf * A * B"


def test_playground_sct_infers_complexes_and_named_modifications():
    from bionetgen.atomizer.modern import SBMLParser
    from bionetgen.atomizer.modern import build_species_composition_table

    model = SBMLParser().parse(SBML_FIXTURE)
    sct = build_species_composition_table(model, atomize=True)

    assert sct.entries["A"].is_elemental is True
    assert sct.entries["B"].is_elemental is True
    assert sct.entries["D"].is_elemental is False
    assert sct.entries["D"].components == ["A", "B"]
    assert "b1" in {
        component.name
        for molecule in sct.entries["D"].structure.molecules
        for component in molecule.components
    }
    assert sct.entries["C"].is_elemental is False
    assert sct.entries["C"].structure.molecules[0].get_component("phosphorylation")
    assert (
        sct.entries["C"]
        .structure.molecules[0]
        .get_component("phosphorylation")
        .active_state
        == "P"
    )


def test_playground_collision_discriminator_preserves_distinct_species():
    from bionetgen.atomizer.modern import (
        Component,
        Molecule,
        SBMLModel,
        SBMLSpecies,
        Species,
        SpeciesCompositionTable,
        SCTEntry,
        disambiguate_colliding_species,
    )

    def make_species():
        result = Species()
        molecule = Molecule("ERK")
        molecule.add_component(Component("site", states=["P"]))
        result.add_molecule(molecule)
        return result

    entries = OrderedDict(
        [
            (
                "cyto",
                SCTEntry(
                    structure=make_species(),
                    components=["ERK"],
                    sbml_id="cyto",
                    is_elemental=True,
                    modifications={},
                    weight=1,
                    bonds=[],
                ),
            ),
            (
                "nuc",
                SCTEntry(
                    structure=make_species(),
                    components=["ERK"],
                    sbml_id="nuc",
                    is_elemental=True,
                    modifications={},
                    weight=1,
                    bonds=[],
                ),
            ),
        ]
    )
    model = SBMLModel(
        id="m",
        name="m",
        compartments=OrderedDict(),
        species=OrderedDict(
            [
                ("cyto", SBMLSpecies(id="cyto", name="ERK", compartment="cell")),
                ("nuc", SBMLSpecies(id="nuc", name="ERK", compartment="cell")),
            ]
        ),
        parameters=OrderedDict(),
        reactions=OrderedDict(),
        rules=[],
        function_definitions=OrderedDict(),
        events=[],
        initial_assignments=[],
        species_by_compartment=OrderedDict(),
        unit_definitions=OrderedDict(),
    )
    sct = SpeciesCompositionTable(
        entries=entries,
        dependencies=OrderedDict(),
        reverse_dependencies=OrderedDict(),
        sorted_species=["cyto", "nuc"],
        weights=[("cyto", 1), ("nuc", 1)],
    )

    assert disambiguate_colliding_species(sct, model) == 2
    assert (
        sct.entries["cyto"].structure.molecules[0].get_component("__sp").active_state
        == "cyto"
    )
    assert (
        sct.entries["nuc"].structure.molecules[0].get_component("__sp").active_state
        == "nuc"
    )


def test_playground_atomizer_generates_flat_and_atomized_bngl():
    from bionetgen.atomizer.modern import Atomizer

    flat = Atomizer(atomize=False).atomize(SBML_FIXTURE)
    atomized = Atomizer(atomize=True).atomize(SBML_FIXTURE)

    for result in (flat, atomized):
        assert result.success is True
        assert "begin model" in result.bngl
        assert "begin parameters" in result.bngl
        assert "begin seed species" in result.bngl
        assert "begin reaction rules" in result.bngl
        assert "bind" in result.bngl
        assert "phosphorylation" in result.bngl

    assert "A()" in flat.bngl or "M_A" in flat.bngl
    assert "b1" in atomized.bngl
    assert "~P" in atomized.bngl


def test_playground_math_rewrites_match_writer_contract():
    from bionetgen.atomizer.modern import convert_math_expression

    assert convert_math_expression("pow(x, y)") == "((x)^(y))"
    assert convert_math_expression("sqrt(x)") == "((x)^(1/2))"
    assert convert_math_expression("exp(x)") == "(2.71828182845905^(x))"
    assert convert_math_expression("log(x)") == "ln(x)"
    assert convert_math_expression("log10(x)") == "(ln(x)/2.302585093)"
    assert convert_math_expression("abs(x)") == "if(x>=0,x,-(x))"
    assert (
        convert_math_expression("piecewise(v1, c1, v2, c2)")
        == "if(c1, v1, if(c2, v2, 0))"
    )
    assert convert_math_expression("gt(a, b)") == "(a > b)"
    assert convert_math_expression("pi * exponentiale * true * false") == (
        "3.14159265358979 * 2.71828182845905 * 1 * 0"
    )


def test_playground_writer_emits_zero_argument_functions_and_assignment_rules():
    from bionetgen.atomizer.modern import (
        SBMLFunctionDefinition,
        SBMLModel,
        SBMLParameter,
        SBMLRule,
        SBMLSpecies,
        Atomizer,
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    model = SBMLModel(
        id="rules",
        name="rules",
        species=OrderedDict(
            [
                (
                    "A",
                    SBMLSpecies(
                        id="A", name="A", initial_amount=1, initial_amount_set=True
                    ),
                )
            ]
        ),
        parameters=OrderedDict([("k", SBMLParameter(id="k", value=2))]),
        function_definitions=OrderedDict(
            [("f", SBMLFunctionDefinition(id="f", name="f", math="k + 1"))]
        ),
        rules=[SBMLRule(type="assignment", variable="v", math="f")],
    )
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    assert "f() = k + 1" in bngl
    assert "v() = f()" in bngl
