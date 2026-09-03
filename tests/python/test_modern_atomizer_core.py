"""Source-derived contracts for the Playground atomization-core facade."""

import pytest

from bionetgen.atomizer.modern import (
    addToDependencyGraph,
    add_to_dependency_graph,
    analyze_reactions,
    analyze_naming_conventions,
    build_species_composition_table,
    classify_reaction,
    defineEditDistanceMatrix,
    findLongestSubstring,
    topological_sort,
)
from bionetgen.atomizer.modern.helpers import logger
from bionetgen.atomizer.modern.types import (
    SBMLModel,
    SBMLKineticLaw,
    SBMLReaction,
    SBMLSpecies,
    SBMLSpeciesReference,
)


def test_dependency_graph_insertion_is_unique_and_accepts_scalar_or_list():
    graph = {}

    addToDependencyGraph(graph, "complex", ["A", "B", "A"])
    add_to_dependency_graph(graph, "complex", "B")

    assert graph == {"complex": ["A", "B"]}


def test_edit_distance_result_keeps_full_matrix_and_legacy_two_value_unpacking():
    result = defineEditDistanceMatrix(["A", "A_P", "far"], 2)

    assert result.matrix == [[0, 2, 3], [2, 0, 3], [3, 3, 0]]
    assert result.pairs == [("A", "A_P")]
    assert result.differences == [["+ _", "+ P"]]

    pairs, differences = result
    assert pairs == result.pairs
    assert differences == result.differences


def test_longest_substring_alias_matches_playground_name():
    assert findLongestSubstring("abc", "zbcx") == "bc"


def test_playground_infer_modification_returns_named_result():
    from bionetgen.atomizer.modern import infer_modification

    result = infer_modification("A_P", ["A"])

    assert result.base == "A"
    assert result.modification == "Phosphorylation"
    assert result.confidence == pytest.approx(1 / 3)
    base, modification, confidence = result
    assert (base, modification, confidence) == (
        result.base,
        result.modification,
        result.confidence,
    )


def test_playground_facade_exports_camel_case_core_functions():
    import bionetgen.atomizer.modern as modern

    aliases = {
        "buildSpeciesCompositionTable": "build_species_composition_table",
        "disambiguateCollidingSpecies": "disambiguate_colliding_species",
        "getMoleculeTypes": "get_molecule_types",
        "getSeedSpecies": "get_seed_species",
        "analyzeReactions": "analyze_reactions",
        "analyzeNamingConventions": "analyze_naming_conventions",
        "topologicalSort": "topological_sort",
        "classifyReaction": "classify_reaction",
    }

    assert all(
        hasattr(modern, camel) and getattr(modern, camel) is getattr(modern, snake)
        for camel, snake in aliases.items()
    )


def test_playground_data_contract_exposes_camel_case_fields():
    from bionetgen.atomizer.modern import (
        AtomizerResult,
        SBMLCompartment,
        SBMLEvent,
        SBMLKineticLaw,
        SBMLModel,
        SBMLParameter,
        SBMLReaction,
        SBMLSpecies,
        SBMLSpeciesReference,
    )

    compartment = SBMLCompartment(id="cell", spatial_dimensions=2, size_set=True)
    assert compartment.spatialDimensions == 2
    assert compartment.sizeSet is True
    compartment.sizeSet = False
    assert compartment.size_set is False

    parameter = SBMLParameter(id="k", value=2)
    species = SBMLSpecies(
        id="A",
        initial_concentration=3,
        initial_amount=4,
        has_only_substance_units=True,
        initial_amount_set=True,
        initial_concentration_set=False,
        sbo_term="SBO:0000252",
        conversion_factor="cf",
        species_type="simple",
    )
    assert species.initialConcentration == 3
    assert species.initialAmount == 4
    assert species.hasOnlySubstanceUnits is True
    assert species.initialAmountSet is True
    assert species.initialConcentrationSet is False
    assert species.sboTerm == "SBO:0000252"
    assert species.conversionFactor == "cf"
    assert species.speciesType == "simple"

    reference = SBMLSpeciesReference(
        "A", stoichiometry_set=True, variable_stoichiometry=True
    )
    assert reference.stoichiometrySet is True
    assert reference.variableStoichiometry is True

    kinetic_law = SBMLKineticLaw("k * A", "<math/>")
    reaction = SBMLReaction(id="r", kinetic_law=kinetic_law, conversion_factor="cf")
    assert kinetic_law.mathML == "<math/>"
    assert kinetic_law.localParameters == kinetic_law.local_parameters
    assert reaction.kineticLaw is kinetic_law
    assert reaction.conversionFactor == "cf"

    event = SBMLEvent(
        id="e",
        use_values_from_trigger_time=False,
        trigger_initial_value=False,
        trigger_persistent=True,
    )
    assert event.useValuesFromTriggerTime is False
    assert event.triggerInitialValue is False
    assert event.triggerPersistent is True

    model = SBMLModel(
        id="m",
        function_definitions={"f": object()},
        species_by_compartment={"cell": ["A"]},
        import_warnings=[{"category": "test"}],
    )
    assert model.functionDefinitions is model.function_definitions
    assert model.speciesByCompartment is model.species_by_compartment
    assert model.importWarnings is model.import_warnings

    result = AtomizerResult("bngl", observable_map={"A": "A"})
    assert result.observableMap is result.observable_map
    result.observableMap = {"B": "B"}
    assert result.observable_map == {"B": "B"}


def test_playground_topological_sort_reports_dependency_cycles():
    logger.clear()
    logger.setLevel("WARNING")
    logger.setQuietMode(True)
    try:
        sorted_species = topological_sort(
            ["A", "B", "C"],
            {"A": {"B"}, "B": {"A"}, "C": {"A"}},
        )
        warnings = logger.getMessagesByLevel("WARNING")
    finally:
        logger.clear()
        logger.setQuietMode(False)

    assert sorted_species == ["B", "A", "C"]
    assert len(warnings) == 1
    assert warnings[0].code == "DEP001"
    assert "A -> B -> A" in warnings[0].message


def test_playground_naming_analysis_reports_summary():
    logger.clear()
    logger.setLevel("INFO")
    logger.setQuietMode(True)
    try:
        analyze_naming_conventions(["A", "A_P"])
        messages = logger.getMessagesByLevel("INFO")
    finally:
        logger.clear()
        logger.setQuietMode(False)

    assert len(messages) == 1
    assert messages[0].code == "NAM001"
    assert messages[0].message == "Naming analysis: 1 similar pairs, 1 classifications"


def test_playground_reaction_analysis_reports_summary():
    model = SBMLModel(
        id="model",
        species={
            "A": SBMLSpecies(id="A", name="A"),
            "B": SBMLSpecies(id="B", name="B"),
            "AB": SBMLSpecies(id="AB", name="AB"),
        },
        reactions={
            "bind": SBMLReaction(
                id="bind",
                reactants=[SBMLSpeciesReference("A"), SBMLSpeciesReference("B")],
                products=[SBMLSpeciesReference("AB")],
            )
        },
    )
    logger.clear()
    logger.setLevel("INFO")
    logger.setQuietMode(True)
    try:
        result = analyze_reactions(model)
        messages = logger.getMessagesByLevel("INFO")
    finally:
        logger.clear()
        logger.setQuietMode(False)

    assert result["bindingReactions"] == {"AB": ["A", "B"]}
    assert len(messages) == 1
    assert messages[0].code == "RXN001"
    assert messages[0].message == "Reaction analysis: 1 binding, 0 modification"


def test_reaction_classification_requires_reference_saturation_shape():
    simple_quotient = SBMLReaction(
        id="simple_quotient",
        reactants=[SBMLSpeciesReference("A"), SBMLSpeciesReference("B")],
        products=[SBMLSpeciesReference("B")],
        kinetic_law=SBMLKineticLaw("k / K"),
    )
    saturation = SBMLReaction(
        id="saturation",
        reactants=[SBMLSpeciesReference("A"), SBMLSpeciesReference("B")],
        products=[SBMLSpeciesReference("B")],
        kinetic_law=SBMLKineticLaw("(vmax * A * B) / (Km + B)"),
    )

    assert classify_reaction(simple_quotient).type == "binding"
    assert classify_reaction(saturation).type == "catalysis"


def test_playground_sct_builder_reports_summary():
    model = SBMLModel(
        id="model",
        species={"A": SBMLSpecies(id="A", name="A")},
    )
    logger.clear()
    logger.setLevel("INFO")
    logger.setQuietMode(True)
    try:
        table = build_species_composition_table(model)
        messages = [
            message
            for message in logger.getMessagesByLevel("INFO")
            if message.code == "SCT001"
        ]
    finally:
        logger.clear()
        logger.setQuietMode(False)

    assert len(table.entries) == 1
    assert len(messages) == 1
    assert messages[0].message == "Built SCT: 1 species (1 elemental, 0 complex)"
