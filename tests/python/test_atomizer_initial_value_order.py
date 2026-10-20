"""Regression tests for SBML initial-value resolution order in seed species.

These tests cover the spec-mandated ordering (SBML Level 3 Version 2 Core
\u00a74.8 "Rules" and \u00a74.11): assignment rules determine their targets'
values at t=0 before initial assignments are evaluated, so an initial
assignment may reference a variable defined by an assignment rule.  A
non-constant parameter without a ``value`` attribute has no defined initial
value and must not be seeded with the default 0, which would shadow its
assignment rule.

Each regression is derived from the SBML Test Suite semantics (official
reference data are authoritative) and must fail on the unfixed source.
"""

from __future__ import annotations

from collections import OrderedDict

import pytest

from bionetgen.atomizer.modern import (
    SBMLCompartment,
    SBMLInitialAssignment,
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

SBML_NS = "http://www.w3.org/1998/Math/MathML"


def _math(math: str) -> str:
    return (
        f'<math xmlns="{SBML_NS}"><apply><times/>{math}</apply></math>'
        if "<" not in math
        else f'<math xmlns="{SBML_NS}">{math}</math>'
    )


def _bngl_seed_lines(bngl: str) -> dict[str, str]:
    seeds: dict[str, str] = {}
    in_seed = False
    for line in bngl.splitlines():
        if line.strip() == "begin seed species":
            in_seed = True
            continue
        if in_seed:
            if line.strip() == "end seed species":
                break
            if line.strip() and not line.strip().startswith("#"):
                # @C:M_S1() 0.1  ->  S1: 0.1
                body = line.strip().lstrip("@").split(":", 1)[-1]
                species = body.split("()")[0].lstrip("$")
                if species.startswith("M_"):
                    species = species[2:]
                amount = float(body.split()[-1])
                seeds[species] = amount
    return seeds


def test_assignment_rule_value_precedes_initial_assignment():
    # SBML Test Suite semantic/00617 shape:
    #   k1 = constant="false", no value  <- assignmentRule k1 = 0.75
    #   initialAssignment S1 = 0.133333333333333 * k1  -> S1 = 0.1
    sbml = """<?xml version="1.0"?>
    <sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
      <model id="ordering">
        <listOfCompartments>
          <compartment id="C" size="1" units="volume" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" name="S1" compartment="C" substanceUnits="substance"
                   hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="S2" name="S2" compartment="C" initialAmount="0.15"
                   substanceUnits="substance" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k1" name="k1" constant="false"/>
        </listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="S1">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><cn>0.133333333333333</cn><ci>k1</ci></apply>
            </math>
          </initialAssignment>
        </listOfInitialAssignments>
        <listOfRules>
          <assignmentRule variable="k1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.75</cn></math>
          </assignmentRule>
        </listOfRules>
      </model>
    </sbml>
    """
    res = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert res.success, res.error
    seeds = _bngl_seed_lines(res.bngl)
    assert seeds["S1"] == pytest.approx(0.1, abs=1e-9), seeds
    assert seeds["S2"] == pytest.approx(0.15, abs=1e-9), seeds


def test_initial_assignment_references_assignment_rule_target():
    # k1 defined by assignment rule; initial assignment S1 references k1.
    model = SBMLModel(
        id="ref_rule_target",
        compartments=OrderedDict([("cell", SBMLCompartment(id="cell", size=1))]),
        species=OrderedDict(
            [
                (
                    "S1",
                    SBMLSpecies(
                        id="S1",
                        name="S1",
                        compartment="cell",
                        initial_amount=0,
                        initial_amount_set=False,
                    ),
                )
            ]
        ),
        parameters=OrderedDict([("k1", SBMLParameter(id="k1", constant=False))]),
        rules=[SBMLRule(type="assignment", variable="k1", math="0.75")],
        initial_assignments=[
            SBMLInitialAssignment(symbol="S1", math="0.133333333333333 * k1")
        ],
    )
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    import re

    match = re.search(r"@cell:M_S1\(\)\s+([0-9.eE+-]+)", bngl)
    assert match is not None, bngl
    assert float(match.group(1)) == pytest.approx(0.1, abs=1e-9), bngl


def test_initial_assignment_chain():
    # initialAssignment B = 5, initialAssignment A = B + 1  -> B=5, A=6.
    model = SBMLModel(
        id="assignment_chain",
        compartments=OrderedDict([("cell", SBMLCompartment(id="cell", size=1))]),
        species=OrderedDict(
            (
                species_id,
                SBMLSpecies(
                    id=species_id,
                    name=species_id,
                    compartment="cell",
                    initial_amount=0,
                    initial_amount_set=False,
                ),
            )
            for species_id in ("A", "B")
        ),
        initial_assignments=[
            SBMLInitialAssignment(symbol="A", math="B + 1"),
            SBMLInitialAssignment(symbol="B", math="5"),
        ],
    )
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    assert "@cell:M_B() 5" in bngl, bngl
    assert "@cell:M_A() 6" in bngl, bngl


def test_initial_assignment_overrides_species_initial_amount():
    # S1 carries initialAmount=10 but an initialAssignment sets S1 = 0.1;
    # the initial assignment must win.
    sbml = """<?xml version="1.0"?>
    <sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
      <model id="override_amount">
        <listOfCompartments>
          <compartment id="C" size="1" units="volume" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" name="S1" compartment="C" initialAmount="10"
                   substanceUnits="substance" hasOnlySubstanceUnits="false"
                   boundaryCondition="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k1" value="0.75" constant="true"/>
        </listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="S1"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.1</cn></math></initialAssignment>
        </listOfInitialAssignments>
      </model>
    </sbml>
    """
    res = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert res.success, res.error
    seeds = _bngl_seed_lines(res.bngl)
    assert seeds["S1"] == pytest.approx(0.1, abs=1e-9), seeds


def test_non_constant_parameter_without_value_is_not_seeded_zero():
    # k1 = constant="false", no value; assignmentRule k1 = 0.75.  The seed for
    # k1 must be 0.75, not the default 0.
    model = SBMLModel(
        id="no_value_param",
        compartments=OrderedDict([("cell", SBMLCompartment(id="cell", size=1))]),
        species=OrderedDict(
            [
                (
                    "S1",
                    SBMLSpecies(
                        id="S1",
                        name="S1",
                        compartment="cell",
                        initial_amount=0,
                        initial_amount_set=False,
                    ),
                )
            ]
        ),
        parameters=OrderedDict([("k1", SBMLParameter(id="k1", constant=False))]),
        rules=[SBMLRule(type="assignment", variable="k1", math="0.75")],
        initial_assignments=[SBMLInitialAssignment(symbol="S1", math="k1")],
    )
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    # k1 itself resolves to 0.75, so S1 = 0.75 (not 0).
    assert "@cell:M_S1() 0.75" in bngl, bngl


def test_concentration_species_initial_assignment_applies_volume():
    # Concentration species (hasOnlySubstanceUnits="false") in a volume-2
    # compartment.  initialAssignment S1 = 0.1 is a concentration, so the seed
    # amount is 0.1 * Avogadro * volume = 0.2.
    model = SBMLModel(
        id="concentration_seed",
        compartments=OrderedDict(
            [("cell", SBMLCompartment(id="cell", size=2, spatial_dimensions=3))]
        ),
        species=OrderedDict(
            [
                (
                    "S1",
                    SBMLSpecies(
                        id="S1",
                        name="S1",
                        compartment="cell",
                        initial_amount=0,
                        initial_amount_set=False,
                        has_only_substance_units=False,
                    ),
                )
            ]
        ),
        initial_assignments=[SBMLInitialAssignment(symbol="S1", math="0.1")],
    )
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    assert "@cell:M_S1() 0.2" in bngl, bngl
