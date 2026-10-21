"""Regression tests for SBML initial-value resolution in seed species.

SBML determines a model's initial values from the model's assignment
statements considered as a whole (Sec. 4.8.5, "Semantics of initial
assignments"; Sec. 4.9.5, "Additional restrictions on rules"; Sec. 3.4.8,
 "Initial conditions and special considerations", for the order in which
the values at t <= 0 are established).  Two consequences matter here:

* an initial assignment that reads a variable an assignment rule defines
  observes the rule's value, because an assignment rule holds for all time
  and overrides the value its target's definition gives it (Sec. 4.9.3).  The
  official SBML Test Suite requires this: semantic/00617 and seventeen
  further cases have that shape, and in every one of them the rule target has
  no declared value;
* an initial assignment that reads a variable another initial assignment
  defines observes that initial assignment's value, not the value given in
  the symbol's definition (Sec. 4.8.5).

A model that names the same variable in an assignment rule and an initial
assignment is **not valid SBML** -- it would be indeterminate (Sec. 4.9.3) --
so the specification says nothing about it.  The two tests that build such a
model pin BNG3's deterministic tie-break for that invalid combination; they
do not assert a specified behaviour.

A symbol that no construct establishes a value for is underdetermined rather
than invalid (Sec. 3.4.9).  BNG3 leaves such a value unresolved instead of
inventing a 0, and one test pins that.

The expected values were derived offline with libRoadRunner 2.10.0 as an
independent oracle; the tests themselves do not import it.

What each test discriminates:

* ``test_assignment_rule_value_precedes_initial_assignment``,
  ``test_initial_assignment_references_assignment_rule_target``,
  ``test_non_constant_parameter_without_value_is_not_seeded_zero``,
  ``test_assignment_rule_reads_initial_assignment_value`` and
  ``test_parameter_without_value_is_not_silently_seeded_zero`` fail against
  the source before PR #316;
* ``test_initial_assignment_group_resolves_before_assignment_rules`` fails
  against the source before this change, which resolved the invalid
  combination by a different route;
* ``test_assignment_rule_governs_variable_named_by_initial_assignment`` and
  ``test_initial_assignment_chain`` pass on every source tried; they pin
  behaviour that must not drift.
"""

from __future__ import annotations

import re
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


def _initial_assignment(symbol: str, math: str) -> str:
    return (
        '<initialAssignment symbol="'
        + symbol
        + '">'
        + _math(math)
        + "</initialAssignment>"
    )


def _assignment_rule(variable: str, math: str) -> str:
    return (
        '<assignmentRule variable="'
        + variable
        + '">'
        + _math(math)
        + "</assignmentRule>"
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


def _overlap_sbml(
    initial_assignments: str,
    rules: str,
    parameters: str = '<parameter id="p" constant="false"/>',
    species: str = (
        '<species id="S1" compartment="C" initialAmount="0"'
        ' hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>'
        '<species id="S2" compartment="C" initialAmount="0"'
        ' hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>'
    ),
) -> str:
    """Build a small SBML model that exercises initial-value resolution."""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
      <model id="overlap">
        <listOfCompartments>
          <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>{species}</listOfSpecies>
        <listOfParameters>{parameters}</listOfParameters>
        <listOfInitialAssignments>{initial_assignments}</listOfInitialAssignments>
        {rules}
        <listOfReactions>
          <reaction id="R0" reversible="false">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw><math xmlns="{SBML_NS}"><cn>0</cn></math></kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>
    """


def _bngl_function(bngl: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(name)}\(\)\s*=\s*(.+)$", bngl)
    assert match is not None, f"{name}() is not emitted:\n{bngl}"
    return match.group(1).strip()


def test_initial_assignment_group_resolves_before_assignment_rules():
    # The model below is NOT valid SBML: an assignment rule and an initial
    # assignment name the same variable, which Sec. 4.9.3 declares
    # indeterminate.  Nothing is specified for it, so this test pins BNG3's
    # deterministic tie-break and nothing more.  The tie-break is that the
    # initial assignment's value is what the other initial assignments
    # observe, so S1 = p and S2 = S1 both see p's initial assignment value 3,
    # while the assignment rule still gives p its own value 5.
    # libRoadRunner 2.10.0 reports the same t=0 values (S1 = 3, S2 = 3,
    # p = 5) for this model.
    sbml = _overlap_sbml(
        initial_assignments=(
            _initial_assignment("S1", "<ci>p</ci>")
            + _initial_assignment("p", "<cn>3</cn>")
            + _initial_assignment("S2", "<ci>S1</ci>")
        ),
        rules="<listOfRules>" + _assignment_rule("p", "<cn>5</cn>") + "</listOfRules>",
    )
    res = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert res.success, res.error
    seeds = _bngl_seed_lines(res.bngl)
    assert seeds["S1"] == pytest.approx(3.0, abs=1e-9), seeds
    assert seeds["S2"] == pytest.approx(3.0, abs=1e-9), seeds


def test_assignment_rule_governs_variable_named_by_initial_assignment():
    # The model below is NOT valid SBML: p is named by both an initial
    # assignment and an assignment rule, which Sec. 4.9.3 declares
    # indeterminate.  Nothing is specified for it, so this test pins BNG3's
    # deterministic tie-break: the initial assignment's value is what the
    # other initial assignments observe (S1 = 2 * 3 = 6), while the
    # assignment rule still governs p's own value in the emitted model
    # (p() = 5).  libRoadRunner 2.10.0 reports the same t=0 values
    # (S1 = 6, p = 5) for this model.
    sbml = _overlap_sbml(
        initial_assignments=(
            _initial_assignment("p", "<cn>3</cn>")
            + _initial_assignment("S1", "<apply><times/><cn>2</cn><ci>p</ci></apply>")
        ),
        rules="<listOfRules>" + _assignment_rule("p", "<cn>5</cn>") + "</listOfRules>",
    )
    res = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert res.success, res.error
    seeds = _bngl_seed_lines(res.bngl)
    assert seeds["S1"] == pytest.approx(6.0, abs=1e-9), seeds
    # The rule determines the value of p itself.
    assert _bngl_function(res.bngl, "p") == "5", res.bngl


def test_assignment_rule_reads_initial_assignment_value():
    # The initial assignments are evaluated first, so the rule p = q + 1 sees
    # q's initial assignment value 3 and gives p = 4.  libRoadRunner reports
    # p = 4 and S1 = 2 * 4 = 8 at t=0.
    sbml = _overlap_sbml(
        initial_assignments=(
            _initial_assignment("q", "<cn>3</cn>")
            + _initial_assignment("S1", "<apply><times/><cn>2</cn><ci>p</ci></apply>")
        ),
        rules=(
            "<listOfRules>"
            + _assignment_rule("p", "<apply><plus/><ci>q</ci><cn>1</cn></apply>")
            + "</listOfRules>"
        ),
        parameters=(
            '<parameter id="p" value="1" constant="true"/>'
            '<parameter id="q" value="1" constant="true"/>'
        ),
    )
    res = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert res.success, res.error
    seeds = _bngl_seed_lines(res.bngl)
    assert seeds["S1"] == pytest.approx(8.0, abs=1e-9), seeds
    assert _bngl_function(res.bngl, "p") == "3 + 1", res.bngl


def test_parameter_without_value_is_not_silently_seeded_zero():
    # A constant="false" parameter with no value attribute, no rule and no
    # initial assignment is underdetermined rather than invalid (Sec. 3.4.9),
    # and SBML stipulates no particular course of action for it.  BNG3 leaves
    # the value out of the table, so an initial assignment that reads it
    # stays unresolved -- the seed keeps the symbolic expression instead of
    # silently becoming 0.  libRoadRunner refuses such a model outright
    # ("Global parameter 'k' is missing a value"), so the symbolic seed is
    # the honest rendering.
    sbml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
      <model id="undefined_parameter">
        <listOfCompartments>
          <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="0"
                   hasOnlySubstanceUnits="true" boundaryCondition="false"
                   constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k" name="k" constant="false"/>
        </listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="S1">
            <math xmlns="{SBML_NS}"><apply><times/><cn>2</cn><ci>k</ci></apply></math>
          </initialAssignment>
        </listOfInitialAssignments>
      </model>
    </sbml>
    """
    res = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert res.success, res.error
    in_seed = False
    emitted = []
    for line in res.bngl.splitlines():
        stripped = line.strip()
        if stripped == "begin seed species":
            in_seed = True
            continue
        if stripped == "end seed species":
            break
        if in_seed and stripped:
            emitted.append(stripped)
    assert emitted, res.bngl
    amounts = [entry.split()[-1] for entry in emitted]
    # The undefined variable must not be resolved to the number 0.
    assert "0" not in amounts, res.bngl
    assert "0.0" not in amounts, res.bngl
    # The seed keeps the unresolved expression, so the model does not claim a
    # value the source never established.
    assert any("k" in amount for amount in amounts), res.bngl
