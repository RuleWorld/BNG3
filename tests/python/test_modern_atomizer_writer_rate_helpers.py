"""Source-derived contracts for Playground writer rate helpers."""

import pytest

from bionetgen.atomizer.modern import (
    ProcessedRate,
    ReversibleRateSplit,
    SBMLCompartment,
    SBMLFunctionDefinition,
    SBMLKineticLaw,
    SBMLModel,
    SBMLParameter,
    SBMLReaction,
    SBMLRule,
    SBMLSpecies,
    SBMLSpeciesReference,
    checkMassAction,
    inlineSBMLFunctions,
    inline_sbml_functions,
    processReactionRate,
    process_reaction_rate,
    splitReversibleRate,
    split_reversible_rate,
    writeReactionRulesAtomized,
    writeReactionRulesFlat,
    writeReactionRulesFlat_V2,
    write_reaction_rules_atomized,
    write_reaction_rules_flat,
    write_reaction_rules_flat_v2,
)
from bionetgen.atomizer.modern.writer import _contains_static_zero_divisor


def _mass_action_model(rate: str = "k * A", reversible: bool = False) -> SBMLModel:
    return SBMLModel(
        id="rate_processor",
        compartments={"cell": SBMLCompartment(id="cell", size=2)},
        species={
            "A": SBMLSpecies(id="A", compartment="cell"),
            "P": SBMLSpecies(id="P", compartment="cell"),
        },
        parameters={
            "k": SBMLParameter(id="k", value=3),
            "Km": SBMLParameter(id="Km", value=2),
        },
        reactions={
            "r": SBMLReaction(
                id="r",
                reversible=reversible,
                reactants=[SBMLSpeciesReference("A")],
                products=[SBMLSpeciesReference("P")],
                kinetic_law=SBMLKineticLaw(rate),
            )
        },
    )


def test_inline_sbml_functions_substitutes_formals_simultaneously():
    definitions = {
        "f": SBMLFunctionDefinition(id="f", arguments=["x", "y"], math="x + y"),
    }

    result = inline_sbml_functions("f(y, 2)", definitions)

    assert result == "((y) + (2))"
    assert inlineSBMLFunctions("f(1, g(2))", definitions) == "((1) + (g(2)))"


def test_inline_sbml_functions_expands_nested_calls_and_keeps_unknown_calls():
    definitions = {
        "outer": SBMLFunctionDefinition(
            id="outer", arguments=["value"], math="inner(value)"
        ),
        "inner": SBMLFunctionDefinition(id="inner", arguments=["x"], math="x^2"),
    }

    assert inline_sbml_functions("outer(a) + missing(a)", definitions) == (
        "((((a))^2)) + missing(a)"
    )


def test_split_reversible_rate_returns_reference_shaped_forward_and_reverse_laws():
    result = splitReversibleRate("(kf*A - kr*B)")

    assert isinstance(result, ReversibleRateSplit)
    assert result.success is True
    assert result.forward_rate == "kf*A"
    assert result.reverse_rate == "kr*B"
    assert result.forwardRate == result.forward_rate
    assert result.reverseRate == result.reverse_rate


def test_split_reversible_rate_rejects_one_sided_and_preserves_original_input():
    result = split_reversible_rate("  kf*A  ")

    assert result == ReversibleRateSplit(False, "  kf*A  ", "0")


def test_check_mass_action_matches_source_constant_and_rejects_saturation():
    compartments = {"cell": SBMLCompartment(id="cell", size=2)}
    species_to_compartment = {"A": "cell"}

    assert (
        checkMassAction(
            "k * _c_A()",
            "A_amt",
            "__compartment_cell__",
            {"k": 3},
            compartments,
            species_to_compartment,
        )
        == 3
    )
    assert (
        checkMassAction(
            "k * _c_A() / (Km + _c_A())",
            "A_amt",
            "__compartment_cell__",
            {"k": 3, "Km": 2},
            compartments,
            species_to_compartment,
        )
        is None
    )
    assert (
        checkMassAction(
            "-1e-20 * _c_A() * (1 + _c_B())",
            "A_amt",
            "__compartment_cell__",
            {},
            {"cell": SBMLCompartment(id="cell", size=2)},
            {"A": "cell", "B": "cell"},
        )
        is None
    )


def test_check_mass_action_uses_reaction_order_for_concentration_laws():
    compartments = {"cell": SBMLCompartment(id="cell", size=2)}
    species_to_compartment = {"A": "cell", "B": "cell"}

    assert (
        checkMassAction(
            "k * _c_A() * _c_B()",
            "A_amt * B_amt",
            "__compartment_cell__",
            {"k": 3},
            compartments,
            species_to_compartment,
            reaction_order=2,
        )
        == 3
    )


def test_static_zero_divisor_detection_handles_lowered_numeric_denominators():
    assert _contains_static_zero_divisor("20 / 0") is True
    assert _contains_static_zero_divisor("0 / (0 + 0)") is True
    assert _contains_static_zero_divisor("0 / 106.09") is False


def test_generate_bngl_reports_parameter_lowered_division_by_zero():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    model = SBMLModel(
        id="undefined_division",
        species={"A": SBMLSpecies(id="A", initial_amount=1)},
        parameters={"zero": SBMLParameter(id="zero", value=0)},
        rules=[SBMLRule(type="assignment", variable="flux", math="20 / zero")],
    )
    sct = build_species_composition_table(model, atomize=False)
    result = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    assert "flux() = 20 / 0" in result.bngl
    assert any("division by zero" in warning for warning in result.warnings)
    assert any(
        warning["category"] == "mathml"
        and warning["severity"] == "dropped"
        and "division by zero" in warning["message"]
        for warning in model.import_warnings
    )


def test_write_functions_preserves_assignment_rule_that_shadows_parameter():
    from bionetgen.atomizer.modern import write_functions

    model = _mass_action_model()
    model.parameters["T"] = SBMLParameter(id="T", value=0)
    model.rules = [
        SBMLRule(type="assignment", variable="T", math="A"),
        SBMLRule(type="assignment", variable="flux", math="T * A"),
    ]

    lines = write_functions(model)

    assert "T() = A" in lines
    assert "flux() = T() * A" in lines
    assert "flux() = 0 * A" not in lines


def test_bngl_renames_legacy_time_alias_for_sbml_identifiers():
    from bionetgen.atomizer.modern import standardize_name

    assert standardize_name("t") == "t_id"


def test_process_reaction_rate_returns_source_shaped_mass_action_result():
    model = _mass_action_model()

    result = process_reaction_rate(model.reactions["r"], "r", model)

    assert isinstance(result, ProcessedRate)
    assert result.rate_string == "3"
    assert result.rateString == result.rate_string
    assert result.force_irreversible is False
    assert result.forceIrreversible is False
    assert result.is_split_rxn is False
    assert result.isSplitRxn is False
    assert processReactionRate(model.reactions["r"], "r", model) == result


def test_process_reaction_rate_restores_dynamic_reactant_factor_after_stripping():
    model = _mass_action_model("V * A")
    model.rules = [SBMLRule(type="assignment", variable="V", math="k")]

    result = process_reaction_rate(model.reactions["r"], "r", model)

    assert result.rate_string == "V()"
    assert result.is_total_rate is False


def test_process_reaction_rate_preserves_reversible_denominator_fallback():
    model = _mass_action_model("kf * A / (Km + A) - kr * P", reversible=True)
    model.parameters.update(
        {"kf": SBMLParameter(id="kf", value=1), "kr": SBMLParameter(id="kr", value=1)}
    )

    result = process_reaction_rate(model.reactions["r"], "r", model)

    assert result.force_irreversible is True
    assert result.is_split_rxn is True
    assert "_c_A()" in result.rate_string
    assert "Km + _c_A()" in result.rate_string


def test_process_reaction_rate_preserves_outer_compartment_on_net_flux():
    model = _mass_action_model("cell * (kf * A - kr * P)", reversible=True)
    model.parameters.update(
        {
            "kf": SBMLParameter(id="kf", value=0.5),
            "kr": SBMLParameter(id="kr", value=0.25),
        }
    )

    result = process_reaction_rate(model.reactions["r"], "r", model)

    assert result.force_irreversible is True
    assert result.is_total_rate is True
    assert result.rate_string == "__compartment_cell__ * (kf * _c_A() - kr * _c_P())"


def test_process_reaction_rate_preserves_other_compartment_geometry_factors():
    model = SBMLModel(
        id="cross_compartment_rate",
        compartments={
            "cell": SBMLCompartment(id="cell", size=2),
            "membrane": SBMLCompartment(id="membrane", size=3),
        },
        species={
            "A": SBMLSpecies(id="A", compartment="cell"),
            "P": SBMLSpecies(id="P", compartment="membrane"),
        },
        parameters={"k": SBMLParameter(id="k", value=3)},
        reactions={
            "r": SBMLReaction(
                id="r",
                reactants=[SBMLSpeciesReference("A")],
                products=[SBMLSpeciesReference("P")],
                kinetic_law=SBMLKineticLaw("membrane * k * A * (1 + P)"),
            )
        },
    )

    result = process_reaction_rate(model.reactions["r"], "r", model)

    assert "__compartment_membrane__" in result.rate_string


def test_process_reaction_rate_marks_reactant_independent_flux_as_total_rate():
    model = _mass_action_model("cell * 2 * k")

    result = process_reaction_rate(model.reactions["r"], "r", model)

    assert result.is_total_rate is True
    assert result.rate_string == "__compartment_cell__ * 2 * k"


def test_generate_bngl_splits_mixed_total_rate_reversible_directions():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    model = _mass_action_model("sin(A) - kr * P", reversible=True)
    model.parameters["kr"] = SBMLParameter(id="kr", value=0.25)
    processed = process_reaction_rate(model.reactions["r"], "r", model)

    assert processed.forward_is_total_rate is True
    assert processed.reverse_is_total_rate is False
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    assert "r_forward: @cell:M_A() -> @cell:M_P() sin(_c_A()) TotalRate" in bngl
    assert "r_reverse: @cell:M_P() -> @cell:M_A() 0.25\n" in bngl


def test_process_reaction_rate_keeps_numeric_parameter_only_flux_as_total_rate():
    model = _mass_action_model("unitime")
    model.parameters["unitime"] = SBMLParameter(id="unitime", value=1)

    result = process_reaction_rate(model.reactions["r"], "r", model)

    assert result.is_total_rate is True
    assert result.rate_string == "unitime"


def test_writer_reverses_constant_negative_sbml_flux():
    from bionetgen.atomizer.modern import build_species_composition_table

    model = _mass_action_model("-1")
    sct = build_species_composition_table(model, atomize=False)

    result = write_reaction_rules_flat(model, sct)

    assert "r: M_P()@cell -> M_A()@cell 1" in result
    assert any(
        warning["category"] == "rate"
        and warning["severity"] == "info"
        and "reversed the reaction sides" in warning["message"]
        for warning in model.import_warnings
    )


def test_rate_rule_source_sink_reactions_are_total_rates():
    from bionetgen.atomizer.modern import (
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    model = _mass_action_model()
    model.rules = [SBMLRule(type="rate", variable="A", math="k * A")]
    sct = build_species_composition_table(model, atomize=False)
    result = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    assert "__rate_rule_A: 0 -> @cell:M_A() __rate_rule__A() TotalRate" in result.bngl
    assert "__rate_rule_in_A:" not in result.bngl
    assert "__rate_rule_out_A:" not in result.bngl


def test_writer_projects_mixed_conversion_factors_per_species():
    from bionetgen.atomizer.modern import build_species_composition_table

    model = SBMLModel(
        id="mixed_conversion_factors",
        compartments={"cell": SBMLCompartment(id="cell", size=1)},
        species={
            "A": SBMLSpecies(id="A", compartment="cell", conversion_factor="a_factor"),
            "B": SBMLSpecies(id="B", compartment="cell", conversion_factor="b_factor"),
        },
        parameters={
            "a_factor": SBMLParameter(id="a_factor", value=2),
            "b_factor": SBMLParameter(id="b_factor", value=3),
            "k": SBMLParameter(id="k", value=0.5),
        },
        reactions={
            "r": SBMLReaction(
                id="r",
                reversible=True,
                reactants=[SBMLSpeciesReference("A")],
                products=[SBMLSpeciesReference("B")],
                kinetic_law=SBMLKineticLaw("k * A"),
            )
        },
    )
    sct = build_species_composition_table(model, atomize=False)

    result = write_reaction_rules_flat(model, sct)

    assert "r_consume_A: M_A()@cell -> 0 2 * (k * _c_A()) TotalRate" in result
    assert "r_produce_B: 0 -> M_B()@cell 3 * (k * _c_A()) TotalRate" in result
    assert not any(
        warning["severity"] == "dropped" and warning["category"] == "conversionFactor"
        for warning in model.import_warnings
    )
    assert any(
        warning["severity"] == "info"
        and "species-specific TotalRate rules" in warning["message"]
        for warning in model.import_warnings
    )


def test_playground_writer_facade_exports_reference_function_names():
    import bionetgen.atomizer.modern as modern

    assert modern.bnglFunction is modern.bngl_function
    assert modern.generateBNGL is modern.generate_bngl


def test_playground_writer_facade_exports_all_implemented_writer_names():
    import bionetgen.atomizer.modern as modern

    for camel_name, snake_name in (
        ("extendFunction", "extend_function"),
        ("writeParameters", "write_parameters"),
        ("writeCompartments", "write_compartments"),
        ("writeMoleculeTypes", "write_molecule_types"),
        ("writeSeedSpecies", "write_seed_species"),
        ("writeObservables", "write_observables"),
        ("writeFunctions", "write_functions"),
        ("writeReactionRules", "write_reaction_rules"),
    ):
        assert getattr(modern, camel_name) is getattr(modern, snake_name)


def test_playground_writer_exposes_distinct_reaction_rule_entry_points():
    from bionetgen.atomizer.modern import build_species_composition_table

    model = _mass_action_model()
    sct = build_species_composition_table(model, atomize=False)

    flat = write_reaction_rules_flat(model, sct)
    atomized = write_reaction_rules_atomized(model, sct)
    flat_v2 = write_reaction_rules_flat_v2(model, sct)

    assert flat.startswith("begin reaction rules\n")
    assert flat.endswith("\nend reaction rules")
    assert "r: M_A()@cell -> M_P()@cell 3" in flat
    assert atomized == flat
    assert flat_v2 == flat
    assert writeReactionRulesFlat is write_reaction_rules_flat
    assert writeReactionRulesAtomized is write_reaction_rules_atomized
    assert writeReactionRulesFlat_V2 is write_reaction_rules_flat_v2


def test_playground_writer_can_preserve_scoped_local_parameter_names():
    from bionetgen.atomizer.modern import (
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    model = _mass_action_model("local_rate * A")
    model.reactions["r"].kinetic_law = SBMLKineticLaw(
        "local_rate * A",
        local_parameters=[SBMLParameter(id="local_rate", value=7, scope="local")],
    )
    from bionetgen.atomizer.modern import build_species_composition_table

    sct = build_species_composition_table(model, atomize=False)
    result = generate_bngl(
        model,
        sct,
        get_molecule_types(sct),
        get_seed_species(sct, model),
        replace_loc_params=False,
    )

    assert "r_local_rate 7" in result.bngl
    assert "r: @cell:M_A() -> @cell:M_P() r_local_rate" in result.bngl
    assert "r: M_A()@cell -> M_P()@cell 7" not in result.bngl
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    cpp.parse_string(result.bngl)


def test_playground_atomizer_accepts_replace_local_parameters_option():
    from bionetgen.atomizer.modern import Atomizer

    atomizer = Atomizer(replaceLocParams=False)

    assert atomizer.getOptions()["replace_loc_params"] is False
    assert "replaceLocParams" not in atomizer.getOptions()


def test_playground_generate_bngl_returns_named_generation_result():
    from collections import OrderedDict

    from bionetgen.atomizer.modern import (
        SBMLModel,
        SBMLSpecies,
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    model = SBMLModel(
        id="named_generation",
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
    )
    sct = build_species_composition_table(model)
    result = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )

    assert result.bngl.startswith("# BNGL model generated")
    assert result.observableMap == result.observable_map
    assert isinstance(result.warnings, list)
    bngl, observable_map = result
    assert bngl == result.bngl
    assert observable_map == result.observable_map
