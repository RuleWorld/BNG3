"""Regression gates ported from the newer Playground SBML parity suite."""

from __future__ import annotations

import pytest


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
        warning["category"] == "algebraicRule" for warning in model.import_warnings
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
        warning["category"] == "algebraicRule" for warning in model.import_warnings
    )


def test_sbml_simple_algebraic_rule_lowers_nonparticipant_species():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="simple_algebraic_species">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="1" constant="false"/>
          <species id="B" compartment="c" initialAmount="2" constant="false"/>
          <species id="C" compartment="c" initialAmount="0" constant="false"/>
        </listOfSpecies>
        <listOfParameters><parameter id="k" value="1"/></listOfParameters>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfReactants><speciesReference species="B"/></listOfReactants>
          <listOfProducts><speciesReference species="C"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>B</ci></apply>
          </math></kineticLaw>
        </reaction></listOfReactions>
        <listOfRules><algebraicRule>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><minus/><apply><plus/><ci>A</ci><ci>B</ci></apply><cn>10</cn></apply>
          </math>
        </algebraicRule></listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    assert [(rule.type, rule.variable, rule.math) for rule in model.rules] == [
        ("assignment", "A", "-((B) - (10))")
    ]
    assert "A() = " in bngl
    assert not any(
        warning["category"] == "algebraicRule" for warning in model.import_warnings
    )


def test_sbml_algebraic_species_coefficient_can_use_constant_parameters():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="algebraic_species_constant_coefficient">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="c" initialAmount="0" constant="false"/>
          <species id="T" compartment="c" initialAmount="0" constant="false"/>
          <species id="X" compartment="c" initialAmount="0" constant="false"/>
        </listOfSpecies>
        <listOfParameters><parameter id="k3" value="2.5" constant="true"/></listOfParameters>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfReactants><speciesReference species="T"/></listOfReactants>
          <listOfProducts><speciesReference species="X"/></listOfProducts>
          <listOfModifiers><modifierSpeciesReference species="S1"/></listOfModifiers>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfRules><algebraicRule>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><minus/>
              <apply><times/><apply><plus/><ci>k3</ci><cn>1</cn></apply><ci>S1</ci></apply>
              <ci>T</ci>
            </apply>
          </math>
        </algebraicRule></listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)

    assert [(rule.type, rule.variable, rule.math) for rule in model.rules] == [
        ("assignment", "S1", "-(-(T)) / (3.5)")
    ]
    assert not any(
        warning["category"] == "algebraicRule" for warning in model.import_warnings
    )


def test_sbml_static_species_reference_id_is_global_model_symbol():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="static_species_reference_symbol">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="2"/>
          <species id="B" compartment="c" initialAmount="0"/>
        </listOfSpecies>
        <listOfParameters><parameter id="p" constant="false"/></listOfParameters>
        <listOfRules><assignmentRule variable="p">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>sr</ci><cn>3</cn></apply>
          </math>
        </assignmentRule></listOfRules>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfReactants><speciesReference id="sr" species="A" stoichiometry="2" constant="false"/></listOfReactants>
          <listOfProducts><speciesReference species="B"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
        </reaction></listOfReactions>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    assert model.parameters["sr"].value == 2
    assert "sr" in bngl
    assert not any(
        warning.get("category") == "scope" for warning in model.import_warnings
    )


def test_sbml_function_formal_can_match_reaction_local_parameter_name():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="local_parameter_function_argument">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="2"/>
          <species id="B" compartment="c" initialAmount="0"/>
        </listOfSpecies>
        <listOfFunctionDefinitions><functionDefinition id="twice">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <lambda><bvar><ci>k</ci></bvar><apply><times/><ci>k</ci><cn>2</cn></apply></lambda>
          </math>
        </functionDefinition></listOfFunctionDefinitions>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfReactants><speciesReference species="A"/>
          </listOfReactants><listOfProducts><speciesReference species="B"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><apply><ci>twice</ci><ci>k</ci></apply><ci>A</ci></apply>
          </math><listOfLocalParameters><localParameter id="k" value="0.25"/></listOfLocalParameters></kineticLaw>
        </reaction></listOfReactions>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    generate_bngl(model, sct, get_molecule_types(sct), get_seed_species(sct, model))

    assert not any(
        warning.get("category") == "scope" for warning in model.import_warnings
    )


def test_sbml_rate_ruled_species_reference_remains_dynamic():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="dynamic_species_reference_symbol">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfParameters><parameter id="p" value="0" constant="false"/></listOfParameters>
        <listOfSpecies><species id="A" compartment="c" initialAmount="2"/></listOfSpecies>
        <listOfRules><rateRule variable="sr">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.1</cn></math>
        </rateRule></listOfRules>
        <listOfEvents><event id="uses_dynamic_reference">
          <trigger><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply>
          </math></trigger>
          <listOfEventAssignments><eventAssignment variable="p">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>sr</ci></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfReactants><speciesReference id="sr" species="A" stoichiometry="2" constant="false"/></listOfReactants>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
        </reaction></listOfReactions>
      </model>
    </sbml>"""

    model = _model(xml)

    assert model.reactions["r"].reactants[0].variable_stoichiometry
    assert "sr" not in model.parameters
    sct = build_species_composition_table(model)
    generate_bngl(model, sct, get_molecule_types(sct), get_seed_species(sct, model))
    assert not any(
        warning.get("category") == "scope" for warning in model.import_warnings
    )
    assert any(
        warning.get("category") == "stoichiometry" for warning in model.import_warnings
    )


def test_sbml_fixed_fractional_stoichiometry_lowers_to_deterministic_flux_rules():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="fixed_fractional_stoichiometry">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="2"/>
          <species id="B" compartment="c" initialAmount="0"/>
        </listOfSpecies>
        <listOfParameters><parameter id="k" value="0.25"/></listOfParameters>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfReactants><speciesReference species="A" stoichiometry="1"/></listOfReactants>
          <listOfProducts><speciesReference species="B" stoichiometry="0.5"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math></kineticLaw>
        </reaction></listOfReactions>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    result = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    assert "r_consume_A: @c:M_A() -> 0" in result.bngl
    assert "r_produce_B: 0 -> @c:M_B()" in result.bngl
    assert "TotalRate" in result.bngl
    assert not any(
        line.startswith("  r_") and "if(" in line for line in result.bngl.splitlines()
    )
    assert any(
        warning.get("category") == "stoichiometry" and warning.get("severity") == "info"
        for warning in model.import_warnings
    )

    fast_model = _model(
        xml.replace(
            'reaction id="r" reversible="false"',
            'reaction id="r" reversible="false" fast="true"',
        )
    )
    fast_sct = build_species_composition_table(fast_model)
    fast_result = generate_bngl(
        fast_model,
        fast_sct,
        get_molecule_types(fast_sct),
        get_seed_species(fast_sct, fast_model),
    )
    assert "r_consume_A" not in fast_result.bngl
    assert any(
        warning.get("category") == "stoichiometry"
        and warning.get("severity") == "dropped"
        for warning in fast_model.import_warnings
    )


def test_sbml_static_species_reference_assignment_becomes_numeric_parameter():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="assigned_species_reference_symbol">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies><species id="A" compartment="c" initialAmount="2"/></listOfSpecies>
        <listOfInitialAssignments><initialAssignment symbol="sr">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>4</cn></math>
        </initialAssignment></listOfInitialAssignments>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfReactants><speciesReference id="sr" species="A" stoichiometry="2" constant="false"/></listOfReactants>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
        </reaction></listOfReactions>
      </model>
    </sbml>"""

    model = _model(xml)

    assert model.parameters["sr"].value == 4
    assert not model.reactions["r"].reactants[0].variable_stoichiometry
    assert not model.initial_assignments


def test_event_target_species_reference_initial_assignment_stays_dynamic():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="event_target_species_reference_initial_assignment">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies><species id="A" compartment="c" initialAmount="1"/></listOfSpecies>
        <listOfInitialAssignments><initialAssignment symbol="sr">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math>
        </initialAssignment></listOfInitialAssignments>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfProducts><speciesReference id="sr" species="A" stoichiometry="4" constant="false"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="change_stoichiometry">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="sr">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    result = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    parameters = result.bngl.split("begin parameters\n", 1)[1].split(
        "\nend parameters", 1
    )[0]
    functions = result.bngl.split("begin functions\n", 1)[1].split(
        "\nend functions", 1
    )[0]
    assert "sr 2" in {line.strip() for line in parameters.splitlines()}
    assert "sr 4" not in {line.strip() for line in parameters.splitlines()}
    assert "sr() =" not in functions
    assert 'setParameter("sr", "3")' in result.bngl


def test_event_target_parameter_initial_assignment_stays_dynamic(tmp_path):
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="event_target_parameter_initial_assignment">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="2"/>
          <species id="B" compartment="c" initialAmount="0"/>
        </listOfSpecies>
        <listOfParameters><parameter id="p" value="4" constant="false"/></listOfParameters>
        <listOfInitialAssignments><initialAssignment symbol="p">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math>
        </initialAssignment></listOfInitialAssignments>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfReactants><speciesReference species="A"/></listOfReactants>
          <listOfProducts><speciesReference species="B"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>p</ci><ci>A</ci></apply>
          </math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="change_parameter">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="p">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    result = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    parameters = result.bngl.split("begin parameters\n", 1)[1].split(
        "\nend parameters", 1
    )[0]
    functions = result.bngl.split("begin functions\n", 1)[1].split(
        "\nend functions", 1
    )[0]
    assert model.parameters["p"].value == 2
    assert "p 2" in {line.strip() for line in parameters.splitlines()}
    assert "p 4" not in {line.strip() for line in parameters.splitlines()}
    assert "p() =" not in functions
    assert 'setParameter("p", "3")' in result.bngl

    import numpy as np

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    atomized = Atomizer(quiet_mode=True, t_end=2, n_steps=200).atomize(xml)
    assert atomized.success, atomized.error
    assert "Events NOT simulated" not in atomized.bngl
    model_path = tmp_path / "event_target_parameter_initial_assignment.bngl"
    model_path.write_text(atomized.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])

    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-9)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", "A"]
    reference = rr.simulate(times=bng_data[:, columns.index("time")])
    jump = int(np.argmin(np.abs(bng_data[:, columns.index("time")] - 1.0)))
    compare = np.ones(len(bng_data), dtype=bool)
    compare[max(0, jump - 1) : min(len(bng_data), jump + 2)] = False
    bng_values = bng_data[compare, columns.index("A_amt")]
    rr_values = reference[compare, reference.colnames.index("A")]
    assert np.max(np.abs(bng_values - rr_values)) <= 1e-7


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
        warning["category"] == "algebraicRule" and warning["severity"] == "dropped"
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
        warning["category"] == "algebraicRule" and warning["severity"] == "dropped"
        for warning in model.import_warnings
    )


def test_sbml_linear_algebraic_rule_can_define_unreacted_boundary_species():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="algebraic_boundary_species">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="c" initialAmount="1"/>
          <species id="S2" compartment="c" initialAmount="0"/>
          <species id="S4" compartment="c" initialAmount="1" boundaryCondition="true"/>
        </listOfSpecies>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfReactants><speciesReference species="S1" stoichiometry="1"/></listOfReactants>
          <listOfProducts><speciesReference species="S2" stoichiometry="1"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfRules><algebraicRule>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><minus/><ci>S4</ci><ci>S1</ci></apply>
          </math>
        </algebraicRule></listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)

    assert model.rules[0].type == "assignment"
    assert model.rules[0].variable == "S4"
    assert "S4" not in model.rules[0].math
    assert "S1" in model.rules[0].math


def test_constant_reaction_flux_state_threshold_lowers_exact_crossing():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="constant_flux_event_crossing">
        <listOfCompartments><compartment id="c" size="2" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="0" hasOnlySubstanceUnits="false"/>
          <species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="false"/>
        </listOfSpecies>
        <listOfParameters><parameter id="P" value="0" constant="false"/></listOfParameters>
        <listOfReactions><reaction id="source" reversible="false">
          <listOfProducts><speciesReference species="A" stoichiometry="1"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="threshold">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><geq/><ci>A</ci><cn>1</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="P">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>7</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "t_end=>1" in result.bngl
    assert 'setParameter("P", "7")' in result.bngl
    assert "untranslated" not in result.bngl.lower()


def test_first_order_reaction_threshold_lowers_exponential_crossing():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="first_order_event_crossing">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="4" hasOnlySubstanceUnits="false"/>
          <species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k" value="0.5" constant="true"/>
          <parameter id="P" value="0" constant="false"/>
        </listOfParameters>
        <listOfReactions><reaction id="decay" reversible="false">
          <listOfReactants><speciesReference species="A" stoichiometry="1"/></listOfReactants>
          <listOfProducts><speciesReference species="B" stoichiometry="1"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="threshold">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><leq/><ci>A</ci><cn>2</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="P">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>A</ci></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "t_end=>1.38629436112" in result.bngl
    assert 'setParameter("P", "2")' in result.bngl
    assert "untranslated" not in result.bngl.lower()


def test_rate_of_exponential_parameter_lowers_exact_event_crossing():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="exponential_parameter_event_crossing">
        <listOfParameters>
          <parameter id="p" value="1" constant="false"/>
          <parameter id="k" value="0.01" constant="true"/>
          <parameter id="out" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules><rateRule variable="p">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>p</ci></apply>
          </math>
        </rateRule></listOfRules>
        <listOfEvents><event id="threshold">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><geq/><apply><times/><cn>0.01</cn><ci>p</ci></apply><cn>0.015</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="out">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>5</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "t_end=>40.5465108108" in result.bngl
    assert 'setParameter("out", "5")' in result.bngl
    assert "untranslated" not in result.bngl.lower()


def test_compound_constant_scale_of_exponential_reaction_state_lowers_event():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="scaled_exponential_reaction_event">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="c" initialAmount="1"/>
          <species id="outSpecies" compartment="c" initialAmount="0"/></listOfSpecies>
        <listOfParameters><parameter id="k" value="0.1" constant="true"/>
          <parameter id="out" value="0" constant="false"/></listOfParameters>
        <listOfReactions><reaction id="growth" reversible="false">
          <listOfProducts><speciesReference species="S" stoichiometry="1"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>S</ci></apply>
          </math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="threshold">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><geq/><apply><divide/><apply><times/><cn>10</cn><ci>k</ci><ci>S</ci></apply><cn>2</cn></apply><cn>0.525</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="out">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>7</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "t_end=>0.487901641694" in result.bngl
    assert 'setParameter("out", "7")' in result.bngl
    assert "untranslated" not in result.bngl.lower()


def test_delayed_event_evaluates_assignment_rule_at_execution_time():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="delayed_event_assignment_rule_execution_value">
        <listOfParameters>
          <parameter id="p" value="0" constant="false"/>
          <parameter id="k2" constant="false"/>
          <parameter id="out" value="1" constant="false"/>
        </listOfParameters>
        <listOfRules><rateRule variable="p">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
        </rateRule><assignmentRule variable="k2">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>p</ci></math>
        </assignmentRule></listOfRules>
        <listOfEvents><event id="threshold" useValuesFromTriggerTime="false">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><gt/><ci>p</ci><cn>4.5</cn></apply>
            </math>
          </trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></delay>
          <listOfEventAssignments><eventAssignment variable="out">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k2</ci></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=10).atomize(xml)

    assert result.success, result.error
    assert "t_end=>6.5" in result.bngl
    assert 'setParameter("out", "6.5")' in result.bngl
    assert "state-dependent or non-constant event" not in result.bngl


def test_single_variable_algebraic_rule_lowers_for_initial_event_trigger():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="single_variable_algebraic_event">
        <listOfParameters>
          <parameter id="k" value="0" constant="false"/>
          <parameter id="out" value="1" constant="false"/>
        </listOfParameters>
        <listOfRules><algebraicRule>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><minus/><cn>10</cn><ci>k</ci></apply>
          </math>
        </algebraicRule></listOfRules>
        <listOfEvents><event id="initial" useValuesFromTriggerTime="true">
          <trigger initialValue="false" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><gt/><ci>k</ci><cn>4.5</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="out">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert 'setParameter("out", "3")' in result.bngl
    assert "algebraic rule(s) present" not in result.bngl
    assert "state-dependent or non-constant event" not in result.bngl


def test_static_assignment_rule_parameter_resolves_exponential_event_rate():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="algebraic_rate_event">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/>
          <species id="S2" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k2" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules><algebraicRule>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><plus/><ci>k2</ci><cn>-2.5</cn></apply>
          </math>
        </algebraicRule></listOfRules>
        <listOfReactions><reaction id="decay" reversible="false">
          <listOfReactants><speciesReference species="S1"/></listOfReactants>
          <listOfProducts><speciesReference species="S2"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k2</ci><ci>S1</ci></apply>
          </math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="threshold" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><lt/><ci>S1</ci><cn>0.25</cn></apply>
            </math>
          </trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></delay>
          <listOfEventAssignments><eventAssignment variable="S2">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.75</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=3).atomize(xml)

    assert result.success, result.error
    assert "not a simple time threshold" not in result.bngl
    assert "t_end=>1.554" in result.bngl
    assert 'setConcentration("@C:M_S2()", "0.75")' in result.bngl

    dynamic_rule_xml = (
        xml.replace("<algebraicRule>", '<assignmentRule variable="k2">')
        .replace("</algebraicRule>", "</assignmentRule>")
        .replace(
            "<apply><plus/><ci>k2</ci><cn>-2.5</cn></apply>",
            "<ci>time</ci>",
        )
    )
    dynamic_result = Atomizer(quiet_mode=True, t_end=3).atomize(dynamic_rule_xml)
    assert dynamic_result.success, dynamic_result.error
    assert "not a simple time threshold" in dynamic_result.bngl


def test_conjunctive_event_outside_horizon_is_safely_omitted():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="conjunctive_event_after_horizon">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/>
          <species id="S2" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"/>
        </listOfSpecies>
        <listOfParameters><parameter id="k" value="1" constant="true"/></listOfParameters>
        <listOfReactions><reaction id="decay" reversible="false">
          <listOfReactants><speciesReference species="S1"/></listOfReactants>
          <listOfProducts><speciesReference species="S2"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>S1</ci></apply>
          </math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="threshold" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><and/>
                <apply><lt/><ci>S1</ci><cn>0.1</cn></apply>
                <apply><lt/><ci>S2</ci><cn>0.95</cn></apply>
              </apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="S1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=1).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert "begin actions" not in result.bngl

    longer_result = Atomizer(quiet_mode=True, t_end=3).atomize(xml)
    assert longer_result.success, longer_result.error
    assert "state-dependent or non-constant event" in longer_result.bngl


def test_event_controls_deterministic_species_reference_flux():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="event_controlled_deterministic_stoichiometry">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="X" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/></listOfSpecies>
        <listOfParameters>
          <parameter id="p1" value="1" constant="false"/>
          <parameter id="k1" value="1" constant="true"/>
        </listOfParameters>
        <listOfRules><assignmentRule variable="Xref">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>p1</ci></math>
        </assignmentRule></listOfRules>
        <listOfReactions><reaction id="source" reversible="false">
          <listOfProducts><speciesReference id="Xref" species="X" constant="false"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k1</ci></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="threshold" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><geq/><ci>X</ci><cn>2</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="p1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=1.5).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert "t_end=>1" in result.bngl
    assert 'setParameter("p1", "2")' in result.bngl


def test_periodic_species_reference_events_prove_reaction_species_threshold_inactive():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="periodic_stoichiometry_keeps_species_static">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="C" initialAmount="0"/></listOfSpecies>
        <listOfParameters>
          <parameter id="reset" value="0" constant="false"/>
          <parameter id="Q" value="1" constant="false"/>
          <parameter id="R" value="1" constant="false"/>
          <parameter id="error" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules><rateRule variable="reset">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
        </rateRule></listOfRules>
        <listOfEvents>
          <event id="increment_Q" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="false">
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><geq/><ci>reset</ci><cn>0.01</cn></apply>
              </math>
            </trigger>
            <listOfEventAssignments>
              <eventAssignment variable="reset"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0</cn></math></eventAssignment>
              <eventAssignment variable="Q"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><ci>Q</ci><cn>0.01</cn></apply></math></eventAssignment>
            </listOfEventAssignments>
          </event>
          <event id="increment_R" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="false">
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><geq/><ci>reset</ci><cn>0.01</cn></apply>
              </math>
            </trigger>
            <listOfEventAssignments>
              <eventAssignment variable="reset"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0</cn></math></eventAssignment>
              <eventAssignment variable="R"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><ci>R</ci><cn>0.01</cn></apply></math></eventAssignment>
            </listOfEventAssignments>
          </event>
          <event id="threshold">
            <trigger initialValue="true" persistent="true">
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><geq/><apply><abs/><ci>S</ci></apply><cn>0.001</cn></apply>
              </math>
            </trigger>
            <listOfEventAssignments>
              <eventAssignment variable="error"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></eventAssignment>
            </listOfEventAssignments>
          </event>
        </listOfEvents>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfReactants><speciesReference id="Q" species="S" constant="false"/></listOfReactants>
          <listOfProducts><speciesReference id="R" species="S" constant="false"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.1</cn></math></kineticLaw>
        </reaction></listOfReactions>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=0.025, n_steps=10).atomize(xml)

    assert result.success, result.error
    assert (
        "state-dependent or non-constant event(s) remain untranslated"
        not in result.bngl
    )
    assert 'setParameter("error", "1")' not in result.bngl

    changing_species_xml = xml.replace(
        "</listOfEvents>",
        """<event id="change_S">
          <trigger><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>0.015</cn></apply>
          </math></trigger>
          <listOfEventAssignments><eventAssignment variable="S">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.002</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>""",
    )
    changing_species = Atomizer(quiet_mode=True, t_end=0.025, n_steps=10).atomize(
        changing_species_xml
    )

    assert changing_species.success, changing_species.error
    assert (
        "state-dependent or non-constant event(s) remain untranslated"
        in changing_species.bngl
    )


def _quadratic_reentrant_event_model(delay=None):
    delay_element = (
        ""
        if delay is None
        else f"""<delay><math xmlns="http://www.w3.org/1998/Math/MathML">
          <cn>{delay}</cn></math></delay>"""
    )
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="quadratic_reentrant_event">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/>
          <species id="B" compartment="C" initialAmount="2" hasOnlySubstanceUnits="true"/>
          <species id="D" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k1" value="0.75" constant="true"/>
          <parameter id="k2" value="0.25" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="bind" reversible="false">
            <listOfReactants><speciesReference species="A"/><speciesReference species="B"/></listOfReactants>
            <listOfProducts><speciesReference species="D"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>C</ci><ci>k1</ci><ci>A</ci><ci>B</ci></apply></math></kineticLaw>
          </reaction>
          <reaction id="unbind" reversible="false">
            <listOfReactants><speciesReference species="D"/></listOfReactants>
            <listOfProducts><speciesReference species="A"/><speciesReference species="B"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>C</ci><ci>k2</ci><ci>D</ci></apply></math></kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents><event id="reset" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><lt/><ci>A</ci><cn>0.75</cn></apply></math>
          </trigger>
          {delay_element}
          <listOfEventAssignments>
            <eventAssignment variable="B"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1.5</cn></math></eventAssignment>
            <eventAssignment variable="A"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></eventAssignment>
          </listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""


def test_quadratic_state_event_repeats_after_trigger_species_reset():
    from bionetgen.atomizer.modern import Atomizer

    xml = _quadratic_reentrant_event_model()
    result = Atomizer(quiet_mode=True, t_end=10, n_steps=100).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert "# 7 time-triggered SBML event(s) translated" in result.bngl
    assert result.bngl.count("setConcentration(") == 14


def test_delayed_quadratic_state_events_recur_and_match_libroadrunner(tmp_path):
    import numpy as np
    import pytest

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = _quadratic_reentrant_event_model(delay=1.5)
    result = Atomizer(quiet_mode=True, t_end=20, n_steps=1200).atomize(xml)

    assert result.success, result.error
    assert "Events NOT simulated" not in result.bngl

    model_path = tmp_path / "delayed_quadratic_reentrant.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])
    times = bng_data[:, columns.index("time")]

    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-9)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", "[A]", "[B]", "[D]"]
    reference = rr.simulate(times=times)

    state_columns = [columns.index(species) for species in ("A", "B", "D")]
    changes = np.abs(np.diff(bng_data[:, state_columns], axis=0))
    jump_indices = np.flatnonzero(np.max(changes, axis=1) > 0.2)
    assert len(jump_indices) >= 1
    compare = np.ones(len(times), dtype=bool)
    compare[jump_indices] = False
    compare[jump_indices + 1] = False
    for species in ("A", "B", "D"):
        bng_values = bng_data[compare, columns.index(species)]
        rr_values = reference[compare, reference.colnames.index(f"[{species}]")]
        scale = max(float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values))))
        assert float(np.max(np.abs(bng_values - rr_values))) <= max(5e-12, 1e-6 * scale)


def test_quadratic_state_event_resolves_species_initial_assignments(tmp_path):
    import numpy as np
    import pytest

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = _quadratic_reentrant_event_model()
    xml = xml.replace('initialAmount="2"', 'initialAmount="5"')
    xml = xml.replace(
        "</listOfParameters>",
        '<parameter id="p1" value="0.5" constant="true"/></listOfParameters>',
    )
    xml = xml.replace(
        "<listOfReactions>",
        """<listOfInitialAssignments>
          <initialAssignment symbol="B"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><divide/><ci>A</ci><ci>p1</ci></apply>
          </math></initialAssignment>
        </listOfInitialAssignments><listOfReactions>""",
    )
    result = Atomizer(quiet_mode=True, t_end=10, n_steps=600).atomize(xml)

    assert result.success, result.error
    assert "Events NOT simulated" not in result.bngl

    model_path = tmp_path / "quadratic_event_with_species_initial_assignment.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])
    times = bng_data[:, columns.index("time")]

    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-9)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", "[A]", "[B]", "[D]"]
    reference = rr.simulate(times=times)

    state_columns = [columns.index(species) for species in ("A", "B", "D")]
    changes = np.abs(np.diff(bng_data[:, state_columns], axis=0))
    jump_indices = np.flatnonzero(np.max(changes, axis=1) > 0.2)
    assert len(jump_indices) >= 1
    compare = np.ones(len(times), dtype=bool)
    compare[jump_indices] = False
    compare[jump_indices + 1] = False
    for species in ("A", "B", "D"):
        bng_values = bng_data[compare, columns.index(species)]
        rr_values = reference[compare, reference.colnames.index(f"[{species}]")]
        scale = max(float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values))))
        assert float(np.max(np.abs(bng_values - rr_values))) <= max(5e-12, 1e-6 * scale)


def _independent_component_quadratic_event_model(
    *, coupled_rate: bool = False, reverse_reaction: bool = False, delay: float = 0
) -> str:
    rate = """<apply><times/><ci>C</ci><apply><plus/>
              <apply><times/><ci>kf</ci><ci>S1</ci></apply>
              <apply><times/><cn>-1</cn><ci>kr</ci><ci>S2</ci></apply>
            </apply></apply>"""
    if coupled_rate:
        rate = rate.replace(
            "<ci>kf</ci><ci>S1</ci>", "<ci>kf</ci><ci>S1</ci><ci>S3</ci>"
        )
    reactant, product = "S1", "S2"
    if reverse_reaction:
        rate = f"<apply><minus/>{rate}</apply>"
        reactant, product = product, reactant
    delay_xml = (
        f'<delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>{delay}</cn></math></delay>'
        if delay
        else ""
    )
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="independent_component_quadratic_event">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false"/>
          <species id="S2" compartment="C" initialAmount="2" hasOnlySubstanceUnits="false"/>
          <species id="S3" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false"/>
          <species id="S4" compartment="C" initialAmount="1.5" hasOnlySubstanceUnits="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="kf" value="0.9" constant="true"/>
          <parameter id="kr" value="0.075" constant="true"/>
          <parameter id="k1" value="0.75" constant="true"/>
          <parameter id="k2" value="0.15" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="trigger_component" reversible="true">
            <listOfReactants><speciesReference species="{reactant}"/></listOfReactants>
            <listOfProducts><speciesReference species="{product}"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">{rate}</math></kineticLaw>
          </reaction>
          <reaction id="independent_component" reversible="true">
            <listOfReactants><speciesReference species="S3"/></listOfReactants>
            <listOfProducts><speciesReference species="S4"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci>C</ci><apply><plus/>
                <apply><times/><ci>k1</ci><ci>S3</ci></apply>
                <apply><times/><cn>-1</cn><ci>k2</ci><ci>S4</ci></apply>
              </apply></apply>
            </math></kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents><event id="threshold" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><lt/><ci>S1</ci><cn>0.5</cn></apply>
            </math>
          </trigger>
          {delay_xml}
          <listOfEventAssignments>
            <eventAssignment variable="S2">
              <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1.5</cn></math>
            </eventAssignment>
            <eventAssignment variable="S4">
              <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>S2</ci></math>
            </eventAssignment>
          </listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""


def test_quadratic_state_event_ignores_an_independent_dynamic_component():
    from bionetgen.atomizer.modern import Atomizer

    result = Atomizer(quiet_mode=True, t_end=5, n_steps=50).atomize(
        _independent_component_quadratic_event_model()
    )

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert "# 1 time-triggered SBML event(s) translated" in result.bngl
    assert result.bngl.count("setConcentration(") == 2
    assert 'setConcentration("@C:M_S4()", "2.5")' in result.bngl


def test_quadratic_independent_component_supports_delayed_reversed_reaction():
    from bionetgen.atomizer.modern import Atomizer

    result = Atomizer(quiet_mode=True, t_end=5, n_steps=50).atomize(
        _independent_component_quadratic_event_model(reverse_reaction=True, delay=1.89)
    )

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert "# 1 time-triggered SBML event(s) translated" in result.bngl
    assert result.bngl.count("setConcentration(") == 2
    assert 'setConcentration("@C:M_S4()", "2.5")' in result.bngl


def test_quadratic_state_event_is_not_horizon_proven_for_ssa_actions():
    from bionetgen.atomizer.modern import Atomizer

    result = Atomizer(
        quiet_mode=True,
        t_end=1,
        n_steps=10,
        actions='simulate({method=>"ssa", t_end=>1, n_steps=>10})',
    ).atomize(_independent_component_quadratic_event_model())

    assert result.success, result.error
    assert (
        "proven to make no state changes through the configured simulation horizon"
        not in result.bngl
    )
    assert (
        "state-triggered SBML events require stochastic jump scheduling" in result.bngl
    )
    assert "Events NOT simulated" in result.bngl


def test_quadratic_state_event_rejects_kinetic_coupling_to_an_independent_component():
    from bionetgen.atomizer.modern import Atomizer

    result = Atomizer(quiet_mode=True, t_end=5, n_steps=50).atomize(
        _independent_component_quadratic_event_model(coupled_rate=True)
    )

    assert result.success, result.error
    assert "state-dependent or non-constant event" in result.bngl
    assert "Events NOT simulated" in result.bngl


def _independent_quadratic_event_pair_model(
    delay_first: float = 0, delay_second: float = 0
) -> str:
    def delay_element(value: float) -> str:
        if value == 0:
            return ""
        return f"""<delay><math xmlns="http://www.w3.org/1998/Math/MathML">
          <cn>{value}</cn></math></delay>"""

    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="independent_quadratic_event_pair">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false"/>
          <species id="S2" compartment="C" initialAmount="2" hasOnlySubstanceUnits="false"/>
          <species id="S3" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false"/>
          <species id="S4" compartment="C" initialAmount="1.5" hasOnlySubstanceUnits="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="kf" value="0.9" constant="true"/>
          <parameter id="kr" value="0.075" constant="true"/>
          <parameter id="k1" value="0.75" constant="true"/>
          <parameter id="k2" value="0.15" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="first_pair" reversible="true">
            <listOfReactants><speciesReference species="S1"/></listOfReactants>
            <listOfProducts><speciesReference species="S2"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/>
              <ci>C</ci><apply><plus/><apply><times/><ci>kf</ci><ci>S1</ci></apply>
                <apply><times/><cn>-1</cn><ci>kr</ci><ci>S2</ci></apply></apply>
            </apply></math></kineticLaw>
          </reaction>
          <reaction id="second_pair" reversible="true">
            <listOfReactants><speciesReference species="S3"/></listOfReactants>
            <listOfProducts><speciesReference species="S4"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/>
              <ci>C</ci><apply><plus/><apply><times/><ci>k1</ci><ci>S3</ci></apply>
                <apply><times/><cn>-1</cn><ci>k2</ci><ci>S4</ci></apply></apply>
            </apply></math></kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents>
          <event id="first_threshold" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><lt/><ci>S1</ci><cn>0.5</cn></apply>
            </math></trigger>
            {delay_element(delay_first)}
            <listOfEventAssignments><eventAssignment variable="S2">
              <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1.5</cn></math>
            </eventAssignment></listOfEventAssignments>
          </event>
          <event id="second_threshold" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><lt/><ci>S3</ci><cn>0.75</cn></apply>
            </math></trigger>
            {delay_element(delay_second)}
            <listOfEventAssignments><eventAssignment variable="S4">
              <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.5</cn></math>
            </eventAssignment></listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""


def _quadratic_event_with_downstream_decay_model() -> str:
    return """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="quadratic_event_with_downstream_decay">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/>
          <species id="B" compartment="C" initialAmount="2" hasOnlySubstanceUnits="true"/>
          <species id="P" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"/>
          <species id="Q" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k" value="0.5" constant="true"/>
          <parameter id="kd" value="0.25" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="combine" reversible="false">
            <listOfReactants>
              <speciesReference species="A" stoichiometry="1"/>
              <speciesReference species="B" stoichiometry="1"/>
            </listOfReactants>
            <listOfProducts><speciesReference species="P" stoichiometry="1"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/>
              <ci>k</ci><ci>A</ci><ci>B</ci>
            </apply></math></kineticLaw>
          </reaction>
          <reaction id="decay" reversible="false">
            <listOfReactants><speciesReference species="P" stoichiometry="1"/></listOfReactants>
            <listOfProducts><speciesReference species="Q" stoichiometry="1"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/>
              <ci>kd</ci><ci>P</ci>
            </apply></math></kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents>
          <event id="reset_reactants" useValuesFromTriggerTime="false">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><lt/><ci>A</ci><cn>0.5</cn></apply>
            </math></trigger>
            <listOfEventAssignments>
              <eventAssignment variable="B"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></eventAssignment>
            </listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""


def test_quadratic_event_ignores_downstream_decay_reactions(tmp_path):
    import numpy as np
    import pytest

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = _quadratic_event_with_downstream_decay_model()
    result = Atomizer(quiet_mode=True, t_end=4, n_steps=400).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert "Events NOT simulated" not in result.bngl
    assert result.bngl.count('setConcentration("@C:M_B()", "1")') == 1

    model_path = tmp_path / "quadratic_event_with_downstream_decay.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])
    times = bng_data[:, columns.index("time")]

    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-9)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", "A", "B", "P", "Q"]
    reference = rr.simulate(times=times)
    event_times = [np.log(1.5) / 0.5]
    away_from_events = np.logical_and.reduce(
        [np.abs(times - event_time) > 1e-6 for event_time in event_times]
    )
    for species in ("A", "B", "P", "Q"):
        bng_values = bng_data[away_from_events, columns.index(species)]
        rr_values = reference[away_from_events, reference.colnames.index(species)]
        scale = max(float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values))))
        assert float(np.max(np.abs(bng_values - rr_values))) <= max(1e-10, 2e-5 * scale)


def test_quadratic_event_rejects_other_reactions_changing_a_rate_species():
    from bionetgen.atomizer.modern import Atomizer

    xml = (
        _quadratic_event_with_downstream_decay_model()
        .replace(
            '<listOfReactants><speciesReference species="P" stoichiometry="1"/></listOfReactants>',
            '<listOfReactants><speciesReference species="B" stoichiometry="1"/></listOfReactants>',
        )
        .replace("<ci>kd</ci><ci>P</ci>", "<ci>kd</ci><ci>B</ci>")
    )
    result = Atomizer(quiet_mode=True, t_end=4, n_steps=400).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" in result.bngl
    assert "Events NOT simulated" in result.bngl


def test_quadratic_state_events_ignore_unrelated_event_assignments(tmp_path):
    import numpy as np
    import pytest

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = _independent_quadratic_event_pair_model(delay_first=2, delay_second=2.5)
    result = Atomizer(quiet_mode=True, t_end=5, n_steps=500).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert "Events NOT simulated" not in result.bngl
    assert 'setConcentration("@C:M_S2()", "1.5")' in result.bngl
    assert 'setConcentration("@C:M_S4()", "0.5")' in result.bngl

    model_path = tmp_path / "independent_event_pair.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])
    times = bng_data[:, columns.index("time")]

    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-7)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", "[S1]", "[S2]", "[S3]", "[S4]"]
    reference = rr.simulate(times=times)
    first_equilibrium = 3 * 0.075 / (0.9 + 0.075)
    second_equilibrium = 2.5 * 0.15 / (0.75 + 0.15)
    first_trigger = np.log((1 - first_equilibrium) / (0.5 - first_equilibrium)) / 0.975
    second_trigger = (
        np.log((1 - second_equilibrium) / (0.75 - second_equilibrium)) / 0.9
    )
    action_times = (first_trigger + 2, second_trigger + 2.5)
    compare = np.logical_and.reduce(
        [np.abs(times - action_time) > 1e-8 for action_time in action_times]
    )
    for species in ("S1", "S2", "S3", "S4"):
        bng_values = bng_data[compare, columns.index(species)]
        rr_values = reference[compare, reference.colnames.index(f"[{species}]")]
        scale = max(float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values))))
        assert float(np.max(np.abs(bng_values - rr_values))) <= max(5e-12, 1e-5 * scale)


def test_quadratic_state_events_keep_cross_component_controls_unsupported():
    from bionetgen.atomizer.modern import Atomizer

    xml = _independent_quadratic_event_pair_model().replace(
        "<apply><times/><ci>kf</ci><ci>S1</ci></apply>",
        "<apply><times/><ci>kf</ci><ci>S1</ci><ci>S3</ci></apply>",
    )
    result = Atomizer(quiet_mode=True, t_end=5, n_steps=500).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" in result.bngl
    assert "Events NOT simulated" in result.bngl


def _first_order_cycle_reentrant_event_model(
    delay=None,
    simultaneous_assignments=False,
    rates=(0.75, 0.55, 0.25),
):
    delay_element = (
        ""
        if delay is None
        else f"""<delay><math xmlns="http://www.w3.org/1998/Math/MathML">
          <cn>{delay}</cn></math></delay>"""
    )
    assignments = (
        """<eventAssignment variable="S2"><math xmlns="http://www.w3.org/1998/Math/MathML">
          <ci>S3</ci></math></eventAssignment>
          <eventAssignment variable="S1"><math xmlns="http://www.w3.org/1998/Math/MathML">
          <ci>S2</ci></math></eventAssignment>
          <eventAssignment variable="S3"><math xmlns="http://www.w3.org/1998/Math/MathML">
          <ci>S1</ci></math></eventAssignment>"""
        if simultaneous_assignments
        else """<eventAssignment variable="S2"><math xmlns="http://www.w3.org/1998/Math/MathML">
          <cn>1.5</cn></math></eventAssignment>
          <eventAssignment variable="S1"><math xmlns="http://www.w3.org/1998/Math/MathML">
          <ci>S2</ci></math></eventAssignment>"""
    )
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="first_order_cycle_reentrant_event">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false"/>
          <species id="S2" compartment="C" initialAmount="2" hasOnlySubstanceUnits="false"/>
          <species id="S3" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k1" value="{rates[0]}" constant="true"/>
          <parameter id="k2" value="{rates[1]}" constant="true"/>
          <parameter id="k3" value="{rates[2]}" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="r1" reversible="false">
            <listOfReactants><speciesReference species="S1"/></listOfReactants>
            <listOfProducts><speciesReference species="S2"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci>C</ci><ci>k1</ci><ci>S1</ci></apply>
            </math></kineticLaw>
          </reaction>
          <reaction id="r2" reversible="false">
            <listOfReactants><speciesReference species="S2"/></listOfReactants>
            <listOfProducts><speciesReference species="S3"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci>C</ci><ci>k2</ci><ci>S2</ci></apply>
            </math></kineticLaw>
          </reaction>
          <reaction id="r3" reversible="false">
            <listOfReactants><speciesReference species="S3"/></listOfReactants>
            <listOfProducts><speciesReference species="S1"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci>C</ci><ci>k3</ci><ci>S3</ci></apply>
            </math></kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents><event id="reset_cycle" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><lt/><ci>S1</ci><cn>0.75</cn></apply>
            </math>
          </trigger>
          {delay_element}
          <listOfEventAssignments>{assignments}</listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""


def _shared_quadratic_event_pair_model(
    time_assignments=False,
    boundary_s2=False,
    boundary_s3=False,
    assignment_value=1.0,
):
    """Reproduce the coupled event core from SSTS semantic/00349 and /00884."""
    s2_boundary = ' boundaryCondition="true"' if boundary_s2 else ""
    s3_boundary = ' boundaryCondition="true"' if boundary_s3 else ""
    if time_assignments:
        parameter = '<parameter id="k3" value="4" constant="true"/>'
        first_assignment = """<apply><times/><ci>k3</ci>
          <csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">s</csymbol>
        </apply>"""
        second_assignment = """<apply><times/><cn>0.25</cn>
          <csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">s</csymbol>
        </apply>"""
    else:
        parameter = ""
        first_assignment = f"<cn>{assignment_value}</cn>"
        second_assignment = f"<cn>{assignment_value}</cn>"

    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="shared_quadratic_event_pair">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false"/>
          <species id="S2" compartment="C" initialAmount="2" hasOnlySubstanceUnits="false"{s2_boundary}/>
          <species id="S3" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false"{s3_boundary}/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k1" value="0.75" constant="true"/>
          <parameter id="k2" value="0.25" constant="true"/>
          {parameter}
        </listOfParameters>
        <listOfReactions>
          <reaction id="reaction1" reversible="false">
            <listOfReactants><speciesReference species="S1"/><speciesReference species="S2"/></listOfReactants>
            <listOfProducts><speciesReference species="S3"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci>C</ci><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>
            </math></kineticLaw>
          </reaction>
          <reaction id="reaction2" reversible="false">
            <listOfReactants><speciesReference species="S3"/></listOfReactants>
            <listOfProducts><speciesReference species="S1"/><speciesReference species="S2"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci>C</ci><ci>k2</ci><ci>S3</ci></apply>
            </math></kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents>
          <event id="event1" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><lt/><ci>S1</ci><cn>0.75</cn></apply>
            </math></trigger>
            <listOfEventAssignments><eventAssignment variable="S2"><math xmlns="http://www.w3.org/1998/Math/MathML">
              {first_assignment}
            </math></eventAssignment></listOfEventAssignments>
          </event>
          <event id="event2" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><gt/><ci>S3</ci><cn>1.4</cn></apply>
            </math></trigger>
            <listOfEventAssignments><eventAssignment variable="S1"><math xmlns="http://www.w3.org/1998/Math/MathML">
              {second_assignment}
            </math></eventAssignment></listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""


def test_shared_quadratic_event_pair_recomputes_after_each_firing(tmp_path):
    import numpy as np
    import pytest

    from bionetgen.atomizer.modern import Atomizer

    for time_assignments in (False, True):
        xml = _shared_quadratic_event_pair_model(time_assignments)
        result = Atomizer(quiet_mode=True, t_end=2, n_steps=400).atomize(xml)

        assert result.success, result.error
        assert "state-dependent or non-constant event" not in result.bngl
        assert "Events NOT simulated" not in result.bngl
        assert "# 2 time-triggered SBML event(s) translated" in result.bngl

        model_path = tmp_path / f"shared_quadratic_events_{time_assignments}.bngl"
        model_path.write_text(result.bngl, encoding="utf-8")
        from bionetgen.model import load

        load(model_path).execute()
        lines = model_path.with_suffix(".gdat").read_text().splitlines()
        columns = lines[0].lstrip("# ").split()
        bng_data = np.loadtxt(lines[1:])
        times = bng_data[:, columns.index("time")]

        roadrunner = pytest.importorskip("roadrunner")
        rr = roadrunner.RoadRunner(xml)
        rr.integrator.setValue("relative_tolerance", 1e-10)
        rr.integrator.setValue("absolute_tolerance", 1e-12)
        rr.timeCourseSelections = ["time", "[S1]", "[S2]", "[S3]"]
        reference = rr.simulate(times=times)

        state_columns = [columns.index(species) for species in ("S1", "S2", "S3")]
        jump_indices = np.flatnonzero(
            np.max(np.abs(np.diff(bng_data[:, state_columns], axis=0)), axis=1) > 0.1
        )
        assert len(jump_indices) >= 2
        compare = np.ones(len(times), dtype=bool)
        compare[jump_indices] = False
        compare[jump_indices + 1] = False
        for species in ("S1", "S2", "S3"):
            bng_values = bng_data[compare, columns.index(species)]
            rr_values = reference[compare, reference.colnames.index(f"[{species}]")]
            scale = max(
                float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values)))
            )
            assert float(np.max(np.abs(bng_values - rr_values))) <= max(
                5e-10, 1e-5 * scale
            )


def test_shared_quadratic_event_pair_tracks_boundary_species_assignments():
    from bionetgen.atomizer.modern import Atomizer

    xml = _shared_quadratic_event_pair_model(boundary_s2=True)
    result = Atomizer(quiet_mode=True, t_end=2, n_steps=400).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert "# 2 time-triggered SBML event(s) translated" in result.bngl


def test_shared_quadratic_event_pair_proves_constant_boundary_trigger_inactive():
    from bionetgen.atomizer.modern import Atomizer

    for boundary_s2, assignment_value in ((False, 1.0), (True, 1.1)):
        xml = _shared_quadratic_event_pair_model(
            boundary_s2=boundary_s2,
            boundary_s3=True,
            assignment_value=assignment_value,
        )
        result = Atomizer(quiet_mode=True, t_end=2, n_steps=400).atomize(xml)

        assert result.success, result.error
        assert "state-dependent or non-constant event" not in result.bngl
        assert "Events NOT simulated" not in result.bngl


def test_shared_quadratic_simultaneous_crossings_stay_unsupported():
    from bionetgen.atomizer.modern import Atomizer

    xml = (
        _shared_quadratic_event_pair_model(assignment_value=0.0)
        .replace('eventAssignment variable="S2"', 'eventAssignment variable="S3"')
        .replace('eventAssignment variable="S1"', 'eventAssignment variable="S2"')
        .replace("<cn>1.4</cn>", "<cn>1.25</cn>")
    )
    result = Atomizer(quiet_mode=True, t_end=2, n_steps=400).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" in result.bngl
    assert "Events NOT simulated" in result.bngl


def test_shared_quadratic_simultaneous_initial_entries_stay_unsupported():
    from bionetgen.atomizer.modern import Atomizer

    xml = (
        _shared_quadratic_event_pair_model()
        .replace(
            "<apply><lt/><ci>S1</ci><cn>0.75</cn></apply>",
            "<apply><lt/><ci>S1</ci><cn>1</cn></apply>",
        )
        .replace("<cn>1.4</cn>", "<cn>1</cn>")
    )
    result = Atomizer(quiet_mode=True, t_end=0.1, n_steps=10).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" in result.bngl
    assert "Events NOT simulated" in result.bngl


def test_shared_quadratic_trigger_entering_at_initial_time_matches_libroadrunner(
    tmp_path,
):
    import numpy as np
    import pytest

    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = _shared_quadratic_event_pair_model().replace(
        "<apply><lt/><ci>S1</ci><cn>0.75</cn></apply>",
        "<apply><lt/><ci>S1</ci><cn>1</cn></apply>",
    )
    result = Atomizer(quiet_mode=True, t_end=0.1, n_steps=10).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert 'setConcentration("@C:M_S2()", "1")' in result.bngl

    model_path = tmp_path / "shared_quadratic_initial_event.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])

    roadrunner = pytest.importorskip("roadrunner")
    reference_engine = roadrunner.RoadRunner(xml)
    reference_engine.integrator.setValue("relative_tolerance", 1e-10)
    reference_engine.integrator.setValue("absolute_tolerance", 1e-12)
    reference_engine.timeCourseSelections = ["time", "[S1]", "[S2]", "[S3]"]
    reference = reference_engine.simulate(times=bng_data[:, columns.index("time")])

    positive_time = bng_data[:, columns.index("time")] > 0
    assert bng_data[0, columns.index("S2")] == pytest.approx(1.0)
    for species in ("S1", "S2", "S3"):
        bng_values = bng_data[positive_time, columns.index(species)]
        rr_values = reference[positive_time, reference.colnames.index(f"[{species}]")]
        scale = max(float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values))))
        assert float(np.max(np.abs(bng_values - rr_values))) <= max(5e-10, 1e-5 * scale)


def test_first_order_cycle_events_match_libroadrunner(tmp_path):
    import numpy as np
    import pytest

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    for delay, simultaneous_assignments, rates in (
        (None, False, (0.75, 0.55, 0.25)),
        (None, True, (0.75, 0.55, 0.25)),
        (1.5, False, (0.75, 0.55, 0.25)),
        (1.5, True, (0.75, 0.55, 0.25)),
        (None, False, (3.0, 0.1, 0.2)),
    ):
        xml = _first_order_cycle_reentrant_event_model(
            delay, simultaneous_assignments, rates
        )
        result = Atomizer(quiet_mode=True, t_end=20, n_steps=1200).atomize(xml)

        assert result.success, result.error
        assert "Events NOT simulated" not in result.bngl

        model_path = tmp_path / (
            f"first_order_cycle_{delay}_{simultaneous_assignments}_{rates[0]}.bngl"
        )
        model_path.write_text(result.bngl, encoding="utf-8")
        load(model_path).execute()
        lines = model_path.with_suffix(".gdat").read_text().splitlines()
        columns = lines[0].lstrip("# ").split()
        bng_data = np.loadtxt(lines[1:])
        times = bng_data[:, columns.index("time")]

        rr = roadrunner.RoadRunner(xml)
        rr.integrator.setValue("relative_tolerance", 1e-9)
        rr.integrator.setValue("absolute_tolerance", 1e-12)
        rr.timeCourseSelections = ["time", "[S1]", "[S2]", "[S3]"]
        reference = rr.simulate(times=times)

        state_columns = [columns.index(species) for species in ("S1", "S2", "S3")]
        changes = np.abs(np.diff(bng_data[:, state_columns], axis=0))
        jump_indices = np.flatnonzero(np.max(changes, axis=1) > 0.2)
        assert len(jump_indices) >= 1
        compare = np.ones(len(times), dtype=bool)
        compare[jump_indices] = False
        compare[jump_indices + 1] = False
        for species in ("S1", "S2", "S3"):
            bng_values = bng_data[compare, columns.index(species)]
            rr_values = reference[compare, reference.colnames.index(f"[{species}]")]
            scale = max(
                float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values)))
            )
            assert float(np.max(np.abs(bng_values - rr_values))) <= max(
                5e-12, 1e-6 * scale
            )


def test_first_order_cycle_inclusive_tangent_event_remains_unsupported():
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.atomizer.modern.events import _first_order_cycle_trajectory

    initial_state = (3.0, 0.5, 0.5)
    rates = (1.0, 1.0, 1.0)
    trajectory = _first_order_cycle_trajectory(initial_state, rates)
    assert trajectory is not None
    first_extremum = trajectory.extrema_times(10.0)[0]
    threshold_state = trajectory.state_at(first_extremum)
    assert threshold_state is not None

    xml = _first_order_cycle_reentrant_event_model(rates=rates)
    xml = xml.replace(
        'id="S1" compartment="C" initialAmount="1"',
        'id="S1" compartment="C" initialAmount="3"',
    )
    xml = xml.replace(
        'id="S2" compartment="C" initialAmount="2"',
        'id="S2" compartment="C" initialAmount="0.5"',
    )
    xml = xml.replace(
        'id="S3" compartment="C" initialAmount="1"',
        'id="S3" compartment="C" initialAmount="0.5"',
    )
    xml = xml.replace(
        "<apply><lt/><ci>S1</ci><cn>0.75</cn></apply>",
        f"<apply><leq/><ci>S1</ci><cn>{threshold_state[0]:.17g}</cn></apply>",
    )

    result = Atomizer(quiet_mode=True, t_end=10, n_steps=100).atomize(xml)

    assert result.success, result.error
    assert "Events NOT simulated" in result.bngl


def test_quadratic_event_ignores_rules_outside_trigger_component():
    from bionetgen.atomizer.modern import Atomizer

    # SBML Test Suite semantic/00652 has one first-order reversible component,
    # a downstream assignment rule, and a rate-ruled species that does not feed
    # back into that component.
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="quadratic_event_with_unrelated_rules">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="0.00001" hasOnlySubstanceUnits="false"/>
          <species id="S2" compartment="C" initialAmount="0.000015" hasOnlySubstanceUnits="false"/>
          <species id="S3" compartment="C" initialAmount="0.00001" hasOnlySubstanceUnits="false"/>
          <species id="S4" compartment="C" initialAmount="2.25" hasOnlySubstanceUnits="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k1" value="0.015" constant="true"/>
          <parameter id="k2" value="0.5" constant="true"/>
          <parameter id="k3" value="1.5" constant="true"/>
        </listOfParameters>
        <listOfRules>
          <assignmentRule variable="S4"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k3</ci><ci>S1</ci></apply>
          </math></assignmentRule>
          <rateRule variable="S2"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><minus/><apply><times/><ci>k2</ci><ci>S3</ci></apply>
              <apply><times/><ci>k1</ci><ci>S1</ci></apply>
            </apply>
          </math></rateRule>
        </listOfRules>
        <listOfReactions>
          <reaction id="forward" reversible="false">
            <listOfReactants><speciesReference species="S1"/></listOfReactants>
            <listOfProducts><speciesReference species="S3"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci>C</ci><ci>k1</ci><ci>S1</ci></apply>
            </math></kineticLaw>
          </reaction>
          <reaction id="reverse" reversible="false">
            <listOfReactants><speciesReference species="S3"/></listOfReactants>
            <listOfProducts><speciesReference species="S1"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci>C</ci><ci>k2</ci><ci>S3</ci></apply>
            </math></kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents><event id="reset" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><gt/><ci>S1</ci><cn>0.000015</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="S3">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.00001</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=1, n_steps=10).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert "Events NOT simulated" not in result.bngl

    active_rule_xml = xml.replace(
        '<rateRule variable="S2">', '<rateRule variable="S1">'
    )
    active_rule_result = Atomizer(quiet_mode=True, t_end=1, n_steps=10).atomize(
        active_rule_xml
    )

    assert active_rule_result.success, active_rule_result.error
    assert "Events NOT simulated" in active_rule_result.bngl

    trigger_rule_xml = (
        xml.replace(
            "</listOfParameters>",
            '<parameter id="k4" value="0.000014" constant="false"/>'
            "</listOfParameters>",
        )
        .replace(
            "</listOfRules>",
            '<rateRule variable="k4"><math '
            'xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.00001</cn>'
            "</math></rateRule></listOfRules>",
        )
        .replace("<cn>0.000015</cn>", "<ci>k4</ci>")
    )
    trigger_rule_result = Atomizer(quiet_mode=True, t_end=1, n_steps=10).atomize(
        trigger_rule_xml
    )

    assert trigger_rule_result.success, trigger_rule_result.error
    assert "Events NOT simulated" in trigger_rule_result.bngl


def test_quadratic_event_staying_true_after_reset_does_not_refire():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="quadratic_event_stays_true">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/>
          <species id="B" compartment="C" initialAmount="2" hasOnlySubstanceUnits="true"/>
          <species id="D" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k1" value="0.75" constant="true"/>
          <parameter id="k2" value="0.25" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="bind" reversible="false">
            <listOfReactants><speciesReference species="A"/><speciesReference species="B"/></listOfReactants>
            <listOfProducts><speciesReference species="D"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>C</ci><ci>k1</ci><ci>A</ci><ci>B</ci></apply></math></kineticLaw>
          </reaction>
          <reaction id="unbind" reversible="false">
            <listOfReactants><speciesReference species="D"/></listOfReactants>
            <listOfProducts><speciesReference species="A"/><speciesReference species="B"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>C</ci><ci>k2</ci><ci>D</ci></apply></math></kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents><event id="reset" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><lt/><ci>A</ci><cn>0.75</cn></apply></math>
          </trigger>
          <listOfEventAssignments>
            <eventAssignment variable="B"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1.5</cn></math></eventAssignment>
            <eventAssignment variable="A"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.5</cn></math></eventAssignment>
          </listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=10, n_steps=100).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert "# 1 time-triggered SBML event(s) translated" in result.bngl
    assert result.bngl.count("setConcentration(") == 2


def test_exponential_self_reset_after_requested_horizon_is_informational():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="exponential_self_reset_after_horizon">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="1" hasOnlySubstanceUnits="true"/>
          <species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true"/>
        </listOfSpecies>
        <listOfParameters><parameter id="k" value="1" constant="true"/></listOfParameters>
        <listOfReactions><reaction id="decay" reversible="false">
          <listOfReactants><speciesReference species="A" stoichiometry="1"/></listOfReactants>
          <listOfProducts><speciesReference species="B" stoichiometry="1"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="reset">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><lt/><ci>A</ci><cn>0.1</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="A">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=1).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert (
        "make no state changes through the configured simulation horizon" in result.bngl
    )
    assert "begin actions" not in result.bngl


def test_exponential_parameter_event_rejects_dynamic_coefficient():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="dynamic_exponential_coefficient_event">
        <listOfParameters>
          <parameter id="p" value="1" constant="false"/>
          <parameter id="q" value="0.01" constant="false"/>
          <parameter id="k" value="0.1" constant="true"/>
          <parameter id="out" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <rateRule variable="p"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>q</ci><ci>p</ci></apply>
          </math></rateRule>
          <rateRule variable="q"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>q</ci></apply>
          </math></rateRule>
        </listOfRules>
        <listOfEvents><event id="threshold">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><geq/><ci>p</ci><cn>1.5</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="out">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>5</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "untranslated" in result.bngl.lower()


def test_fixed_time_event_reads_exact_exponential_parameter_value():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="fixed_time_exponential_parameter_event">
        <listOfParameters>
          <parameter id="p" value="1" constant="false"/>
          <parameter id="k" value="0.5" constant="true"/>
          <parameter id="out" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules><rateRule variable="p">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>p</ci></apply>
          </math>
        </rateRule></listOfRules>
        <listOfEvents><event id="fixed">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply>
            </math>
          </trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn>2</cn><ci>p</ci></apply>
          </math></delay>
          <listOfEventAssignments><eventAssignment variable="out">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>p</ci></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "t_end=>4.2974425414" in result.bngl
    assert 'setParameter("out", "1.6487212707")' in result.bngl
    assert "untranslated" not in result.bngl.lower()


def test_affine_state_interval_event_lowers_with_a_safe_delayed_self_update():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="affine_state_interval_event">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="A" compartment="c" initialAmount="1.8" hasOnlySubstanceUnits="false"/></listOfSpecies>
        <listOfParameters><parameter id="out" value="0" constant="false"/></listOfParameters>
        <listOfReactions><reaction id="source" reversible="false">
          <listOfProducts><speciesReference species="A" stoichiometry="1"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.01</cn></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="interval">
          <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><and/>
              <apply><geq/><ci>A</ci><cn>1.84</cn></apply>
              <apply><leq/><ci>A</ci><cn>1.88</cn></apply>
            </apply>
          </math></trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></delay>
          <listOfEventAssignments>
            <eventAssignment variable="A"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>6</cn></math></eventAssignment>
            <eventAssignment variable="out"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math></eventAssignment>
          </listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "t_end=>5" in result.bngl
    assert 'setConcentration("@c:M_A()", "6")' in result.bngl
    assert 'setParameter("out", "3")' in result.bngl
    assert "untranslated" not in result.bngl.lower()


def test_affine_interval_event_uses_species_conversion_factor():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="affine_interval_species_conversion_factor" conversionFactor="model_cf">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="A" compartment="c" initialAmount="1.8" hasOnlySubstanceUnits="false" conversionFactor="species_cf"/></listOfSpecies>
        <listOfParameters>
          <parameter id="model_cf" value="3" constant="true"/>
          <parameter id="species_cf" value="5" constant="true"/>
        </listOfParameters>
        <listOfReactions><reaction id="source" reversible="false">
          <listOfProducts><speciesReference species="A" stoichiometry="1"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.01</cn></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="interval">
          <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><and/>
              <apply><geq/><ci>A</ci><cn>1.84</cn></apply>
              <apply><leq/><ci>A</ci><cn>1.88</cn></apply>
            </apply>
          </math></trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.2</cn></math></delay>
          <listOfEventAssignments><eventAssignment variable="A">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>6</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "t_end=>1" in result.bngl
    assert 'setConcentration("@c:M_A()", "6")' in result.bngl
    assert "untranslated" not in result.bngl.lower()


def test_exponential_interval_event_lowers_at_first_rising_edge():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="exponential_state_interval_event">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="A" compartment="c" initialAmount="1" hasOnlySubstanceUnits="false"/></listOfSpecies>
        <listOfParameters>
          <parameter id="k" value="1" constant="true"/>
          <parameter id="out" value="0" constant="false"/>
        </listOfParameters>
        <listOfReactions><reaction id="decay" reversible="false">
          <listOfReactants><speciesReference species="A" stoichiometry="1"/></listOfReactants>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="interval">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><and/>
                <apply><leq/><ci>A</ci><cn>0.5</cn></apply>
                <apply><geq/><ci>A</ci><cn>0.4</cn></apply>
              </apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="out">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=5, n_steps=100).atomize(xml)

    assert result.success, result.error
    assert 'setParameter("out", "3")' in result.bngl
    assert "Events NOT simulated" not in result.bngl
    assert "t_end=>0.69314718056" in result.bngl


def test_exponential_interval_action_trajectory_matches_libroadrunner(tmp_path):
    import numpy as np
    import pytest

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="exponential_state_interval_action_parity">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="1" hasOnlySubstanceUnits="false"/>
          <species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="false"/>
        </listOfSpecies>
        <listOfParameters><parameter id="k" value="1" constant="true"/></listOfParameters>
        <listOfReactions><reaction id="decay" reversible="false">
          <listOfReactants><speciesReference species="A" stoichiometry="1"/></listOfReactants>
          <listOfProducts><speciesReference species="B" stoichiometry="1"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="interval">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><and/>
                <apply><leq/><ci>A</ci><cn>0.5</cn></apply>
                <apply><geq/><ci>A</ci><cn>0.4</cn></apply>
              </apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="B">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=2, n_steps=100).atomize(xml)
    assert result.success, result.error
    assert 'setConcentration("@c:M_B()", "2")' in result.bngl
    model_path = tmp_path / "event_parity.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()

    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])
    times = bng_data[:, columns.index("time")]
    assert np.max(bng_data[times > 0.7, columns.index("B")]) > 1.5

    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-7)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    reference = rr.simulate(times=times)
    # BNG3 records event boundaries before applying the scheduled action;
    # libRoadRunner reports the right-continuous value at that exact time.
    # Compare both trajectories away from the discontinuity itself.
    compare = np.abs(times - np.log(2.0)) > 1e-9
    for species in ("A", "B"):
        bng_values = bng_data[compare, columns.index(species)]
        rr_values = reference[compare, reference.colnames.index(f"[{species}]")]
        scale = max(float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values))))
        tolerance = max(5e-12, 1e-5 * scale)
        assert float(np.max(np.abs(bng_values - rr_values))) <= tolerance


def test_time_shifted_initial_event_action_matches_libroadrunner(tmp_path):
    import numpy as np
    import pytest

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="time_shifted_initial_event_parity">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="c" initialAmount="0" hasOnlySubstanceUnits="false"/></listOfSpecies>
        <listOfEvents><event id="at_initial_time">
          <trigger initialValue="false" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><lt/>
                <apply><minus/>
                  <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol>
                  <cn>1</cn>
                </apply>
                <cn>-0.5</cn>
              </apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="S">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=1, n_steps=10).atomize(xml)
    assert result.success, result.error
    assert 'setConcentration("@c:M_S()", "3")' in result.bngl
    model_path = tmp_path / "time_shifted_event.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()

    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])
    times = bng_data[:, columns.index("time")]
    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-7)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    reference = rr.simulate(times=times)
    assert np.all(bng_data[times > 0, columns.index("S")] == 3)
    rr_values = reference[times > 0, reference.colnames.index("[S]")]
    assert np.allclose(rr_values, 3, rtol=0, atol=5e-12)


def test_constant_false_state_event_is_removed_without_model_dynamics():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="constant_false_state_event">
        <listOfParameters>
          <parameter id="S1" value="1" constant="false"/>
          <parameter id="S2" value="0" constant="false"/>
        </listOfParameters>
        <listOfEvents><event id="never_fires">
          <trigger initialValue="false" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><lt/><ci>S1</ci><cn>0.1</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="S1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "untranslated" not in result.bngl.lower()


def test_static_initial_rising_event_uses_its_initial_edge_once():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="static_initial_rising_event">
        <listOfParameters><parameter id="x" value="3" constant="false"/></listOfParameters>
        <listOfEvents><event id="initial_rise">
          <trigger initialValue="false" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><gt/><ci>x</ci><cn>2</cn></apply>
            </math>
          </trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2.5</cn></math></delay>
          <listOfEventAssignments><eventAssignment variable="x">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>7</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert 'setParameter("x", "7")' in result.bngl
    assert "untranslated" not in result.bngl.lower()


def test_affine_threshold_drops_constant_true_conjunction_terms():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="affine_threshold_boolean_conjunction">
        <listOfParameters>
          <parameter id="P" value="0" constant="false"/>
          <parameter id="Q" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules><rateRule variable="P">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
        </rateRule></listOfRules>
        <listOfEvents><event id="event">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><and/>
              <apply><gt/><ci>P</ci><cn>1</cn></apply>
              <apply><not/><cn>0</cn></apply>
            </apply></math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="Q">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>5</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert 'setParameter("Q", "5")' in result.bngl
    assert "state-dependent or non-constant event" not in result.bngl


def test_event_assignment_delay_function_uses_affine_state_history():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="event_delay_affine_history">
        <listOfParameters>
          <parameter id="P" value="0" constant="false"/>
          <parameter id="Q" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules><rateRule variable="P">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
        </rateRule></listOfRules>
        <listOfEvents><event id="event" useValuesFromTriggerTime="{trigger_time}">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><gt/><ci>P</ci><cn>1.5</cn></apply>
            </math>
          </trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></delay>
          <listOfEventAssignments><eventAssignment variable="Q">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
                <ci>P</ci><cn>1</cn>
              </apply>
            </math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    for trigger_time, expected in (("true", "0.5"), ("false", "2.5")):
        result = Atomizer(quiet_mode=True).atomize(
            xml.format(trigger_time=trigger_time)
        )

        assert result.success, result.error
        assert f'setParameter("Q", "{expected}")' in result.bngl
        assert "state-dependent or non-constant event" not in result.bngl


def test_affine_rate_rule_on_species_reference_schedules_interval_event():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="affine_stoichiometry_interval_event">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="C" initialConcentration="0"
          hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/></listOfSpecies>
        <listOfParameters><parameter id="P" value="0" constant="false"/></listOfParameters>
        <listOfRules><rateRule variable="sr">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
        </rateRule></listOfRules>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfProducts><speciesReference id="sr" species="S" stoichiometry="1" constant="false"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.1</cn></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="interval" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><and/><apply><geq/><ci>sr</ci><cn>2.3</cn></apply>
              <apply><leq/><ci>sr</ci><cn>3.3</cn></apply></apply>
          </math></trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></delay>
          <listOfEventAssignments><eventAssignment variable="P">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert 'setParameter("P", "3")' in result.bngl
    assert "state-dependent or non-constant event" not in result.bngl


def test_affine_amount_species_rate_rule_schedules_threshold_event():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="affine_amount_species_event">
        <listOfCompartments><compartment id="C" size="2" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="C" initialAmount="10"
          hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/></listOfSpecies>
        <listOfParameters><parameter id="Q" value="0" constant="false"/></listOfParameters>
        <listOfRules><rateRule variable="S">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>-1</cn></math>
        </rateRule></listOfRules>
        <listOfEvents><event id="threshold">
          <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><leq/><ci>S</ci><cn>8.9</cn></apply>
          </math></trigger>
          <listOfEventAssignments><eventAssignment variable="Q">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert 'setParameter("Q", "3")' in result.bngl
    assert "state-dependent or non-constant event" not in result.bngl


def test_affine_rate_rule_identity_event_assignments_preserve_thresholds():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="affine_identity_event_assignments">
        <listOfParameters><parameter id="P1" value="0" constant="false"/>
          <parameter id="P2" value="0" constant="false"/>
          <parameter id="P3" value="0" constant="false"/></listOfParameters>
        <listOfRules><rateRule variable="P1"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></rateRule>
          <rateRule variable="P2"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></rateRule>
          <rateRule variable="P3"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></rateRule></listOfRules>
        <listOfEvents>
          <event id="e1"><trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><ci>P1</ci><cn>1.5</cn></apply></math></trigger><listOfEventAssignments><eventAssignment variable="P1"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>P1</ci></math></eventAssignment></listOfEventAssignments></event>
          <event id="e2"><trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><ci>P2</ci><cn>1.5</cn></apply></math></trigger><listOfEventAssignments><eventAssignment variable="P2"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>P2</ci></math></eventAssignment></listOfEventAssignments></event>
          <event id="e3"><trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><ci>P3</ci><cn>1.5</cn></apply></math></trigger><listOfEventAssignments><eventAssignment variable="P3"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>P3</ci></math></eventAssignment></listOfEventAssignments></event>
        </listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert result.bngl.count("event") >= 3
    assert "state-dependent or non-constant event" not in result.bngl


def test_reciprocal_species_flux_schedules_exact_threshold_event():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="reciprocal_species_flux_event">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="C" initialAmount="1"
          hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/></listOfSpecies>
        <listOfParameters><parameter id="k" value="1" constant="false"/></listOfParameters>
        <listOfReactions><reaction id="source" reversible="false">
          <listOfProducts><speciesReference species="S" stoichiometry="1" constant="true"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><divide/>
            <apply><times/><ci>C</ci><ci>k</ci></apply><ci>S</ci>
          </apply></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="threshold" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><gt/><ci>S</ci><cn>2.1</cn></apply>
          </math></trigger>
          <listOfEventAssignments><eventAssignment variable="k"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>10</cn></math></eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "t_end=>1.705" in result.bngl
    assert 'setParameter("k", "10")' in result.bngl
    assert "state-dependent or non-constant event" not in result.bngl


def test_reciprocal_species_flux_accepts_volume_assignment_rule_alias(tmp_path):
    import numpy as np
    import pytest

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="reciprocal_volume_assignment_rule_event">
        <listOfCompartments><compartment id="C" spatialDimensions="3"
          constant="false"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="C" initialAmount="1"
          hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/></listOfSpecies>
        <listOfParameters>
          <parameter id="fakeC" value="1" constant="false"/>
          <parameter id="k" value="1" constant="false"/>
        </listOfParameters>
        <listOfRules><assignmentRule variable="C">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>fakeC</ci></math>
        </assignmentRule></listOfRules>
        <listOfReactions><reaction id="source" reversible="false">
          <listOfProducts><speciesReference species="S" stoichiometry="1" constant="true"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><divide/>
            <apply><times/><ci>C</ci><ci>k</ci></apply><ci>S</ci>
          </apply></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="threshold" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><gt/><ci>S</ci><cn>2.1</cn></apply>
          </math></trigger>
          <listOfEventAssignments><eventAssignment variable="fakeC"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>10</cn></math></eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=3, n_steps=300).atomize(xml)

    assert result.success, result.error
    assert "t_end=>1.705" in result.bngl
    assert 'setParameter("fakeC", "10")' in result.bngl
    assert 'setVolume({target=>"C", value=>10})' in result.bngl
    assert 'setParameter("__compartment_C__", "10")' in result.bngl
    assert "state-dependent or non-constant event" not in result.bngl

    model_path = tmp_path / "reciprocal_volume_assignment_rule_event.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])
    times = bng_data[:, columns.index("time")]
    assert np.isclose(times[-1], 3.0, rtol=0, atol=1e-10)

    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-7)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", "[S]", "C"]
    reference = rr.simulate(times=times)
    away_from_event = np.abs(times - 1.705) > 1e-9
    bng_values = bng_data[away_from_event, columns.index("S_amt")]
    rr_values = (
        reference[away_from_event, reference.colnames.index("[S]")]
        * reference[away_from_event, reference.colnames.index("C")]
    )
    scale = max(float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values))))
    assert float(np.max(np.abs(bng_values - rr_values))) <= max(5e-12, 1e-5 * scale)

    longer = Atomizer(quiet_mode=True, t_end=5, n_steps=500).atomize(xml)
    assert longer.success, longer.error
    assert 'setVolume({target=>"C", value=>10})' not in longer.bngl
    assert "volume change can cause the state trigger to re-enter" in longer.bngl


def test_reciprocal_species_flux_schedules_volume_event_without_reentry(tmp_path):
    import numpy as np
    import pytest

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="reciprocal_species_flux_volume_event">
        <listOfCompartments><compartment id="C" size="1" constant="false"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="C" initialAmount="1"
          hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/></listOfSpecies>
        <listOfParameters><parameter id="k" value="1" constant="true"/></listOfParameters>
        <listOfReactions><reaction id="source" reversible="false">
          <listOfProducts><speciesReference species="S" stoichiometry="1" constant="true"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><divide/>
            <apply><times/><ci>C</ci><ci>k</ci></apply><ci>S</ci>
          </apply></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="threshold" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><gt/><ci>S</ci><cn>2.1</cn></apply>
          </math></trigger>
          <listOfEventAssignments><eventAssignment variable="C"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>10</cn></math></eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=3, n_steps=300).atomize(xml)

    assert result.success, result.error
    assert "t_end=>1.705" in result.bngl
    assert 'setVolume({target=>"C", value=>10})' in result.bngl
    assert 'setParameter("__compartment_C__", "10")' in result.bngl
    assert "state-dependent or non-constant event" not in result.bngl

    model_path = tmp_path / "reciprocal_volume_event.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])
    times = bng_data[:, columns.index("time")]
    assert np.isclose(times[-1], 3.0, rtol=0, atol=1e-10)

    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-7)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", "[S]", "C"]
    reference = rr.simulate(times=times)
    away_from_event = np.abs(times - 1.705) > 1e-9
    bng_values = bng_data[away_from_event, columns.index("S_amt")]
    rr_values = (
        reference[away_from_event, reference.colnames.index("[S]")]
        * reference[away_from_event, reference.colnames.index("C")]
    )
    scale = max(float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values))))
    assert float(np.max(np.abs(bng_values - rr_values))) <= max(5e-12, 1e-5 * scale)

    longer = Atomizer(quiet_mode=True, t_end=5, n_steps=500).atomize(xml)
    assert longer.success, longer.error
    assert 'setVolume({target=>"C", value=>10})' not in longer.bngl
    assert "volume change can cause the state trigger to re-enter" in longer.bngl


def test_event_math_folds_constant_reaction_identifier_rate():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="event_reaction_identifier_rate">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="C" initialAmount="0"
          hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/></listOfSpecies>
        <listOfParameters><parameter id="k1" value="1" constant="false"/></listOfParameters>
        <listOfReactions><reaction id="J0" reversible="false">
          <listOfProducts><speciesReference species="S" stoichiometry="1" constant="true"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k1</ci></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="update" useValuesFromTriggerTime="true">
          <trigger initialValue="false" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><gt/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><ci>J0</ci></apply>
          </math></trigger>
          <listOfEventAssignments><eventAssignment variable="k1"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><plus/><cn>1</cn><ci>J0</ci></apply>
          </math></eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert 'setParameter("k1", "2")' in result.bngl
    assert "Events NOT simulated" not in result.bngl


def test_delayed_event_assignment_uses_the_selected_sbml_value_snapshot():
    from bionetgen.atomizer.modern import Atomizer

    for use_trigger_time, expected in (("true", "1"), ("false", "7")):
        xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
          <model id="delayed_event_snapshot">
            <listOfParameters>
              <parameter id="x" value="1" constant="false"/>
              <parameter id="y" value="0" constant="false"/>
            </listOfParameters>
            <listOfEvents>
              <event id="set_y" useValuesFromTriggerTime="{use_trigger_time}">
                <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
                  <apply><gt/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>2.5</cn></apply>
                </math></trigger>
                <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></delay>
                <listOfEventAssignments><eventAssignment variable="y"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>x</ci></math></eventAssignment></listOfEventAssignments>
              </event>
              <event id="set_x" useValuesFromTriggerTime="true">
                <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
                  <apply><gt/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>3.5</cn></apply>
                </math></trigger>
                <listOfEventAssignments><eventAssignment variable="x"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>7</cn></math></eventAssignment></listOfEventAssignments>
              </event>
            </listOfEvents>
          </model>
        </sbml>"""

        result = Atomizer(quiet_mode=True).atomize(xml)

        assert result.success, result.error
        assert f'setParameter("y", "{expected}")' in result.bngl
        assert "Events NOT simulated" not in result.bngl


def test_simultaneous_events_resolve_dynamic_priority_before_assignments():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="simultaneous_dynamic_event_priority">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="S" compartment="C" initialAmount="2" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="T" compartment="C" initialAmount="0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
        </listOfSpecies>
        <listOfReactions><reaction id="convert" reversible="false">
          <listOfReactants><speciesReference species="S" stoichiometry="1" constant="true"/></listOfReactants>
          <listOfProducts><speciesReference species="T" stoichiometry="1" constant="true"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.05</cn></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents>
          <event id="dynamic" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><gt/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>3.5</cn></apply></math></trigger>
            <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>S</ci></math></priority>
            <listOfEventAssignments>
              <eventAssignment variable="S"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></eventAssignment>
              <eventAssignment variable="T"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math></eventAssignment>
            </listOfEventAssignments>
          </event>
          <event id="constant" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><gt/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>3.5</cn></apply></math></trigger>
            <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1.82</cn></math></priority>
            <listOfEventAssignments>
              <eventAssignment variable="S"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>4</cn></math></eventAssignment>
              <eventAssignment variable="T"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>4</cn></math></eventAssignment>
            </listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "Events NOT simulated" not in result.bngl
    first_reset = result.bngl.index('setConcentration("@C:M_S()", "1")')
    second_reset = result.bngl.index('setConcentration("@C:M_S()", "4")')
    assert first_reset < second_reset


def test_affine_parameter_event_priorities_use_execution_time_values():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="affine_parameter_event_priority">
        <listOfParameters>
          <parameter id="P1" value="0" constant="false"/>
          <parameter id="P2" value="0" constant="false"/>
          <parameter id="P3" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules><rateRule variable="P1">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
        </rateRule></listOfRules>
        <listOfEvents>
          <event id="history_priority" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true">
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><gt/><ci>P1</ci><cn>1.5</cn></apply>
              </math>
            </trigger>
            <priority><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply>
                <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
                <ci>P1</ci><cn>1</cn>
              </apply>
            </math></priority>
            <listOfEventAssignments><eventAssignment variable="P3">
              <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
            </eventAssignment></listOfEventAssignments>
          </event>
          <event id="constant_priority" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true">
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><gt/><ci>P1</ci><cn>1.5</cn></apply>
              </math>
            </trigger>
            <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></priority>
            <listOfEventAssignments><eventAssignment variable="P2">
              <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
            </eventAssignment></listOfEventAssignments>
          </event>
          <event id="updated_priority" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true">
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><gt/><ci>P1</ci><cn>1.5</cn></apply>
              </math>
            </trigger>
            <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>P2</ci></math></priority>
            <listOfEventAssignments><eventAssignment variable="P3">
              <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math>
            </eventAssignment></listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=2, n_steps=20).atomize(xml)

    assert result.success, result.error
    assert "Events NOT simulated" not in result.bngl
    p2_update = result.bngl.index('setParameter("P2", "3")')
    reevaluated_priority_update = result.bngl.index('setParameter("P3", "2")')
    history_priority_update = result.bngl.index('setParameter("P3", "3")')
    assert p2_update < reevaluated_priority_update < history_priority_update


def test_simultaneous_rateof_delay_and_priority_use_exponential_history():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="simultaneous_rateof_event_priority">
        <listOfParameters>
          <parameter id="p1" value="2" constant="false"/>
          <parameter id="p2" value="10" constant="false"/>
        </listOfParameters>
        <listOfRules><rateRule variable="p1"><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>0.01</cn><ci>p1</ci></apply>
        </math></rateRule></listOfRules>
        <listOfEvents>
          <event id="static-priority" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><gt/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>4.5</cn></apply></math></trigger>
            <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>p1</ci></apply></math></delay>
            <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.02</cn></math></priority>
            <listOfEventAssignments><eventAssignment variable="p2"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><apply><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>p1</ci></apply><cn>2</cn></apply></math></eventAssignment></listOfEventAssignments>
          </event>
          <event id="dynamic-priority" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><gt/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>4.5</cn></apply></math></trigger>
            <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>p1</ci></apply></math></delay>
            <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>p1</ci></apply></math></priority>
            <listOfEventAssignments><eventAssignment variable="p2"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><apply><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>p1</ci></apply><cn>5</cn></apply></math></eventAssignment></listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "Events NOT simulated" not in result.bngl
    assert "t_end=>4.5209205572" in result.bngl
    high_priority = result.bngl.index('setParameter("p2", "5.0209205572")')
    low_priority = result.bngl.index('setParameter("p2", "2.0209205572")')
    assert high_priority < low_priority


def test_affine_rate_rule_compartment_schedules_delayed_threshold_event():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="affine_compartment_event">
        <listOfCompartments><compartment id="C" size="5" constant="false"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="C" initialAmount="2"
          hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/></listOfSpecies>
        <listOfRules><rateRule variable="C">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
        </rateRule></listOfRules>
        <listOfEvents><event id="volume-threshold" useValuesFromTriggerTime="true">
          <trigger initialValue="false" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><leq/><ci>C</ci><cn>5.1</cn></apply>
          </math></trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1.05</cn></math></delay>
          <listOfEventAssignments><eventAssignment variable="S">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>4</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "state-dependent or non-constant event" not in result.bngl
    assert "begin actions" in result.bngl
    assert "Events NOT simulated" not in result.bngl


def test_constant_piecewise_event_delay_and_assignment_fold_exactly():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="constant_piecewise_event">
        <listOfParameters><parameter id="x" value="0" constant="false"/></listOfParameters>
        <listOfEvents><event id="piecewise_event">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>0.5</cn></apply>
            </math>
          </trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><piecewise>
            <piece><cn>0.5</cn><apply><leq/><cn>1</cn><cn>2</cn><cn>1</cn></apply></piece>
            <otherwise><cn>0.3</cn></otherwise>
          </piecewise></math></delay>
          <listOfEventAssignments><eventAssignment variable="x">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><piecewise>
              <piece><cn>5</cn><apply><eq/><cn>1</cn><cn>1</cn><cn>2</cn></apply></piece>
              <otherwise><cn>7</cn></otherwise>
            </piecewise></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert 'setParameter("x", "7")' in result.bngl
    assert "t_end=>0.8" in result.bngl
    assert "untranslated" not in result.bngl.lower()


def test_nonpersistent_delayed_event_canceled_beyond_time_window_is_noop():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="delayed_time_window_event">
        <listOfParameters><parameter id="x" value="0" constant="false"/></listOfParameters>
        <listOfEvents><event id="window">
          <trigger initialValue="true" persistent="false">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><and/>
              <apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>0.5</cn></apply>
              <apply><leq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply>
            </apply></math>
          </trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></delay>
          <listOfEventAssignments><eventAssignment variable="x">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert 'setParameter("x", "3")' not in result.bngl
    assert "untranslated" not in result.bngl.lower()


def test_exponential_rate_rule_self_reset_schedules_repeated_threshold_events():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="exponential_rate_rule_event_reset">
        <listOfParameters>
          <parameter id="A" value="1" constant="false"/>
          <parameter id="k" value="1" constant="true"/>
        </listOfParameters>
        <listOfRules><rateRule variable="A">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/>
            <cn>-1</cn><ci>k</ci><ci>A</ci>
          </apply></math>
        </rateRule></listOfRules>
        <listOfEvents><event id="reset" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><lt/><ci>A</ci><cn>0.1</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="A">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert result.bngl.count('setConcentration("M___rate_rule_state__A()", "1")') == 4
    assert "untranslated" not in result.bngl.lower()


def test_delayed_affine_rate_rule_self_reset_respects_value_time():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="delayed_affine_trigger_value_reset">
        <listOfParameters><parameter id="P" value="10" constant="false"/></listOfParameters>
        <listOfRules><rateRule variable="P">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>-1</cn></math>
        </rateRule></listOfRules>
        <listOfEvents><event id="reset" useValuesFromTriggerTime="{trigger_time}">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><leq/><ci>P</ci><cn>8.9</cn></apply>
            </math>
          </trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></delay>
          <listOfEventAssignments><eventAssignment variable="P">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/>
              <ci>P</ci><cn>3</cn>
            </apply></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    for trigger_time, expected_value, expected_count in (
        ("true", "11.9", 2),
        ("false", "9.9", 3),
    ):
        result = Atomizer(quiet_mode=True).atomize(
            xml.format(trigger_time=trigger_time)
        )

        assert result.success, result.error
        assert (
            result.bngl.count(f'setParameter("P", "{expected_value}")')
            == expected_count
        )
        assert "untranslated" not in result.bngl.lower()


def test_affine_rate_rule_self_reset_supports_static_companion_assignment():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="affine_rate_rule_event_multiple_assignments">
        <listOfParameters>
          <parameter id="P" value="10" constant="false"/>
          <parameter id="Q" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules><rateRule variable="P">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>-1</cn></math>
        </rateRule></listOfRules>
        <listOfEvents><event id="reset" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><leq/><ci>P</ci><cn>8.9</cn></apply>
            </math>
          </trigger>
          <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.5</cn></math></delay>
          <listOfEventAssignments>
            <eventAssignment variable="P">
              <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/>
                <ci>P</ci><cn>3</cn>
              </apply></math>
            </eventAssignment>
            <eventAssignment variable="Q">
              <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>5</cn></math>
            </eventAssignment>
          </listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert result.bngl.count('setParameter("P", "11.9")') == 3
    assert result.bngl.count('setParameter("Q", "5")') == 3
    assert "untranslated" not in result.bngl.lower()


def test_initial_affine_species_event_uses_rate_rule_concentration_state():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="initial_rate_rule_species_event">
        <listOfCompartments><compartment id="C" size="0.5" constant="false"/></listOfCompartments>
        <listOfSpecies><species id="S" compartment="C" initialConcentration="1"
          hasOnlySubstanceUnits="false" boundaryCondition="true" constant="false"/></listOfSpecies>
        <listOfRules><rateRule variable="S">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.4</cn></math>
        </rateRule></listOfRules>
        <listOfEvents><event id="reset">
          <trigger initialValue="false" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><gt/><ci>S</ci><cn>-1</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="S">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert 'setConcentration("@C:M_S()", "0")' in result.bngl
    assert "untranslated" not in result.bngl.lower()


def test_delay_of_affine_species_uses_initial_history_before_delay_boundary():
    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="affine_delayed_history">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="x" compartment="c" initialAmount="0" hasOnlySubstanceUnits="false"/></listOfSpecies>
        <listOfParameters><parameter id="y" constant="false"/></listOfParameters>
        <listOfRules><assignmentRule variable="y"><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><plus/><cn>2</cn><apply>
            <csymbol definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
            <ci>x</ci><cn>0.2</cn>
          </apply></apply>
        </math></assignmentRule></listOfRules>
        <listOfReactions><reaction id="source" reversible="false">
          <listOfProducts><speciesReference species="x" stoichiometry="1"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
        </reaction></listOfReactions>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True).atomize(xml)

    assert result.success, result.error
    assert "delay(" not in result.bngl
    assert "if((time() - (0.2)) <= 0" in result.bngl
    assert "time() - (0.2)" in result.bngl


def test_nested_delay_uses_zero_lag_from_bounded_assignment_rule():
    from bionetgen.atomizer.modern import Atomizer

    # SBML Test Suite semantic/00985: with x(0)=0 and dx/dt=1, z=delay(x, 1)
    # is zero throughout [0, 1]. The second delay therefore has zero lag and
    # must reduce to x over the requested one-unit simulation horizon.
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="nested_bounded_delay">
        <listOfParameters>
          <parameter id="z" constant="false"/>
          <parameter id="x" value="0" constant="false"/>
          <parameter id="y" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <assignmentRule variable="z"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
              <ci>x</ci><cn type="integer">1</cn>
            </apply>
          </math></assignmentRule>
          <rateRule variable="x"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <cn type="integer">1</cn>
          </math></rateRule>
          <assignmentRule variable="y"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
              <ci>x</ci><ci>z</ci>
            </apply>
          </math></assignmentRule>
        </listOfRules>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=1, n_steps=10).atomize(xml)

    assert result.success, result.error
    assert "delay(" not in result.bngl.lower()
    assert 'math function "delay"' not in result.bngl

    longer_horizon = Atomizer(quiet_mode=True, t_end=2, n_steps=20).atomize(xml)

    assert longer_horizon.success, longer_horizon.error
    assert "delay(" in longer_horizon.bngl.lower()


def test_fixed_time_event_lag_uses_piecewise_affine_delay_history():
    from bionetgen.atomizer.modern import Atomizer

    # SBML Test Suite semantic/00984: temp changes from 0 to 1 at t=0.99,
    # while x=t. Over a one-unit horizon, delay(x, temp) is x before the event
    # and the zero-valued pre-simulation history afterward.
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="fixed_event_delay_lag">
        <listOfParameters>
          <parameter id="y" constant="false"/>
          <parameter id="x" value="0" constant="false"/>
          <parameter id="temp" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <assignmentRule variable="y"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
              <ci>x</ci><ci>temp</ci>
            </apply>
          </math></assignmentRule>
          <rateRule variable="x"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <cn type="integer">1</cn>
          </math></rateRule>
        </listOfRules>
        <listOfEvents><event id="set_lag" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>0.99</cn></apply>
            </math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="temp">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn type="integer">1</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=1, n_steps=10).atomize(xml)

    assert result.success, result.error
    assert "delay(" not in result.bngl.lower()
    assert "y() = if(time() < 0.99, x_amt, 0.0)" in result.bngl
    assert 'setParameter("temp", "1")' in result.bngl
    assert 'math function "delay"' not in result.bngl

    longer_horizon = Atomizer(quiet_mode=True, t_end=2, n_steps=20).atomize(xml)

    assert longer_horizon.success, longer_horizon.error
    assert "delay(" not in longer_horizon.bngl.lower()
    assert "if(time() < 1.0, 0.0, (x_amt - 1.0))" in longer_horizon.bngl


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


def test_sbml_delay_of_affine_rate_rule_uses_exact_pre_simulation_history():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="delay_of_affine_rate_rule">
        <listOfParameters>
          <parameter id="x" value="5" constant="false"/>
          <parameter id="y" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <rateRule variable="x">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><minus/><apply><times/><cn>0.1</cn><ci>x</ci></apply></apply>
            </math>
          </rateRule>
          <assignmentRule variable="y">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol><ci>x</ci><cn>1</cn></apply>
            </math>
          </assignmentRule>
        </listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)

    assert "delay(" not in model.rules[1].math
    assert "if(" in model.rules[1].math
    assert "exp(" in model.rules[1].math
    assert "5" in model.rules[1].math


def test_sbml_delay_of_rate_of_uses_delayed_state_history():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="delay_of_rate_of">
        <listOfParameters>
          <parameter id="x" value="5" constant="false"/>
          <parameter id="y" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <rateRule variable="x">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><minus/><apply><times/><cn>0.1</cn><ci>x</ci></apply></apply>
            </math>
          </rateRule>
          <assignmentRule variable="y">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply>
                <csymbol definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
                <apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>x</ci></apply>
                <cn>1</cn>
              </apply>
            </math>
          </assignmentRule>
        </listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)

    assert "delay(" not in model.rules[1].math
    assert "if(" in model.rules[1].math
    assert "exp(" in model.rules[1].math


def test_sbml_delay_length_that_is_a_bounded_fraction_of_time_lowers():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="delay_fraction_of_time">
        <listOfParameters>
          <parameter id="x" value="1" constant="false"/>
          <parameter id="y" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <rateRule variable="x">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </rateRule>
          <assignmentRule variable="y">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply>
                <csymbol definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
                <ci>x</ci><apply><divide/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>2</cn></apply>
              </apply>
            </math>
          </assignmentRule>
        </listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)

    assert "delay(" not in model.rules[1].math
    assert "time" in model.rules[1].math


def test_sbml_delay_longer_than_elapsed_time_uses_initial_history():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="delay_longer_than_elapsed_time">
        <listOfParameters>
          <parameter id="x" value="1" constant="false"/>
          <parameter id="y" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <rateRule variable="x">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </rateRule>
          <assignmentRule variable="y">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply>
                <csymbol definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
                <ci>x</ci><apply><times/><cn>2</cn><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol></apply>
              </apply>
            </math>
          </assignmentRule>
        </listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)

    assert "delay(" not in model.rules[1].math
    assert "if(" in model.rules[1].math


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


def test_sbml_event_folding_expands_constant_user_functions():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="constant_event_functions">
        <listOfParameters><parameter id="p" value="0" constant="false"/></listOfParameters>
        <listOfFunctionDefinitions>
          <functionDefinition id="event_time"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <lambda><cn>5</cn></lambda>
          </math></functionDefinition>
          <functionDefinition id="twice"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <lambda><bvar><ci>x</ci></bvar><apply><times/><ci>x</ci><cn>2</cn></apply></lambda>
          </math></functionDefinition>
        </listOfFunctionDefinitions>
        <listOfEvents><event id="fixed">
          <trigger><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol>
              <apply><ci>event_time</ci></apply>
            </apply>
          </math></trigger>
          <listOfEventAssignments><eventAssignment variable="p">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><ci>twice</ci><cn>3</cn></apply>
            </math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    assert 'setParameter("p", "6")' in bngl
    assert "t_end=>5" in bngl
    assert not any(
        warning.get("category") == "event" and warning.get("severity") == "dropped"
        for warning in model.import_warnings
    )


def test_sbml_fixed_time_compartment_event_uses_set_volume_action():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="fixed_compartment_event">
        <listOfCompartments><compartment id="cell" size="1" constant="false"/></listOfCompartments>
        <listOfEvents><event id="resize">
          <trigger><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>5</cn></apply>
          </math></trigger>
          <listOfEventAssignments><eventAssignment variable="cell">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    assert 'setVolume({target=>"cell", value=>2})' in bngl
    assert 'setParameter("cell"' not in bngl
    assert not any(
        warning.get("category") == "event" and warning.get("severity") == "dropped"
        for warning in model.import_warnings
    )


def test_sbml_avogadro_constant_folds_in_fixed_time_event():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="avogadro_event">
        <listOfParameters><parameter id="p" value="0" constant="false"/></listOfParameters>
        <listOfEvents><event id="set_p">
          <trigger><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><gt/>
              <csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol>
              <apply><divide/>
                <csymbol definitionURL="http://www.sbml.org/sbml/symbols/avogadro">avogadro</csymbol>
                <cn>6.022e23</cn>
              </apply>
            </apply>
          </math></trigger>
          <listOfEventAssignments><eventAssignment variable="p">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    assert "t_end=>1.00002337429" in bngl
    assert 'setParameter("p", "3")' in bngl
    assert not any(
        warning.get("category") == "event" and warning.get("severity") == "dropped"
        for warning in model.import_warnings
    )


def test_sbml_event_with_provably_false_time_conjunction_is_informational():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="false_event">
        <listOfParameters><parameter id="p" value="0" constant="false"/></listOfParameters>
        <listOfEvents><event id="never">
          <trigger><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><and/>
              <apply><gt/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>0.21</cn></apply>
              <apply><leq/><cn>5</cn><cn>5</cn><cn>2</cn></apply>
            </apply>
          </math></trigger>
          <listOfEventAssignments><eventAssignment variable="p">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    event_warnings = [
        warning
        for warning in model.import_warnings
        if warning.get("category") == "event"
    ]
    assert len(event_warnings) == 1
    assert event_warnings[0]["severity"] == "info"
    assert "proven not to fire" in event_warnings[0]["message"]
    assert "begin actions" not in bngl


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


def test_rate_rule_driven_stoichiometry_lowers_to_ode_flux_rules():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="dynamic_stoichiometry_rate_rule">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="X" compartment="c" initialAmount="0"/></listOfSpecies>
        <listOfParameters><parameter id="p" value="1" constant="false"/>
          <parameter id="k" value="2" constant="true"/></listOfParameters>
        <listOfRules><rateRule variable="p"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.1</cn></math></rateRule></listOfRules>
        <listOfReactions><reaction id="r" reversible="false">
          <listOfProducts><speciesReference id="Xref" species="X" stoichiometry="1" constant="false">
            <stoichiometryMath><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>p</ci></math></stoichiometryMath>
          </speciesReference></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math></kineticLaw>
        </reaction></listOfReactions>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    assert "r_produce_X" in bngl
    assert "p_amt" in bngl and "(2) TotalRate" in bngl
    assert "r:" not in bngl
    assert not any(
        warning.get("category") == "stoichiometry"
        and warning.get("severity") in {"dropped", "approximated"}
        for warning in model.import_warnings
    )


def test_state_event_updates_parameter_driven_stoichiometry_matches_libroadrunner(
    tmp_path,
):
    import numpy as np

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level2/version5" level="2" version="5">
      <model id="state_event_parameter_stoichiometry">
        <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
        <listOfSpecies><species id="X" compartment="c" initialConcentration="1"/></listOfSpecies>
        <listOfParameters>
          <parameter id="p1" value="1" constant="false"/>
          <parameter id="k1" value="1"/>
        </listOfParameters>
        <listOfReactions><reaction id="production">
          <listOfProducts><speciesReference id="Xref" species="X">
            <stoichiometryMath><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>p1</ci></math></stoichiometryMath>
          </speciesReference></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k1</ci></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="double_stoichiometry">
          <trigger><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><ci>X</ci><cn>2</cn></apply></math></trigger>
          <listOfEventAssignments><eventAssignment variable="p1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=2, n_steps=200).atomize(xml)

    assert result.success, result.error
    assert "Events NOT simulated" not in result.bngl
    model_path = tmp_path / "state_event_parameter_stoichiometry.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])

    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-9)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", "X"]
    reference = rr.simulate(times=bng_data[:, columns.index("time")])

    jump = int(np.argmin(np.abs(bng_data[:, columns.index("time")] - 1.0)))
    compare = np.ones(len(bng_data), dtype=bool)
    compare[max(0, jump - 1) : min(len(bng_data), jump + 2)] = False
    bng_values = bng_data[compare, columns.index("X_amt")]
    rr_values = reference[compare, reference.colnames.index("X")]
    assert np.max(np.abs(bng_values - rr_values)) <= 5e-10
    assert abs(float(bng_data[-1, columns.index("X_amt")]) - 4.0) <= 1e-8


def test_state_event_updates_species_reference_stoichiometry_matches_libroadrunner(
    tmp_path,
):
    import numpy as np

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
      <model id="state_event_species_reference_stoichiometry">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="X" compartment="c" initialConcentration="0" hasOnlySubstanceUnits="false" constant="false"/></listOfSpecies>
        <listOfParameters><parameter id="k1" value="1" constant="true"/></listOfParameters>
        <listOfReactions><reaction id="production" reversible="true">
          <listOfProducts><speciesReference id="Xref" species="X" stoichiometry="1" constant="false"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k1</ci></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfEvents><event id="triple_stoichiometry" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><ci>X</ci><cn>5</cn></apply></math>
          </trigger>
          <listOfEventAssignments><eventAssignment variable="Xref">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""

    result = Atomizer(quiet_mode=True, t_end=10, n_steps=100).atomize(xml)

    assert result.success, result.error
    assert "Events NOT simulated" not in result.bngl
    model_path = tmp_path / "state_event_species_reference_stoichiometry.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])

    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-9)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", "X"]
    reference = rr.simulate(times=bng_data[:, columns.index("time")])

    bng_values = bng_data[:, columns.index("X_amt")]
    rr_values = reference[:, reference.colnames.index("X")]
    assert np.max(np.abs(bng_values - rr_values)) <= 5e-10
    assert abs(float(bng_values[-1]) - 20.0) <= 1e-8


def test_synthetic_rate_rule_observables_have_stable_order():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="stable_rate_rule_observables">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfParameters><parameter id="z" value="0" constant="false"/>
          <parameter id="a" value="0" constant="false"/></listOfParameters>
        <listOfRules>
          <rateRule variable="z"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></rateRule>
          <rateRule variable="a"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></rateRule>
        </listOfRules>
      </model>
    </sbml>"""

    model = _model(xml)
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    observables = bngl.split("begin observables\n", 1)[1].split("\nend observables", 1)[
        0
    ]

    assert observables.index("a_amt") < observables.index("z_amt")


def _quadratic_rate_rule_event_model(
    *, second_event: bool = False, delayed: bool = False
) -> str:
    delay1 = (
        """<delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1.1</cn></math></delay>"""
        if delayed
        else ""
    )
    delay2 = (
        """<delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1.5</cn></math></delay>"""
        if delayed
        else ""
    )
    second = (
        f"""
      <event id="event2" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><gt/><ci>S3</ci><cn>1.4</cn></apply>
          </math>
        </trigger>
        {delay2}
        <listOfEventAssignments><eventAssignment variable="S1">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
        </eventAssignment></listOfEventAssignments>
      </event>"""
        if second_event
        else ""
    )
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="quadratic_rate_rule_event">
        <listOfParameters>
          <parameter id="S1" value="1" constant="false"/>
          <parameter id="S2" value="2" constant="false"/>
          <parameter id="S3" value="1" constant="false"/>
          <parameter id="k1" value="0.75" constant="true"/>
          <parameter id="k2" value="0.25" constant="true"/>
        </listOfParameters>
        <listOfRules>
          <rateRule variable="S1"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><plus/><apply><times/><ci>k2</ci><ci>S3</ci></apply>
              <apply><times/><cn>-1</cn><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>
            </apply>
          </math></rateRule>
          <rateRule variable="S2"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><plus/><apply><times/><ci>k2</ci><ci>S3</ci></apply>
              <apply><times/><cn>-1</cn><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>
            </apply>
          </math></rateRule>
          <rateRule variable="S3"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><plus/><apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>
              <apply><times/><cn>-1</cn><ci>k2</ci><ci>S3</ci></apply>
            </apply>
          </math></rateRule>
        </listOfRules>
        <listOfEvents><event id="event1" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><lt/><ci>S1</ci><cn>0.75</cn></apply>
            </math>
          </trigger>
          {delay1}
          <listOfEventAssignments><eventAssignment variable="S2">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </eventAssignment></listOfEventAssignments>
        </event>{second}</listOfEvents>
      </model>
    </sbml>"""


def _quadratic_reaction_multi_delay_model() -> str:
    return """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="quadratic_reaction_multi_delay">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="S2" compartment="C" initialAmount="2" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="S3" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k1" value="0.75" constant="true"/>
          <parameter id="k2" value="0.25" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="r1" reversible="false">
            <listOfReactants><speciesReference species="S1"/><speciesReference species="S2"/></listOfReactants>
            <listOfProducts><speciesReference species="S3"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply></math></kineticLaw>
          </reaction>
          <reaction id="r2" reversible="false">
            <listOfReactants><speciesReference species="S3"/></listOfReactants>
            <listOfProducts><speciesReference species="S1"/><speciesReference species="S2"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k2</ci><ci>S3</ci></apply></math></kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents>
          <event id="resetS2" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><lt/><ci>S1</ci><cn>0.75</cn></apply></math></trigger>
            <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></delay>
            <listOfEventAssignments><eventAssignment variable="S2"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>S3</ci></math></eventAssignment></listOfEventAssignments>
          </event>
          <event id="resetS1" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><gt/><ci>S3</ci><cn>1.4</cn></apply></math></trigger>
            <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.25</cn></math></delay>
            <listOfEventAssignments><eventAssignment variable="S1"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></eventAssignment></listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""


def test_quadratic_reaction_events_support_independent_delays(tmp_path):
    import numpy as np

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = _quadratic_reaction_multi_delay_model()
    result = Atomizer(quiet_mode=True, t_end=4, n_steps=800).atomize(xml)

    assert result.success, result.error
    assert "Events NOT simulated" not in result.bngl
    model_path = tmp_path / "quadratic_reaction_multi_delay.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])
    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-9)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", "S1", "S2", "S3"]
    reference = rr.simulate(times=bng_data[:, columns.index("time")])
    state_columns = [columns.index(f"{name}_amt") for name in ("S1", "S2", "S3")]
    jump_indices = np.flatnonzero(
        np.max(np.abs(np.diff(bng_data[:, state_columns], axis=0)), axis=1) > 0.1
    )
    assert len(jump_indices) >= 2
    compare = np.ones(len(bng_data), dtype=bool)
    compare[jump_indices] = False
    compare[jump_indices + 1] = False
    for name in ("S1", "S2", "S3"):
        bng_values = bng_data[compare, columns.index(f"{name}_amt")]
        rr_values = reference[compare, reference.colnames.index(name)]
        scale = max(float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values))))
        assert float(np.max(np.abs(bng_values - rr_values))) <= max(5e-10, 1e-5 * scale)


def _quadratic_species_difference_multi_delay_model(*, rank_two: bool = False) -> str:
    second_reaction_s3_stoichiometry = ' stoichiometry="2"' if rank_two else ""
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="quadratic_species_difference_multi_delay">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="0.001" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="S2" compartment="C" initialAmount="0.0012" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="S3" compartment="C" initialAmount="0.002" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="S4" compartment="C" initialAmount="0.001" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k1" value="750" constant="true"/>
          <parameter id="k2" value="250" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="r1" reversible="false">
            <listOfReactants><speciesReference species="S1"/><speciesReference species="S2"/></listOfReactants>
            <listOfProducts><speciesReference species="S3"/><speciesReference species="S4"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply></math></kineticLaw>
          </reaction>
          <reaction id="r2" reversible="false">
            <listOfReactants><speciesReference species="S3"{second_reaction_s3_stoichiometry}/><speciesReference species="S4"/></listOfReactants>
            <listOfProducts><speciesReference species="S1"/><speciesReference species="S2"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k2</ci><ci>S3</ci><ci>S4</ci></apply></math></kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents>
          <event id="resetS1" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><gt/><ci>S4</ci><ci>S2</ci></apply></math></trigger>
            <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.5</cn></math></delay>
            <listOfEventAssignments><eventAssignment variable="S1"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.002</cn></math></eventAssignment></listOfEventAssignments>
          </event>
          <event id="resetS4" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><gt/><ci>S3</ci><cn>0.00225</cn></apply></math></trigger>
            <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.75</cn></math></delay>
            <listOfEventAssignments><eventAssignment variable="S4"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.001</cn></math></eventAssignment></listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""


def test_quadratic_delayed_event_group_supports_species_difference_trigger(tmp_path):
    import numpy as np

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = _quadratic_species_difference_multi_delay_model()
    result = Atomizer(quiet_mode=True, t_end=4, n_steps=800).atomize(xml)

    assert result.success, result.error
    assert "Events NOT simulated" not in result.bngl
    model_path = tmp_path / "quadratic_species_difference_multi_delay.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])
    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-9)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", "S1", "S2", "S3", "S4"]
    reference = rr.simulate(times=bng_data[:, columns.index("time")])
    state_columns = [columns.index(f"{name}_amt") for name in ("S1", "S2", "S3", "S4")]
    jump_indices = np.flatnonzero(
        np.max(np.abs(np.diff(bng_data[:, state_columns], axis=0)), axis=1) > 1e-4
    )
    assert len(jump_indices) >= 2
    compare = np.ones(len(bng_data), dtype=bool)
    compare[jump_indices] = False
    compare[jump_indices + 1] = False
    for name in ("S1", "S2", "S3", "S4"):
        bng_values = bng_data[compare, columns.index(f"{name}_amt")]
        rr_values = reference[compare, reference.colnames.index(name)]
        scale = max(float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values))))
        assert float(np.max(np.abs(bng_values - rr_values))) <= max(5e-10, 1e-5 * scale)


def test_quadratic_difference_group_keeps_rank_two_events_unsupported():
    from bionetgen.atomizer.modern import Atomizer

    result = Atomizer(quiet_mode=True, t_end=4, n_steps=40).atomize(
        _quadratic_species_difference_multi_delay_model(rank_two=True)
    )

    assert result.success, result.error
    assert "Events NOT simulated" in result.bngl


@pytest.mark.parametrize(
    "second_event,delayed", ((False, False), (True, False), (False, True), (True, True))
)
def test_quadratic_rate_rule_state_events_match_libroadrunner(
    tmp_path, second_event, delayed
):
    import numpy as np

    roadrunner = pytest.importorskip("roadrunner")
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import load

    xml = _quadratic_rate_rule_event_model(second_event=second_event, delayed=delayed)
    t_end = 4 if delayed else 2
    result = Atomizer(quiet_mode=True, t_end=t_end, n_steps=200 * t_end).atomize(xml)

    assert result.success, result.error
    assert "Events NOT simulated" not in result.bngl

    model_path = tmp_path / "quadratic_rate_rule_events.bngl"
    model_path.write_text(result.bngl, encoding="utf-8")
    load(model_path).execute()
    lines = model_path.with_suffix(".gdat").read_text().splitlines()
    columns = lines[0].lstrip("# ").split()
    bng_data = np.loadtxt(lines[1:])
    times = bng_data[:, columns.index("time")]

    rr = roadrunner.RoadRunner(xml)
    rr.integrator.setValue("relative_tolerance", 1e-9)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", "S1", "S2", "S3"]
    reference = rr.simulate(times=times)
    state_columns = [columns.index(f"{name}_amt") for name in ("S1", "S2", "S3")]
    jump_indices = np.flatnonzero(
        np.max(np.abs(np.diff(bng_data[:, state_columns], axis=0)), axis=1) > 0.1
    )
    assert len(jump_indices) >= (2 if second_event else 1)
    compare = np.ones(len(times), dtype=bool)
    compare[jump_indices] = False
    compare[jump_indices + 1] = False
    for name in ("S1", "S2", "S3"):
        bng_values = bng_data[compare, columns.index(f"{name}_amt")]
        rr_values = reference[compare, reference.colnames.index(name)]
        scale = max(float(np.max(np.abs(bng_values))), float(np.max(np.abs(rr_values))))
        assert float(np.max(np.abs(bng_values - rr_values))) <= max(5e-10, 1e-5 * scale)
