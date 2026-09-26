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
    assert 't_end=>1' in result.bngl
    assert 'setParameter("P", "7")' in result.bngl
    assert "untranslated" not in result.bngl.lower()


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
