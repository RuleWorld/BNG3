"""Focused tests for SBML Level 3 ``arrays`` v1 static flattening."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from bionetgen.atomizer.modern import (
    ARRAYS_NAMESPACE_V1,
    ArraysFlatteningError,
    Atomizer,
    SBMLParser,
    flatten_arrays_package,
    flatten_arrays_sbml,
    has_arrays_constructs,
)

CORE_NS = "http://www.sbml.org/sbml/level3/version1/core"
MATH_NS = "http://www.w3.org/1998/Math/MathML"
ARRAYS_NS = ARRAYS_NAMESPACE_V1


def _sbml_doc(body: str, *, arrays_decl: bool = True, arrays_version: int = 1) -> str:
    decl = (
        f' xmlns:arrays="http://www.sbml.org/sbml/level3/version1/arrays/version{arrays_version}"'
        ' arrays:required="true"'
        if arrays_decl
        else ""
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<sbml xmlns="{CORE_NS}"{decl} level="3" version="1">\n'
        f'  <model id="arrays_test">\n'
        f"{body}\n"
        f"  </model>\n"
        f"</sbml>\n"
    )


def _assert_libsbml_valid(sbml_xml: str) -> None:
    libsbml = pytest.importorskip("libsbml")
    doc = libsbml.readSBMLFromString(sbml_xml)
    doc.checkConsistency()
    errors = [
        doc.getError(i).getMessage()
        for i in range(doc.getNumErrors())
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors, f"libSBML consistency errors: {errors}"


def _simulate_bng3_ode(tmp_path, sbml_xml: str, t_end: float = 2.0, n_steps: int = 20):
    import bionetgen

    atomized = Atomizer(
        atomize=False, quiet_mode=True, t_end=t_end, n_steps=n_steps
    ).atomize(sbml_xml)
    assert atomized.success, atomized.error
    model_path = tmp_path / "model.bngl"
    model_path.write_text(atomized.bngl, encoding="utf-8")
    return bionetgen.run(str(model_path), "ode", t_end, n_steps), atomized


def _assert_fails_closed(sbml_xml: str, match: str) -> None:
    with pytest.raises(ArraysFlatteningError, match=match):
        flatten_arrays_sbml(sbml_xml)

    flat, failure = flatten_arrays_package(sbml_xml)
    assert flat == sbml_xml
    assert failure is not None and "arrays flattening failed" in failure

    parsed = SBMLParser().parse(sbml_xml)
    assert any(
        w["category"] == "arraysFlattening" and w["severity"] == "dropped"
        for w in parsed.import_warnings
    )

    atomized = Atomizer(atomize=False, quiet_mode=True).atomize(sbml_xml)
    assert not atomized.success
    assert atomized.error and "arrays flattening failed" in atomized.error


def test_1d_arrayed_compartments_species_parameters_and_reactions_match_hand_flattened(
    tmp_path,
):
    """3-stage transport chain with arrayed compartments, species, params, and reactions."""

    arrays_sbml = _sbml_doc(f"""
    <listOfCompartments>
      <compartment id="c" size="1" constant="true">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="d_c" arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </compartment>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="c" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="d_s" arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
        <arrays:listOfIndices>
          <arrays:index arrays:referencedAttribute="compartment" arrays:arrayDimension="0">
            <math xmlns="{MATH_NS}"><ci>d_s</ci></math>
          </arrays:index>
        </arrays:listOfIndices>
      </species>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="N" value="3" constant="true"/>
      <parameter id="M" value="2" constant="true"/>
      <parameter id="k" value="0" constant="true">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="d_k" arrays:size="M" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="c">
        <math xmlns="{MATH_NS}">
          <vector><cn>1</cn><cn>2</cn><cn>4</cn></vector>
        </math>
      </initialAssignment>
      <initialAssignment symbol="S">
        <arrays:listOfIndices>
          <arrays:index arrays:referencedAttribute="symbol" arrays:arrayDimension="0">
            <math xmlns="{MATH_NS}"><cn type="integer">0</cn></math>
          </arrays:index>
        </arrays:listOfIndices>
        <math xmlns="{MATH_NS}"><cn>10</cn></math>
      </initialAssignment>
      <initialAssignment symbol="k">
        <math xmlns="{MATH_NS}">
          <vector><cn>0.5</cn><cn>0.8</cn></vector>
        </math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfReactions>
      <reaction id="R" reversible="false" fast="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="i" arrays:size="M" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
        <listOfReactants>
          <speciesReference species="S" stoichiometry="1" constant="true">
            <arrays:listOfIndices>
              <arrays:index arrays:referencedAttribute="species" arrays:arrayDimension="0">
                <math xmlns="{MATH_NS}"><ci>i</ci></math>
              </arrays:index>
            </arrays:listOfIndices>
          </speciesReference>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="S" stoichiometry="1" constant="true">
            <arrays:listOfIndices>
              <arrays:index arrays:referencedAttribute="species" arrays:arrayDimension="0">
                <math xmlns="{MATH_NS}">
                  <apply><plus/><ci>i</ci><cn type="integer">1</cn></apply>
                </math>
              </arrays:index>
            </arrays:listOfIndices>
          </speciesReference>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="{MATH_NS}">
            <apply>
              <times/>
              <apply><selector/><ci>k</ci><ci>i</ci></apply>
              <apply><selector/><ci>S</ci><ci>i</ci></apply>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    """)

    hand_flattened = _sbml_doc(
        f"""
    <listOfCompartments>
      <compartment id="c_0" size="1" constant="true"/>
      <compartment id="c_1" size="1" constant="true"/>
      <compartment id="c_2" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S_0" compartment="c_0" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="S_1" compartment="c_1" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="S_2" compartment="c_2" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="N" value="3" constant="true"/>
      <parameter id="M" value="2" constant="true"/>
      <parameter id="k_0" value="0" constant="true"/>
      <parameter id="k_1" value="0" constant="true"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="c_0"><math xmlns="{MATH_NS}"><cn>1</cn></math></initialAssignment>
      <initialAssignment symbol="c_1"><math xmlns="{MATH_NS}"><cn>2</cn></math></initialAssignment>
      <initialAssignment symbol="c_2"><math xmlns="{MATH_NS}"><cn>4</cn></math></initialAssignment>
      <initialAssignment symbol="S_0"><math xmlns="{MATH_NS}"><cn>10</cn></math></initialAssignment>
      <initialAssignment symbol="k_0"><math xmlns="{MATH_NS}"><cn>0.5</cn></math></initialAssignment>
      <initialAssignment symbol="k_1"><math xmlns="{MATH_NS}"><cn>0.8</cn></math></initialAssignment>
    </listOfInitialAssignments>
    <listOfReactions>
      <reaction id="R_0" reversible="false" fast="false">
        <listOfReactants><speciesReference species="S_0" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="S_1" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="{MATH_NS}"><apply><times/><ci>k_0</ci><ci>S_0</ci></apply></math></kineticLaw>
      </reaction>
      <reaction id="R_1" reversible="false" fast="false">
        <listOfReactants><speciesReference species="S_1" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="S_2" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="{MATH_NS}"><apply><times/><ci>k_1</ci><ci>S_1</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
    """,
        arrays_decl=False,
    )

    flattened_xml = flatten_arrays_sbml(arrays_sbml)
    _assert_libsbml_valid(flattened_xml)
    assert not has_arrays_constructs(flattened_xml)

    parsed_arr = SBMLParser().parse(arrays_sbml)
    parsed_ref = SBMLParser().parse(hand_flattened)
    assert list(parsed_arr.compartments) == ["c_0", "c_1", "c_2"]
    assert list(parsed_arr.species) == ["S_0", "S_1", "S_2"]
    assert [parsed_arr.species[s].compartment for s in parsed_arr.species] == [
        "c_0",
        "c_1",
        "c_2",
    ]
    assert list(parsed_arr.reactions) == ["R_0", "R_1"]
    assert [parsed_arr.compartments[c].size for c in parsed_arr.compartments] == [
        1.0,
        2.0,
        4.0,
    ]
    assert parsed_arr.species.keys() == parsed_ref.species.keys()
    assert parsed_arr.reactions.keys() == parsed_ref.reactions.keys()

    # Valid flattened arrays emits info warning, zero dropped warnings.
    assert any(
        w["category"] == "arraysFlattened" and w["severity"] == "info"
        for w in parsed_arr.import_warnings
    )
    assert not any(w["severity"] == "dropped" for w in parsed_arr.import_warnings)

    # Independent oracle check with libRoadRunner against hand-flattened Core SBML.
    roadrunner = pytest.importorskip("roadrunner")
    rr_arr = roadrunner.RoadRunner(flattened_xml)
    rr_ref = roadrunner.RoadRunner(hand_flattened)
    for rr in (rr_arr, rr_ref):
        rr.timeCourseSelections = ["time", "S_0", "S_1", "S_2"]
    traj_arr = rr_arr.simulate(0, 2.0, 21)
    traj_ref = rr_ref.simulate(0, 2.0, 21)
    assert traj_arr[-1, 1:] == pytest.approx(traj_ref[-1, 1:], rel=1e-7, abs=1e-9)

    # End-to-end BNG3 execution matches RoadRunner.
    res_bng, _ = _simulate_bng3_ode(tmp_path, arrays_sbml, t_end=2.0, n_steps=20)
    for idx, sid in enumerate(("S_0", "S_1", "S_2"), start=1):
        assert res_bng.observables[sid][-1] == pytest.approx(
            traj_ref[-1, idx], rel=1e-5, abs=1e-6
        )


def test_2d_arrays_nested_vectors_partial_selector_and_rules(tmp_path):
    """2x2 species grid, 2D vector init, nested selector, partial slicing rule, and rateRule."""

    arrays_sbml = _sbml_doc(f"""
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="G" compartment="cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="r" arrays:size="NR" arrays:arrayDimension="0"/>
          <arrays:dimension arrays:id="c" arrays:size="NC" arrays:arrayDimension="1"/>
        </arrays:listOfDimensions>
      </species>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="NR" value="2" constant="true"/>
      <parameter id="NC" value="2" constant="true"/>
      <parameter id="row0" value="0" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="NC" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
      <parameter id="p_rate" value="1" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="dr" arrays:size="NR" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="G">
        <math xmlns="{MATH_NS}">
          <vector>
            <vector><cn>10</cn><cn>20</cn></vector>
            <vector><cn>30</cn><cn>40</cn></vector>
          </vector>
        </math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfRules>
      <assignmentRule variable="row0">
        <math xmlns="{MATH_NS}">
          <apply><selector/><ci>G</ci><cn type="integer">0</cn></apply>
        </math>
      </assignmentRule>
      <rateRule variable="p_rate">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="ri" arrays:size="NR" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
        <arrays:listOfIndices>
          <arrays:index arrays:referencedAttribute="variable" arrays:arrayDimension="0">
            <math xmlns="{MATH_NS}"><ci>ri</ci></math>
          </arrays:index>
        </arrays:listOfIndices>
        <math xmlns="{MATH_NS}">
          <apply>
            <plus/>
            <apply><selector/><ci>G</ci><ci>ri</ci><cn type="integer">0</cn></apply>
            <apply>
              <selector/>
              <apply><selector/><ci>G</ci><ci>ri</ci></apply>
              <cn type="integer">1</cn>
            </apply>
          </apply>
        </math>
      </rateRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="decay" reversible="false" fast="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="i" arrays:size="NR" arrays:arrayDimension="0"/>
          <arrays:dimension arrays:id="j" arrays:size="NC" arrays:arrayDimension="1"/>
        </arrays:listOfDimensions>
        <listOfReactants>
          <speciesReference species="G" stoichiometry="1" constant="true">
            <arrays:listOfIndices>
              <arrays:index arrays:referencedAttribute="species" arrays:arrayDimension="0">
                <math xmlns="{MATH_NS}"><ci>i</ci></math>
              </arrays:index>
              <arrays:index arrays:referencedAttribute="species" arrays:arrayDimension="1">
                <math xmlns="{MATH_NS}"><ci>j</ci></math>
              </arrays:index>
            </arrays:listOfIndices>
          </speciesReference>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="{MATH_NS}">
            <apply>
              <times/>
              <apply><plus/><cn>0.1</cn><apply><times/><cn>0.05</cn><ci>i</ci></apply></apply>
              <apply><selector/><ci>G</ci><ci>i</ci><ci>j</ci></apply>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    """)

    flattened_xml = flatten_arrays_sbml(arrays_sbml)
    _assert_libsbml_valid(flattened_xml)

    parsed = SBMLParser().parse(arrays_sbml)
    assert list(parsed.species) == ["G_0_0", "G_0_1", "G_1_0", "G_1_1"]
    assert list(parsed.reactions) == [
        "decay_0_0",
        "decay_0_1",
        "decay_1_0",
        "decay_1_1",
    ]
    assert set(parsed.parameters) >= {"row0_0", "row0_1", "p_rate_0", "p_rate_1"}
    assign_rules = {r.variable: r.math for r in parsed.rules if r.type == "assignment"}
    assert assign_rules == {"row0_0": "G_0_0", "row0_1": "G_0_1"}

    roadrunner = pytest.importorskip("roadrunner")
    rr = roadrunner.RoadRunner(flattened_xml)
    rr.timeCourseSelections = [
        "time",
        "G_0_0",
        "G_0_1",
        "G_1_0",
        "G_1_1",
        "row0_0",
        "row0_1",
        "p_rate_0",
        "p_rate_1",
    ]
    traj = rr.simulate(0, 1.0, 11)
    assert traj[-1, 5] == pytest.approx(traj[-1, 1], rel=1e-7)
    assert traj[-1, 6] == pytest.approx(traj[-1, 2], rel=1e-7)

    res_bng, _ = _simulate_bng3_ode(tmp_path, arrays_sbml, t_end=1.0, n_steps=10)
    assert res_bng.observables["G_0_0"][-1] == pytest.approx(traj[-1, 1], rel=1e-5)
    assert res_bng.observables["G_1_1"][-1] == pytest.approx(traj[-1, 4], rel=1e-5)


def test_events_with_arrayed_event_and_vector_event_assignment(tmp_path):
    """Arrayed events plus vector eventAssignment reproduce RoadRunner trajectories."""

    arrays_sbml = _sbml_doc(f"""
    <listOfCompartments>
      <compartment id="c" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="X" compartment="c" initialAmount="10"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="d_x" arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </species>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="N" value="2" constant="true"/>
      <parameter id="boost" value="0" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
    </listOfParameters>
    <listOfReactions>
      <reaction id="deg" reversible="false" fast="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="i" arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
        <listOfReactants>
          <speciesReference species="X" stoichiometry="1" constant="true">
            <arrays:listOfIndices>
              <arrays:index arrays:referencedAttribute="species" arrays:arrayDimension="0">
                <math xmlns="{MATH_NS}"><ci>i</ci></math>
              </arrays:index>
            </arrays:listOfIndices>
          </speciesReference>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="{MATH_NS}">
            <apply>
              <times/>
              <apply><plus/><cn>0.5</cn><apply><times/><cn>0.5</cn><ci>i</ci></apply></apply>
              <apply><selector/><ci>X</ci><ci>i</ci></apply>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="refill" useValuesFromTriggerTime="true">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="e" arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
        <trigger initialValue="true" persistent="true">
          <math xmlns="{MATH_NS}">
            <apply>
              <lt/>
              <apply><selector/><ci>X</ci><ci>e</ci></apply>
              <cn>6</cn>
            </apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="X">
            <arrays:listOfIndices>
              <arrays:index arrays:referencedAttribute="variable" arrays:arrayDimension="0">
                <math xmlns="{MATH_NS}"><ci>e</ci></math>
              </arrays:index>
            </arrays:listOfIndices>
            <math xmlns="{MATH_NS}"><cn>12</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
      <event id="vec_set" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="{MATH_NS}">
            <apply>
              <geq/>
              <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol>
              <cn>0.5</cn>
            </apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="boost">
            <math xmlns="{MATH_NS}">
              <vector><cn>3</cn><cn>7</cn></vector>
            </math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
    """)

    flattened_xml = flatten_arrays_sbml(arrays_sbml)
    _assert_libsbml_valid(flattened_xml)

    parsed = SBMLParser().parse(arrays_sbml)
    assert [ev.id for ev in parsed.events] == ["refill_0", "refill_1", "vec_set"]
    assert [(a.variable, a.math) for a in parsed.events[2].assignments] == [
        ("boost_0", "3"),
        ("boost_1", "7"),
    ]

    roadrunner = pytest.importorskip("roadrunner")
    rr = roadrunner.RoadRunner(flattened_xml)
    rr.timeCourseSelections = ["time", "X_0", "X_1", "boost_0", "boost_1"]
    traj = rr.simulate(0, 1.5, 16)
    assert traj[-1, 3] == pytest.approx(3.0)
    assert traj[-1, 4] == pytest.approx(7.0)

    res_bng, _ = _simulate_bng3_ode(tmp_path, arrays_sbml, t_end=1.5, n_steps=15)
    assert res_bng.observables["X_0"][-1] == pytest.approx(traj[-1, 1], rel=1e-4)
    assert res_bng.observables["X_1"][-1] == pytest.approx(traj[-1, 2], rel=1e-4)


def test_species_reference_inner_dimensions_sum_product_local_params_and_modifiers(
    tmp_path,
):
    """Single reaction with arrayed speciesReferences, modifiers, localParameters, sum/product."""

    arrays_sbml = _sbml_doc(f"""
    <listOfCompartments>
      <compartment id="c" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialAmount="2"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </species>
      <species id="P" compartment="c" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="N" value="3" constant="true"/>
      <parameter id="totA" value="0" constant="false"/>
      <parameter id="prodA" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="totA">
        <math xmlns="{MATH_NS}">
          <apply>
            <sum/>
            <bvar><ci>k</ci></bvar>
            <lowlimit><cn type="integer">0</cn></lowlimit>
            <uplimit><apply><minus/><ci>N</ci><cn type="integer">1</cn></apply></uplimit>
            <apply><selector/><ci>A</ci><ci>k</ci></apply>
          </apply>
        </math>
      </assignmentRule>
      <assignmentRule variable="prodA">
        <math xmlns="{MATH_NS}">
          <apply><product/><ci>A</ci></apply>
        </math>
      </assignmentRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="combine" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true">
            <arrays:listOfDimensions>
              <arrays:dimension arrays:id="idx" arrays:size="N" arrays:arrayDimension="0"/>
            </arrays:listOfDimensions>
            <arrays:listOfIndices>
              <arrays:index arrays:referencedAttribute="species" arrays:arrayDimension="0">
                <math xmlns="{MATH_NS}"><ci>idx</ci></math>
              </arrays:index>
            </arrays:listOfIndices>
          </speciesReference>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="P" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <listOfModifiers>
          <modifierSpeciesReference species="A">
            <arrays:listOfDimensions>
              <arrays:dimension arrays:id="midx" arrays:size="N" arrays:arrayDimension="0"/>
            </arrays:listOfDimensions>
            <arrays:listOfIndices>
              <arrays:index arrays:referencedAttribute="species" arrays:arrayDimension="0">
                <math xmlns="{MATH_NS}"><ci>midx</ci></math>
              </arrays:index>
            </arrays:listOfIndices>
          </modifierSpeciesReference>
        </listOfModifiers>
        <kineticLaw>
          <math xmlns="{MATH_NS}">
            <apply>
              <times/>
              <apply><selector/><ci>kloc</ci><cn type="integer">1</cn></apply>
              <apply><sum/><ci>A</ci></apply>
            </apply>
          </math>
          <listOfLocalParameters>
            <localParameter id="kloc" value="0.25">
              <arrays:listOfDimensions>
                <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
              </arrays:listOfDimensions>
            </localParameter>
          </listOfLocalParameters>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    """)

    flattened_xml = flatten_arrays_sbml(arrays_sbml)
    _assert_libsbml_valid(flattened_xml)

    parsed = SBMLParser().parse(arrays_sbml)
    rxn = parsed.reactions["combine"]
    assert [r.species for r in rxn.reactants] == ["A_0", "A_1", "A_2"]
    assert [m.species for m in rxn.modifiers] == ["A_0", "A_1", "A_2"]
    rules = {r.variable: r.math for r in parsed.rules}
    assert rules["totA"] == "A_0 + A_1 + A_2"
    assert rules["prodA"] == "A_0 * A_1 * A_2"

    roadrunner = pytest.importorskip("roadrunner")
    rr = roadrunner.RoadRunner(flattened_xml)
    rr.timeCourseSelections = ["time", "A_0", "P", "totA", "prodA"]
    traj = rr.simulate(0, 0.5, 11)
    assert traj[0, 3] == pytest.approx(6.0)
    assert traj[0, 4] == pytest.approx(8.0)

    res_bng, _ = _simulate_bng3_ode(tmp_path, arrays_sbml, t_end=0.5, n_steps=10)
    assert res_bng.observables["P"][-1] == pytest.approx(traj[-1, 2], rel=1e-5)


def test_piecewise_periodic_index_csymbol_selector_and_const_array_lookup():
    """Periodic boundary index math, <csymbol> selector, and constant index table."""

    arrays_sbml = _sbml_doc(f"""
    <listOfCompartments>
      <compartment id="c" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="c" initialAmount="1"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </species>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="N" constant="true"/>
      <parameter id="perm" value="0" constant="true">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
      <parameter id="out" value="0" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="N">
        <math xmlns="{MATH_NS}"><cn type="integer">3</cn></math>
      </initialAssignment>
      <initialAssignment symbol="perm">
        <math xmlns="{MATH_NS}">
          <vector><cn type="integer">2</cn><cn type="integer">0</cn><cn type="integer">1</cn></vector>
        </math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfRules>
      <assignmentRule variable="out">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="i" arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
        <arrays:listOfIndices>
          <arrays:index arrays:referencedAttribute="variable" arrays:arrayDimension="0">
            <math xmlns="{MATH_NS}"><apply><selector/><ci>perm</ci><ci>i</ci></apply></math>
          </arrays:index>
        </arrays:listOfIndices>
        <math xmlns="{MATH_NS}">
          <apply>
            <csymbol definitionURL="http://www.sbml.org/sbml/symbols/arrays/selector">selector</csymbol>
            <ci>S</ci>
            <piecewise>
              <piece>
                <cn type="integer">0</cn>
                <apply><eq/><ci>i</ci><cn type="integer">2</cn></apply>
              </piece>
              <otherwise>
                <apply><plus/><ci>i</ci><cn type="integer">1</cn></apply>
              </otherwise>
            </piecewise>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
    """)

    flattened_xml = flatten_arrays_sbml(arrays_sbml)
    _assert_libsbml_valid(flattened_xml)
    parsed = SBMLParser().parse(arrays_sbml)
    rules = {r.variable: r.math for r in parsed.rules}
    assert rules == {"out_2": "S_1", "out_0": "S_2", "out_1": "S_0"}


def test_partial_2d_initial_assignment_and_arrayed_algebraic_rule():
    """Partial 2D vector initialAssignment and arrayed algebraicRule flatten cleanly."""

    arrays_sbml = _sbml_doc(f"""
    <listOfCompartments>
      <compartment id="c" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="M" compartment="c" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="R" arrays:arrayDimension="0"/>
          <arrays:dimension arrays:size="C" arrays:arrayDimension="1"/>
        </arrays:listOfDimensions>
      </species>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="R" value="2" constant="true"/>
      <parameter id="C" value="2" constant="true"/>
      <parameter id="T" value="5" constant="true"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="M">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="r" arrays:size="R" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
        <arrays:listOfIndices>
          <arrays:index arrays:referencedAttribute="symbol" arrays:arrayDimension="0">
            <math xmlns="{MATH_NS}"><ci>r</ci></math>
          </arrays:index>
        </arrays:listOfIndices>
        <math xmlns="{MATH_NS}">
          <vector>
            <apply><plus/><ci>r</ci><cn>1</cn></apply>
            <apply><plus/><ci>r</ci><cn>10</cn></apply>
          </vector>
        </math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfRules>
      <algebraicRule>
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="r" arrays:size="R" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
        <math xmlns="{MATH_NS}">
          <apply>
            <minus/>
            <apply>
              <plus/>
              <apply><selector/><ci>M</ci><ci>r</ci><cn type="integer">0</cn></apply>
              <apply><selector/><ci>M</ci><ci>r</ci><cn type="integer">1</cn></apply>
            </apply>
            <ci>T</ci>
          </apply>
        </math>
      </algebraicRule>
    </listOfRules>
    """)

    flattened_xml = flatten_arrays_sbml(arrays_sbml)
    _assert_libsbml_valid(flattened_xml)
    parsed = SBMLParser().parse(arrays_sbml)
    assert list(parsed.species) == ["M_0_0", "M_0_1", "M_1_0", "M_1_1"]
    ias = {ia.symbol: ia.math for ia in parsed.initial_assignments}
    assert ias == {
        "M_0_0": "0 + 1",
        "M_0_1": "0 + 10",
        "M_1_0": "1 + 1",
        "M_1_1": "1 + 10",
    }
    alg_rules = [r.math for r in parsed.rules if r.type == "algebraic"]
    assert alg_rules == ["(M_0_0 + M_0_1) - T", "(M_1_0 + M_1_1) - T"]


def test_zero_size_dimension_and_empty_declared_arrays_package():
    """Zero-size dimensions expand to zero items; unused arrays namespace stays info."""

    zero_sbml = _sbml_doc(f"""
    <listOfCompartments>
      <compartment id="c" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="Empty" compartment="c" initialAmount="1"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="Z" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </species>
      <species id="Keep" compartment="c" initialAmount="3"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="Z" value="0" constant="true"/>
      <parameter id="s0" value="0" constant="false"/>
      <parameter id="p0" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="s0">
        <math xmlns="{MATH_NS}"><apply><sum/><ci>Empty</ci></apply></math>
      </assignmentRule>
      <assignmentRule variable="p0">
        <math xmlns="{MATH_NS}"><apply><product/><ci>Empty</ci></apply></math>
      </assignmentRule>
    </listOfRules>
    """)
    flattened_xml = flatten_arrays_sbml(zero_sbml)
    _assert_libsbml_valid(flattened_xml)
    parsed = SBMLParser().parse(zero_sbml)
    assert list(parsed.species) == ["Keep"]
    rules = {r.variable: r.math for r in parsed.rules}
    assert rules == {"s0": "0", "p0": "1"}

    # Declared xmlns:arrays with zero elements keeps existing info warning.
    empty_decl_sbml = _sbml_doc("""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialAmount="1"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    """)
    assert not has_arrays_constructs(empty_decl_sbml)
    parsed_empty = SBMLParser().parse(empty_decl_sbml)
    warning = next(
        w for w in parsed_empty.import_warnings if w["category"] == "package:arrays"
    )
    assert warning["severity"] == "info"


@pytest.mark.parametrize(
    "label,param_xml,match",
    [
        (
            "non_constant_size",
            '<parameter id="N" value="2" constant="false"/>',
            "constant non-negative integer",
        ),
        (
            "negative_size",
            '<parameter id="N" value="-2" constant="true"/>',
            "constant non-negative integer",
        ),
        (
            "non_integer_size",
            '<parameter id="N" value="2.5" constant="true"/>',
            "constant non-negative integer",
        ),
        (
            "missing_size_param",
            "",
            "constant non-negative integer",
        ),
        (
            "arrayed_size_param",
            '<parameter id="M" value="2" constant="true"/>'
            '<parameter id="N" value="2" constant="true">'
            "<arrays:listOfDimensions>"
            '<arrays:dimension arrays:size="M" arrays:arrayDimension="0"/>'
            "</arrays:listOfDimensions></parameter>",
            "constant non-negative integer",
        ),
    ],
)
def test_fail_closed_invalid_dimension_sizes(label, param_xml, match):
    sbml = _sbml_doc(f"""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="c" initialAmount="1"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="i" arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </species>
    </listOfSpecies>
    <listOfParameters>{param_xml}</listOfParameters>
    """)
    _assert_fails_closed(sbml, match)


def test_fail_closed_dynamic_index_in_selector_and_arrays_index():
    dynamic_selector = _sbml_doc(f"""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="c" initialAmount="1"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </species>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="N" value="2" constant="true"/>
      <parameter id="dyn" value="0" constant="false"/>
      <parameter id="out" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="out">
        <math xmlns="{MATH_NS}">
          <apply><selector/><ci>S</ci><ci>dyn</ci></apply>
        </math>
      </assignmentRule>
    </listOfRules>
    """)
    _assert_fails_closed(dynamic_selector, "Non-constant or unknown symbol 'dyn'")

    dynamic_index = _sbml_doc(f"""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="c" initialAmount="1"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </species>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="N" value="2" constant="true"/>
      <parameter id="dyn" value="0" constant="false"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="S">
        <arrays:listOfIndices>
          <arrays:index arrays:referencedAttribute="symbol" arrays:arrayDimension="0">
            <math xmlns="{MATH_NS}"><ci>dyn</ci></math>
          </arrays:index>
        </arrays:listOfIndices>
        <math xmlns="{MATH_NS}"><cn>5</cn></math>
      </initialAssignment>
    </listOfInitialAssignments>
    """)
    _assert_fails_closed(dynamic_index, "Non-constant or unknown symbol 'dyn'")


@pytest.mark.parametrize("bad_index", ["-1", "2"])
def test_fail_closed_out_of_bounds_index_and_selector(bad_index):
    oob_index = _sbml_doc(f"""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="c" initialAmount="1"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </species>
    </listOfSpecies>
    <listOfParameters><parameter id="N" value="2" constant="true"/></listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="S">
        <arrays:listOfIndices>
          <arrays:index arrays:referencedAttribute="symbol" arrays:arrayDimension="0">
            <math xmlns="{MATH_NS}"><cn type="integer">{bad_index}</cn></math>
          </arrays:index>
        </arrays:listOfIndices>
        <math xmlns="{MATH_NS}"><cn>5</cn></math>
      </initialAssignment>
    </listOfInitialAssignments>
    """)
    _assert_fails_closed(oob_index, "out of bounds")

    oob_selector = _sbml_doc(f"""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="c" initialAmount="1"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </species>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="N" value="2" constant="true"/>
      <parameter id="out" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="out">
        <math xmlns="{MATH_NS}">
          <apply><selector/><ci>S</ci><cn type="integer">{bad_index}</cn></apply>
        </math>
      </assignmentRule>
    </listOfRules>
    """)
    _assert_fails_closed(oob_selector, "out of bounds")


def test_fail_closed_malformed_dimensions_indices_vectors_and_collisions():
    # 1. Non-contiguous arrayDimension
    non_contiguous = _sbml_doc("""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfParameters>
      <parameter id="N" value="2" constant="true"/>
      <parameter id="p" value="1" constant="true">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="1"/>
        </arrays:listOfDimensions>
      </parameter>
    </listOfParameters>
    """)
    _assert_fails_closed(non_contiguous, "contiguous arrayDimension")

    # 2. Unindexed array symbol in scalar arithmetic
    unindexed_scalar_math = _sbml_doc(f"""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfParameters>
      <parameter id="N" value="2" constant="true"/>
      <parameter id="p" value="1" constant="true">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
      <parameter id="out" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="out">
        <math xmlns="{MATH_NS}"><apply><times/><cn>2</cn><ci>p</ci></apply></math>
      </assignmentRule>
    </listOfRules>
    """)
    _assert_fails_closed(unindexed_scalar_math, "Unindexed array value")

    # 3. Shape mismatch in vector assignment
    shape_mismatch = _sbml_doc(f"""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfParameters>
      <parameter id="N" value="3" constant="true"/>
      <parameter id="p" value="1" constant="true">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="p">
        <math xmlns="{MATH_NS}"><vector><cn>1</cn><cn>2</cn></vector></math>
      </initialAssignment>
    </listOfInitialAssignments>
    """)
    _assert_fails_closed(shape_mismatch, "Shape mismatch")

    # 4. Jagged nested vector
    jagged_vector = _sbml_doc(f"""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfParameters>
      <parameter id="N" value="2" constant="true"/>
      <parameter id="M" value="2" constant="true"/>
      <parameter id="p" value="1" constant="true">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
          <arrays:dimension arrays:size="M" arrays:arrayDimension="1"/>
        </arrays:listOfDimensions>
      </parameter>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="p">
        <math xmlns="{MATH_NS}">
          <vector>
            <vector><cn>1</cn><cn>2</cn></vector>
            <vector><cn>3</cn></vector>
          </vector>
        </math>
      </initialAssignment>
    </listOfInitialAssignments>
    """)
    _assert_fails_closed(jagged_vector, "Jagged")

    # 5. Flattened ID collision
    id_collision = _sbml_doc("""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfParameters>
      <parameter id="N" value="2" constant="true"/>
      <parameter id="p" value="1" constant="true">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
      <parameter id="p_0" value="5" constant="true"/>
    </listOfParameters>
    """)
    _assert_fails_closed(id_collision, "collides")

    # 6. Duplicate target from collapsing index
    duplicate_target = _sbml_doc(f"""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfParameters>
      <parameter id="N" value="2" constant="true"/>
      <parameter id="p" value="1" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="p">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="i" arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
        <arrays:listOfIndices>
          <arrays:index arrays:referencedAttribute="variable" arrays:arrayDimension="0">
            <math xmlns="{MATH_NS}"><cn type="integer">0</cn></math>
          </arrays:index>
        </arrays:listOfIndices>
        <math xmlns="{MATH_NS}"><ci>i</ci></math>
      </assignmentRule>
    </listOfRules>
    """)
    _assert_fails_closed(duplicate_target, "Duplicate <assignmentRule> target 'p_0'")

    # 7. Dimension id colliding with existing model SId
    dim_sid_collision = _sbml_doc("""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfParameters>
      <parameter id="N" value="2" constant="true"/>
      <parameter id="i" value="9" constant="true"/>
      <parameter id="p" value="1" constant="true">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="i" arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
    </listOfParameters>
    """)
    _assert_fails_closed(dim_sid_collision, "collides with an existing model SId")

    # 8. listOfDimensions on unsupported element (<functionDefinition>)
    unsupported_elem = _sbml_doc(f"""
    <listOfFunctionDefinitions>
      <functionDefinition id="f">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
        <math xmlns="{MATH_NS}"><lambda><cn>1</cn></lambda></math>
      </functionDefinition>
    </listOfFunctionDefinitions>
    <listOfParameters><parameter id="N" value="2" constant="true"/></listOfParameters>
    """)
    _assert_fails_closed(unsupported_elem, "functionDefinition")

    # 9. Unsupported arrays package version
    bad_version = _sbml_doc(
        """
    <listOfParameters>
      <parameter id="N" value="2" constant="true"/>
      <parameter id="p" value="1" constant="true">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
    </listOfParameters>
    """,
        arrays_version=2,
    )
    _assert_fails_closed(bad_version, "Unsupported SBML arrays package version 2")

    # 10. Dimension size exceeding MAX_FLATTENED_ELEMENTS
    huge_size = _sbml_doc("""
    <listOfParameters>
      <parameter id="N" value="1000000" constant="true"/>
      <parameter id="p" value="1" constant="true">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </parameter>
    </listOfParameters>
    """)
    _assert_fails_closed(huge_size, "exceeds flattening limit")


def test_arrayed_species_reference_id_and_stoichiometry_rule():
    """SpeciesReference with id inside arrayed reaction flattens and supports rules."""

    arrays_sbml = _sbml_doc(f"""
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="c" initialAmount="5"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
      </species>
    </listOfSpecies>
    <listOfParameters><parameter id="N" value="2" constant="true"/></listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="sr">
        <math xmlns="{MATH_NS}"><vector><cn>2</cn><cn>3</cn></vector></math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfReactions>
      <reaction id="R" reversible="false" fast="false">
        <arrays:listOfDimensions>
          <arrays:dimension arrays:id="i" arrays:size="N" arrays:arrayDimension="0"/>
        </arrays:listOfDimensions>
        <listOfReactants>
          <speciesReference id="sr" species="S" stoichiometry="1" constant="true">
            <arrays:listOfIndices>
              <arrays:index arrays:referencedAttribute="species" arrays:arrayDimension="0">
                <math xmlns="{MATH_NS}"><ci>i</ci></math>
              </arrays:index>
            </arrays:listOfIndices>
          </speciesReference>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="{MATH_NS}"><apply><selector/><ci>S</ci><ci>i</ci></apply></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    """)

    flattened_xml = flatten_arrays_sbml(arrays_sbml)
    _assert_libsbml_valid(flattened_xml)
    parsed = SBMLParser().parse(arrays_sbml)
    assert parsed.reactions["R_0"].reactants[0].id == "sr_0"
    assert parsed.reactions["R_0"].reactants[0].stoichiometry == pytest.approx(2.0)
    assert parsed.reactions["R_1"].reactants[0].id == "sr_1"
    assert parsed.reactions["R_1"].reactants[0].stoichiometry == pytest.approx(3.0)
    # Verify XML root has no leftover arrays namespace attributes.
    root = ET.fromstring(flattened_xml)
    assert not any("arrays" in key for key in root.attrib)
