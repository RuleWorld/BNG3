"""Regression tests for a compartment's initial assignment.

SBML Level 3 Version 2 Core (Sec. 4.8.5) states that the value calculated
by an ``initialAssignment`` overrides the value assigned by the object that
defines the symbol: "if a Compartment's size is set in its definition, and
the model also contains an InitialAssignment having that compartment's id as
its symbol value, then the size assigned in the Compartment object
definition should be ignored".  The official SBML Test Suite cases
``semantic/00785``, ``semantic/00786`` and ``semantic/01514`` check that the
compartment therefore has the assigned size at t=0, so both the seed amounts
and the emitted compartment size use it rather than the ``size`` attribute.

Each regression is derived from the official reference data and must fail on
the unfixed source.
"""

from __future__ import annotations

import pytest

from bionetgen.atomizer.modern import Atomizer

SBML_NS = "http://www.w3.org/1998/Math/MathML"


def _model(body: str) -> str:
    return (
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" '
        'level="3" version="2">'
        f'<model id="compartment_initial_assignment">{body}</model>'
        "</sbml>"
    )


def _atomize(body: str):
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(_model(body))
    assert result.success, result.error
    return atomizer, result


def _parameter(bngl: str, name: str) -> str:
    for line in bngl.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{name} "):
            return stripped.split()[1]
    raise AssertionError(f"no {name} parameter emitted:\n{bngl}")


def _seed(bngl: str, species: str) -> str:
    for line in bngl.splitlines():
        stripped = line.strip()
        if not stripped.startswith("@"):
            continue
        pattern, _, amount = stripped.partition(" ")
        if pattern.replace("$", "").endswith(f":M_{species}()"):
            return amount.strip()
    raise AssertionError(f"no seed for {species} emitted:\n{bngl}")


def test_compartment_initial_assignment_replaces_the_declared_size():
    # semantic/00785: C declares size 3.5 but an initial assignment sets it
    # to 2 * p1 = 0.5.  The declared size must be ignored.
    atomizer, result = _atomize(
        "<listOfCompartments>"
        '<compartment id="C" name="C" spatialDimensions="3" size="3.5" '
        'constant="false"/>'
        "</listOfCompartments>"
        "<listOfSpecies>"
        '<species id="S1" name="S1" compartment="C" initialConcentration="0.001" '
        'hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>'
        "</listOfSpecies>"
        "<listOfParameters>"
        '<parameter id="p1" name="p1" value="0.25" constant="true"/>'
        "</listOfParameters>"
        "<listOfInitialAssignments>"
        '<initialAssignment symbol="C">'
        f'<math xmlns="{SBML_NS}"><apply><times/>'
        '<cn type="integer"> 2 </cn><ci> p1 </ci></apply></math>'
        "</initialAssignment>"
        "</listOfInitialAssignments>"
    )

    assert _parameter(result.bngl, "__compartment_C__") == "0.5"
    # The seed amount is the initial concentration times the assigned size.
    assert _seed(result.bngl, "S1") == "0.0005"
    assert atomizer.model.compartments["C"].size == pytest.approx(0.5)


def test_compartment_initial_assignment_supplies_an_undeclared_size():
    # semantic/00786: C declares no size at all, so the initial assignment is
    # the only statement of the compartment's volume.
    _, result = _atomize(
        "<listOfCompartments>"
        '<compartment id="C" name="C" spatialDimensions="3" constant="false"/>'
        "</listOfCompartments>"
        "<listOfSpecies>"
        '<species id="S1" name="S1" compartment="C" initialConcentration="0.1" '
        'hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>'
        "</listOfSpecies>"
        "<listOfParameters>"
        '<parameter id="p1" name="p1" value="0.25" constant="true"/>'
        "</listOfParameters>"
        "<listOfInitialAssignments>"
        '<initialAssignment symbol="C">'
        f'<math xmlns="{SBML_NS}"><apply><times/>'
        '<cn type="integer"> 2 </cn><ci> p1 </ci></apply></math>'
        "</initialAssignment>"
        "</listOfInitialAssignments>"
    )

    assert _parameter(result.bngl, "__compartment_C__") == "0.5"
    assert _seed(result.bngl, "S1") == "0.05"


def test_rate_ruled_compartment_keeps_the_assigned_initial_size():
    # semantic/01514: C1 has a rate rule, which only governs t>0, and an
    # initial assignment, which fixes the size at t=0.  The species' initial
    # quantity is a concentration, so its amount is that concentration times
    # the assigned volume.
    _, result = _atomize(
        "<listOfCompartments>"
        '<compartment id="C1" spatialDimensions="3" constant="false"/>'
        "</listOfCompartments>"
        "<listOfSpecies>"
        '<species id="S1" compartment="C1" hasOnlySubstanceUnits="false" '
        'boundaryCondition="true" constant="false"/>'
        "</listOfSpecies>"
        "<listOfInitialAssignments>"
        '<initialAssignment symbol="S1">'
        f'<math xmlns="{SBML_NS}"><apply><divide/>'
        '<cn type="integer"> 3 </cn><cn type="integer"> 2 </cn></apply></math>'
        "</initialAssignment>"
        '<initialAssignment symbol="C1">'
        f'<math xmlns="{SBML_NS}"><apply><divide/>'
        '<cn type="integer"> 1 </cn><cn type="integer"> 2 </cn></apply></math>'
        "</initialAssignment>"
        "</listOfInitialAssignments>"
        "<listOfRules>"
        '<rateRule variable="C1">'
        f'<math xmlns="{SBML_NS}"><cn> 0.2 </cn></math>'
        "</rateRule>"
        "</listOfRules>"
    )

    assert _parameter(result.bngl, "__compartment_C1__") == "0.5"
    # 3/2 concentration in a 1/2 volume compartment.
    assert _seed(result.bngl, "S1") == "0.75"
    # The rate rule still governs the compartment after t=0.
    assert "__rate_rule__C1()" in result.bngl


def test_compartment_initial_assignments_resolve_a_chain():
    # One initial assignment may use the value another one establishes.
    _, result = _atomize(
        "<listOfCompartments>"
        '<compartment id="C1" spatialDimensions="3" constant="true"/>'
        '<compartment id="C2" spatialDimensions="3" constant="true"/>'
        "</listOfCompartments>"
        "<listOfInitialAssignments>"
        '<initialAssignment symbol="C1">'
        f'<math xmlns="{SBML_NS}"><cn> 2 </cn></math>'
        "</initialAssignment>"
        '<initialAssignment symbol="C2">'
        f'<math xmlns="{SBML_NS}"><apply><times/>'
        '<cn type="integer"> 3 </cn><ci> C1 </ci></apply></math>'
        "</initialAssignment>"
        "</listOfInitialAssignments>"
    )

    assert _parameter(result.bngl, "__compartment_C1__") == "2"
    assert _parameter(result.bngl, "__compartment_C2__") == "6"


def test_only_resolved_compartment_initial_assignments_are_applied():
    # An initial assignment whose expression depends on a species cannot be
    # resolved at t=0, because that species has no initial amount or
    # concentration and its initial quantity is therefore unknown (SBML
    # Level 3 Version 2 Core, Sec. 4.8).  The compartment keeps the size its
    # assignment rule computes instead: an assignment rule "overrides the
    # value assigned to the given symbol by the object defining that
    # symbol" (Sec. 4.9.3), so the declared size is ignored.
    #
    # The fixture model is not valid SBML -- Sec. 4.9.3 forbids a model from
    # containing both an assignment rule and an initial assignment for the
    # same variable -- so the rule's value is what the model defines, and
    # the unresolved initial assignment contributes nothing.
    _, result = _atomize(
        "<listOfCompartments>"
        '<compartment id="C1" spatialDimensions="3" size="3.5" constant="true"/>'
        '<compartment id="C2" spatialDimensions="3" size="3.5" constant="false"/>'
        '<compartment id="C3" spatialDimensions="3" size="3.5" constant="false"/>'
        "</listOfCompartments>"
        "<listOfSpecies>"
        '<species id="S1" compartment="C1" hasOnlySubstanceUnits="false" '
        'boundaryCondition="false" constant="false"/>'
        "</listOfSpecies>"
        "<listOfInitialAssignments>"
        '<initialAssignment symbol="C1">'
        f'<math xmlns="{SBML_NS}"><cn> 0.5 </cn></math>'
        "</initialAssignment>"
        '<initialAssignment symbol="C2">'
        f'<math xmlns="{SBML_NS}"><ci> S1 </ci></math>'
        "</initialAssignment>"
        '<initialAssignment symbol="C3">'
        f'<math xmlns="{SBML_NS}"><cn> 0.25 </cn></math>'
        "</initialAssignment>"
        "</listOfInitialAssignments>"
        "<listOfRules>"
        '<assignmentRule variable="C2">'
        f'<math xmlns="{SBML_NS}"><cn> 2 </cn></math>'
        "</assignmentRule>"
        "</listOfRules>"
    )

    assert _parameter(result.bngl, "__compartment_C1__") == "0.5"
    assert _parameter(result.bngl, "__compartment_C3__") == "0.25"
    # The unresolved initial assignment contributes nothing: the size is the
    # assignment rule's value, not the species' undefined initial quantity.
    assert _parameter(result.bngl, "__compartment_C2__") == "2"
