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


def test_sbml_level2_reaction_local_parameters_are_inlined():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level2/version3">
      <model id="level2_local_parameter">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="2"/>
          <species id="B" compartment="c" initialAmount="0"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="r">
            <listOfReactants><speciesReference species="A"/></listOfReactants>
            <listOfProducts><speciesReference species="B"/></listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>k_local</ci><ci>A</ci></apply>
              </math>
              <listOfParameters>
                <parameter id="k_local" value="0.25"/>
              </listOfParameters>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "  r:" in result.bngl
    assert "0.25" in result.bngl
    assert "k_local" not in result.bngl


def test_sbml_rate_of_expands_from_explicit_rate_rule():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core">
      <model id="rate_of_rate_rule">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies>
          <species id="S" compartment="c" initialAmount="0"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="p" value="2" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <rateRule variable="p">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><cn>0.5</cn><ci>p</ci></apply>
            </math>
          </rateRule>
        </listOfRules>
        <listOfReactions>
          <reaction id="r">
            <listOfProducts><speciesReference species="S"/></listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>p</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""

    model = _model(xml)
    assert model.reactions["r"].kinetic_law.math == "(0.5 * p)"

    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    assert "rateOf(" not in bngl
    assert "0.5 * p_amt" in bngl


def test_sbml_rate_of_uses_species_conversion_factor_for_each_derivative():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core">
      <model id="rate_of_mixed_conversion">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="c" initialAmount="1" conversionFactor="s1_factor"/>
          <species id="S2" compartment="c" initialAmount="0" conversionFactor="s2_factor"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="s1_factor" value="2"/>
          <parameter id="s2_factor" value="3"/>
          <parameter id="p" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <assignmentRule variable="p">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><plus/>
                <apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>S1</ci></apply>
                <apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>S2</ci></apply>
              </apply>
            </math>
          </assignmentRule>
        </listOfRules>
        <listOfReactions>
          <reaction id="r">
            <listOfReactants><speciesReference species="S1"/></listOfReactants>
            <listOfProducts><speciesReference species="S2"/></listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><cn>0.5</cn><ci>S1</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""

    model = _model(xml)

    assert "(2)" in model.rules[0].math
    assert "(3)" in model.rules[0].math
    assert "rateOf" not in model.rules[0].math


def test_sbml_rate_of_csymbol_text_is_not_duplicated():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="rate_of_csymbol_text">
        <listOfParameters>
          <parameter id="p1" value="1" constant="false"/>
          <parameter id="p2" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <rateRule variable="p1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math>
          </rateRule>
          <assignmentRule variable="p2">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/rateOf">p1</csymbol><ci>p1</ci></apply>
            </math>
          </assignmentRule>
        </listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)

    assert model.rules[1].math == "(2)"


def test_sbml_rate_of_unruled_mutable_parameter_is_zero():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="rate_of_unruled_parameter">
        <listOfParameters>
          <parameter id="p1" value="1" constant="false"/>
          <parameter id="p2" constant="false"/>
        </listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="p2">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>p1</ci></apply>
            </math>
          </initialAssignment>
        </listOfInitialAssignments>
      </model>
    </sbml>"""

    model = _model(xml)

    assert model.initial_assignments[0].math == "(0)"


def test_sbml_rate_of_species_accounts_for_rate_ruled_compartment_volume():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="rate_of_dynamic_volume">
        <listOfCompartments><compartment id="C" size="1" constant="false"/></listOfCompartments>
        <listOfSpecies><species id="S1" compartment="C" initialConcentration="1"/></listOfSpecies>
        <listOfRules>
          <rateRule variable="C"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1.3</cn></math></rateRule>
          <assignmentRule variable="x"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>S1</ci></apply></math></assignmentRule>
        </listOfRules>
        <listOfParameters><parameter id="x" constant="false"/></listOfParameters>
        <listOfReactions><reaction id="r"><listOfProducts><speciesReference species="S1" stoichiometry="1"/></listOfProducts><kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></kineticLaw></reaction></listOfReactions>
      </model>
    </sbml>"""

    model = _model(xml)

    assert "rateOf" not in model.rules[1].math
    assert "(1) * (2) / (C)" in model.rules[1].math
    assert "(-(S1) * (1.3) / (C))" in model.rules[1].math


def test_sbml_simple_algebraic_rule_lowers_unique_mutable_parameter():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="simple_algebraic_parameter">
        <listOfParameters>
          <parameter id="k1" value="1" constant="true"/>
          <parameter id="k2" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <algebraicRule>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><minus/><ci>k2</ci><cn>0.9</cn></apply>
            </math>
          </algebraicRule>
        </listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)

    assert [(rule.type, rule.variable, rule.math) for rule in model.rules] == [
        ("assignment", "k2", "0.9")
    ]
    assert not any(
        warning["category"] == "algebraicRule"
        for warning in model.import_warnings
    )


def test_sbml_simple_algebraic_rule_lowers_unique_mutable_compartment():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="simple_algebraic_compartment">
        <listOfCompartments>
          <compartment id="cell" size="1" constant="false"/>
        </listOfCompartments>
        <listOfRules><algebraicRule>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><minus/><ci>cell</ci><cn>2</cn></apply>
          </math>
        </algebraicRule></listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)

    assert [(rule.type, rule.variable, rule.math) for rule in model.rules] == [
        ("assignment", "cell", "2")
    ]
    assert not any(
        warning["category"] == "algebraicRule"
        for warning in model.import_warnings
    )


def test_sbml_nonlinear_algebraic_rule_stays_explicitly_unsupported():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="nonlinear_algebraic_parameter">
        <listOfParameters><parameter id="k" constant="false"/></listOfParameters>
        <listOfRules><algebraicRule>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><minus/><apply><power/><ci>k</ci><cn>2</cn></apply><cn>1</cn></apply>
          </math>
        </algebraicRule></listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)

    assert model.rules[0].type == "algebraic"
    assert any(
        warning["category"] == "algebraicRule"
        and warning["severity"] == "dropped"
        for warning in model.import_warnings
    )


def test_sbml_coupled_algebraic_unknowns_stay_explicitly_unsupported():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="coupled_algebraic_parameters">
        <listOfParameters>
          <parameter id="k1" constant="false"/><parameter id="k2" constant="false"/>
        </listOfParameters>
        <listOfRules><algebraicRule>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><minus/><apply><plus/><ci>k1</ci><ci>k2</ci></apply><cn>1</cn></apply>
          </math>
        </algebraicRule></listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)

    assert model.rules[0].type == "algebraic"
    assert any(
        warning["category"] == "algebraicRule"
        and warning["severity"] == "dropped"
        for warning in model.import_warnings
    )


def test_sbml_delay_of_unchanging_parameter_lowers_to_value():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="delay_of_static_parameter">
        <listOfParameters>
          <parameter id="k" value="2" constant="false"/>
          <parameter id="y" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <assignmentRule variable="y">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><plus/><cn>1</cn><apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol><ci>k</ci><cn>5</cn></apply></apply>
            </math>
          </assignmentRule>
        </listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)

    assert model.rules[0].math == "1 + k"
    assert "delay(" not in model.rules[0].math


def test_sbml_rate_of_expands_from_fixed_volume_reaction_flux():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core">
      <model id="rate_of_reaction">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="1" hasOnlySubstanceUnits="true"/>
          <species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true"/>
        </listOfSpecies>
        <listOfParameters><parameter id="p" constant="false"/></listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="p">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>A</ci></apply>
            </math>
          </initialAssignment>
        </listOfInitialAssignments>
        <listOfReactions>
          <reaction id="r">
            <listOfReactants><speciesReference species="A"/></listOfReactants>
            <listOfProducts><speciesReference species="B"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""

    model = _model(xml)
    assert model.initial_assignments[0].math == "((-1) * (2))"

    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    assert "rateOf(" not in bngl


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
