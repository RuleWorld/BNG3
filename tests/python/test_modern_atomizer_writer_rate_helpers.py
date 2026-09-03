"""Source-derived contracts for Playground writer rate helpers."""

from bionetgen.atomizer.modern import (
    ProcessedRate,
    ReversibleRateSplit,
    SBMLCompartment,
    SBMLFunctionDefinition,
    SBMLKineticLaw,
    SBMLModel,
    SBMLParameter,
    SBMLReaction,
    SBMLSpecies,
    SBMLSpeciesReference,
    checkMassAction,
    inlineSBMLFunctions,
    inline_sbml_functions,
    processReactionRate,
    process_reaction_rate,
    splitReversibleRate,
    split_reversible_rate,
)


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


def test_process_reaction_rate_strips_leading_compartment_before_reversible_split():
    model = _mass_action_model("cell * (kf * A - kr * P)", reversible=True)
    model.parameters.update(
        {
            "kf": SBMLParameter(id="kf", value=0.5),
            "kr": SBMLParameter(id="kr", value=0.25),
        }
    )

    result = process_reaction_rate(model.reactions["r"], "r", model)

    assert result.force_irreversible is False
    assert result.rate_string == "0.5, 0.25"


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
