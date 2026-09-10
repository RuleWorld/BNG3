"""Regression gates ported from the newer Playground SBML parity suite."""

from __future__ import annotations


def _model(xml: str):
    from bionetgen.atomizer.modern import SBMLParser

    return SBMLParser().parse(xml)


def test_sbml_empty_boolean_identities_and_empty_math_are_safe():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core">
      <model id="empty_math">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="c" initialAmount="1"/></listOfSpecies>
        <listOfRules>
          <assignmentRule variable="S">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><and/></apply></math>
          </assignmentRule>
        </listOfRules>
        <listOfFunctionDefinitions>
          <functionDefinition id="empty"><math xmlns="http://www.w3.org/1998/Math/MathML"/></functionDefinition>
        </listOfFunctionDefinitions>
        <listOfInitialAssignments>
          <initialAssignment symbol="S"><math xmlns="http://www.w3.org/1998/Math/MathML"/></initialAssignment>
        </listOfInitialAssignments>
      </model>
    </sbml>"""

    model = _model(xml)

    assert model.rules[0].math == "1"
    assert model.function_definitions["empty"].math == "0"
    assert model.initial_assignments == []
    assert (
        sum(warning["category"] == "missingMath" for warning in model.import_warnings)
        == 2
    )


def test_sbml_event_folding_rejects_mutable_identifiers_and_preserves_false_flag():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core">
      <model id="mutable_event">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="c" initialAmount="0"/></listOfSpecies>
        <listOfParameters>
          <parameter id="x" value="0" constant="false"/>
          <parameter id="y" value="0" constant="false"/>
        </listOfParameters>
        <listOfEvents>
          <event id="E" useValuesFromTriggerTime="false">
            <trigger><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply></math></trigger>
            <listOfEventAssignments>
              <eventAssignment variable="y"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><ci>y</ci><ci>x</ci></apply></math></eventAssignment>
              <eventAssignment variable="x"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></eventAssignment>
            </listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""

    model = _model(xml)
    assert model.events[0].use_values_from_trigger_time is False

    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    assert "time-triggered event(s) translated" not in bngl
    assert "useValuesFromTriggerTime" in bngl or "not constant" in bngl
    assert "@sbml-event" in bngl


def test_sbml_req_package_is_informational():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:req="http://www.sbml.org/sbml/level3/version1/req/version1">
      <model id="requirements"/>
    </sbml>"""

    model = _model(xml)

    assert any(
        warning["category"] == "package:req" for warning in model.import_warnings
    )


def test_sbml_functional_flux_keeps_live_piecewise_condition():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core">
      <model id="piecewise_flux">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="10"/>
          <species id="B" compartment="c"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="fast" value="0.8"/>
          <parameter id="slow" value="0.1"/>
          <parameter id="threshold" value="5"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="r">
            <listOfReactants><speciesReference species="A"/></listOfReactants>
            <listOfProducts><speciesReference species="B"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/>
                <piecewise>
                  <piece><ci>fast</ci><apply><gt/><ci>A</ci><ci>threshold</ci></apply></piece>
                  <otherwise><ci>slow</ci></otherwise>
                </piecewise>
                <ci>A</ci>
              </apply>
            </math></kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    reaction = next(line for line in bngl.splitlines() if line.startswith("  r:"))
    assert "if(" in reaction
    assert "_c_A() > threshold" in reaction
    assert "* _c_A()" not in reaction
