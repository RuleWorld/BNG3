"""Source-derived tests for the Playground SBML unit-normalization contract."""

from __future__ import annotations

import math
from collections import OrderedDict

import pytest

from bionetgen.atomizer.modern.types import (
    SBMLCompartment,
    SBMLKineticLaw,
    SBMLModel,
    SBMLParameter,
    SBMLReaction,
    SBMLSpecies,
)
from bionetgen.atomizer.modern.units import (
    apply_unit_scaling,
    resolve_unit_factor,
    unit_conversion_factor,
)


def test_playground_unit_conversion_factor_uses_all_term_fields():
    terms = [(0, -3, 1, 2), (0, 2, 2, 1)]

    assert unit_conversion_factor(terms) == pytest.approx(20.0)
    assert unit_conversion_factor(
        [{"scale": "invalid", "exponent": "invalid", "multiplier": "invalid"}]
    ) == pytest.approx(1.0)


def test_playground_resolve_unit_factor_treats_base_and_unknown_units_as_noops():
    model = SBMLModel(
        id="units",
        unit_definitions=OrderedDict([("mM", [(0, -3, 1, 1)])]),
    )

    assert resolve_unit_factor("mM", model) == pytest.approx(1e-3)
    assert resolve_unit_factor("litre", model) == pytest.approx(1.0)
    assert resolve_unit_factor("not_declared", model) == pytest.approx(1.0)
    assert resolve_unit_factor("", model) == pytest.approx(1.0)


def test_playground_apply_unit_scaling_covers_parameters_compartments_and_species():
    model = SBMLModel(
        id="units",
        substance_units="mmol",
        volume_units="litre",
        area_units="cm2",
        length_units="cm",
        unit_definitions=OrderedDict(
            [
                ("mmol", [(0, -3, 1, 1)]),
                ("cm", [(0, -2, 1, 1)]),
                ("cm2", [(0, -2, 2, 1)]),
            ]
        ),
        parameters=OrderedDict([("k", SBMLParameter(id="k", value=4, units="mmol"))]),
        reactions=OrderedDict(
            [
                (
                    "r",
                    SBMLReaction(
                        id="r",
                        kinetic_law=SBMLKineticLaw(
                            local_parameters=[
                                SBMLParameter(id="local", value=5, units="mmol")
                            ]
                        ),
                    ),
                )
            ]
        ),
        compartments=OrderedDict(
            [
                ("cell", SBMLCompartment(id="cell", spatial_dimensions=3, size=2)),
                (
                    "membrane",
                    SBMLCompartment(id="membrane", spatial_dimensions=2, size=3),
                ),
                ("line", SBMLCompartment(id="line", spatial_dimensions=1, size=4)),
            ]
        ),
        species=OrderedDict(
            [
                (
                    "A",
                    SBMLSpecies(
                        id="A",
                        compartment="cell",
                        initial_amount=3,
                        initial_concentration=2,
                    ),
                ),
                (
                    "B",
                    SBMLSpecies(
                        id="B",
                        compartment="membrane",
                        initial_amount=5,
                        initial_concentration=7,
                    ),
                ),
            ]
        ),
    )

    warnings = apply_unit_scaling(model)

    assert model.parameters["k"].value == pytest.approx(0.004)
    assert model.reactions["r"].kinetic_law.local_parameters[0].value == pytest.approx(
        0.005
    )
    assert model.compartments["membrane"].size == pytest.approx(3e-4)
    assert model.compartments["line"].size == pytest.approx(0.04)
    assert model.species["A"].initial_amount == pytest.approx(0.003)
    assert model.species["A"].initial_concentration == pytest.approx(0.002)
    assert model.species["B"].initial_amount == pytest.approx(0.005)
    assert model.species["B"].initial_concentration == pytest.approx(70.0)
    assert len(warnings) == 9
    assert warnings[-1]["category"] == "units"
    assert "Applied SBML unit conversion" in warnings[-1]["message"]


def test_playground_unit_scaling_leaves_nonfinite_parameters_untouched():
    parameter = SBMLParameter(id="nan", value=math.nan, units="mmol")
    model = SBMLModel(
        id="units",
        unit_definitions=OrderedDict([("mmol", [(0, -3, 1, 1)])]),
        parameters=OrderedDict([("nan", parameter)]),
    )

    warnings = apply_unit_scaling(model)

    assert math.isnan(parameter.value)
    assert warnings == []


def test_unit_scaling_preserves_reaction_law_coordinates_for_unqualified_parameter():
    from bionetgen.atomizer.modern import SBMLSpeciesReference

    reaction = SBMLReaction(
        id="dimerize",
        reactants=[SBMLSpeciesReference(species="A", stoichiometry=2)],
        products=[SBMLSpeciesReference(species="B", stoichiometry=1)],
        kinetic_law=SBMLKineticLaw("cell * k * A * A"),
    )
    model = SBMLModel(
        id="rate-units",
        substance_units="substance",
        volume_units="vol",
        unit_definitions=OrderedDict([("vol", [(0, -15, 1, 1)])]),
        compartments=OrderedDict(
            [("cell", SBMLCompartment(id="cell", size=2, spatial_dimensions=3))]
        ),
        species=OrderedDict(
            [
                (
                    "A",
                    SBMLSpecies(
                        id="A",
                        compartment="cell",
                        initial_concentration=1,
                        has_only_substance_units=False,
                    ),
                ),
                (
                    "B",
                    SBMLSpecies(
                        id="B",
                        compartment="cell",
                        initial_concentration=0,
                        has_only_substance_units=False,
                    ),
                ),
            ]
        ),
        parameters=OrderedDict([("k", SBMLParameter(id="k", value=0.1))]),
        reactions=OrderedDict([("dimerize", reaction)]),
    )

    apply_unit_scaling(model)

    original_flux = 2 * 0.1 * 1 * 1
    normalized_symbols = {
        "cell": model.compartments["cell"].size,
        "A": model.species["A"].initial_concentration,
        "k": model.parameters["k"].value,
    }
    normalized_flux = eval(
        reaction.kinetic_law.math, {"__builtins__": {}}, normalized_symbols
    )
    assert normalized_flux == pytest.approx(original_flux)


@pytest.mark.parametrize("atomize_mode", [True, False], ids=["atomized", "flat"])
def test_atomizer_native_trajectory_matches_source_law_with_unqualified_rate_units(
    atomize_mode,
):
    import bionetgen._bionetgen_cpp as cpp
    import libsbml
    import roadrunner
    from bionetgen import BioNetGenModel
    from bionetgen.atomizer.modern import Atomizer

    source = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2"><model id="m" substanceUnits="milli_item" volumeUnits="vol" timeUnits="second"><listOfUnitDefinitions><unitDefinition id="vol"><listOfUnits><unit kind="litre" exponent="1" scale="-15" multiplier="1"/></listOfUnits></unitDefinition><unitDefinition id="milli_item"><listOfUnits><unit kind="item" exponent="1" scale="-3" multiplier="1"/></listOfUnits></unitDefinition></listOfUnitDefinitions><listOfCompartments><compartment id="cell" size="2" spatialDimensions="3" constant="true"/></listOfCompartments><listOfSpecies><species id="A" compartment="cell" initialConcentration="1" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/><species id="B" compartment="cell" initialConcentration="0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/></listOfSpecies><listOfParameters><parameter id="k" value="0.1" constant="true"/></listOfParameters><listOfReactions><reaction id="dimerize" reversible="false"><listOfReactants><speciesReference species="A" stoichiometry="2" constant="true"/></listOfReactants><listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts><kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>cell</ci><ci>k</ci><ci>A</ci><ci>A</ci></apply></math></kineticLaw></reaction></listOfReactions></model></sbml>"""
    document = libsbml.readSBMLFromString(source)
    document.checkConsistency()
    assert document.getModel() is not None
    assert not [
        document.getError(index).getMessage()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    t_end = 1e-8
    source_model = roadrunner.RoadRunner(source)
    source_result = source_model.simulate(
        0, t_end, 10, selections=["time", "[A]", "[B]"]
    )
    atomized = Atomizer(
        quiet_mode=True, t_end=t_end, n_steps=10, atomize=atomize_mode
    ).atomize(source)
    assert atomized.success, atomized.error
    result = BioNetGenModel(cpp.parse_string(atomized.bngl)).simulate(
        method="ode", t_start=0, t_end=t_end, n_steps=10, rtol=1e-7, atol=1e-12
    )

    # Independent source concentrations are converted to source-coordinate
    # amounts with V=2, then from milli-item to item for native BNG observables.
    assert result.observables["A_amt"][-1] == pytest.approx(
        0.001 * 2 * source_result[-1, 1], rel=1e-7, abs=1e-12
    )
    assert result.observables["B_amt"][-1] == pytest.approx(
        0.001 * 2 * source_result[-1, 2], rel=1e-6, abs=1e-12
    )
    # Analytically, v=V*k*(A/V)^2 and A_amount(0)=2 milli-item, so
    # dA_amount/dt=-0.1*A_amount^2 in that source coordinate.
    expected_a_amount = 0.001 * 2 / (1 + 0.2 * t_end)
    expected_b_amount = 0.001 * (2 - expected_a_amount / 0.001) / 2
    assert result.observables["A_amt"][-1] == pytest.approx(
        expected_a_amount, rel=1e-7, abs=1e-12
    )
    assert result.observables["B_amt"][-1] == pytest.approx(
        expected_b_amount, rel=1e-6, abs=1e-12
    )


def test_unit_scaling_rewrites_function_and_assignment_coordinates_without_capture():
    from bionetgen.atomizer.modern.types import (
        SBMLEvent,
        SBMLEventAssignment,
        SBMLFunctionDefinition,
        SBMLInitialAssignment,
        SBMLRule,
    )

    model = SBMLModel(
        id="expression-coordinates",
        substance_units="substance",
        volume_units="litre",
        unit_definitions=OrderedDict([("substance", [(0, -3, 1, 1)])]),
        compartments=OrderedDict(
            [("cell", SBMLCompartment(id="cell", size=1, spatial_dimensions=3))]
        ),
        species=OrderedDict(
            [
                (
                    "S",
                    SBMLSpecies(
                        id="S",
                        compartment="cell",
                        initial_amount=2,
                        has_only_substance_units=True,
                    ),
                )
            ]
        ),
        parameters=OrderedDict(
            [("k", SBMLParameter(id="k", value=4, units="substance"))]
        ),
        function_definitions=OrderedDict(
            [
                ("inner", SBMLFunctionDefinition("inner", math="x*x", arguments=["x"])),
                (
                    "outer",
                    SBMLFunctionDefinition("outer", math="inner(k)", arguments=["k"]),
                ),
            ]
        ),
        rules=[SBMLRule(type="assignment", variable="S", math="outer(k)")],
        initial_assignments=[SBMLInitialAssignment(symbol="S", math="k + 1e-15")],
        events=[
            SBMLEvent(
                id="assign-s",
                trigger="S > 1e-15",
                delay="k",
                priority="k",
                assignments=[SBMLEventAssignment(variable="S", math="k")],
            )
        ],
    )

    apply_unit_scaling(model)

    # Species and parameter identifiers both use source substance coordinates.
    # The outer formal named k must bind to its local actual, not capture the
    # scaled global parameter k while the nested function is expanded.
    rule_value = eval(model.rules[0].math, {"__builtins__": {}}, {"k": 0.004})
    expected_rule_value = 0.001 * (4**2)
    assert rule_value == pytest.approx(expected_rule_value)
    initial_value = eval(
        model.initial_assignments[0].math,
        {"__builtins__": {}},
        {"k": 0.004},
    )
    assert initial_value == pytest.approx(0.001 * (4 + 1e-15))
    assert "e /" not in model.initial_assignments[0].math
    event = model.events[0]
    assert eval(event.trigger, {"__builtins__": {}}, {"S": 0.002})
    assert eval(event.delay, {"__builtins__": {}}, {"k": 0.004}) == pytest.approx(4)
    assert eval(event.priority, {"__builtins__": {}}, {"k": 0.004}) == pytest.approx(4)
    event_assignment = eval(
        event.assignments[0].math,
        {"__builtins__": {}},
        {"k": 0.004},
    )
    assert event_assignment == pytest.approx(0.004)


def test_unit_scaling_local_parameter_shadows_global_parameter_in_reaction_law():
    from bionetgen.atomizer.modern.types import SBMLSpeciesReference

    reaction = SBMLReaction(
        id="r",
        reactants=[SBMLSpeciesReference(species="A", stoichiometry=1)],
        products=[SBMLSpeciesReference(species="B", stoichiometry=1)],
        kinetic_law=SBMLKineticLaw(
            "k * A",
            local_parameters=[SBMLParameter(id="k", value=3, units="local_unit")],
        ),
    )
    model = SBMLModel(
        id="shadowing",
        substance_units="substance",
        volume_units="litre",
        unit_definitions=OrderedDict(
            [
                ("substance", [(0, -3, 1, 1)]),
                ("global_unit", [(0, -2, 1, 1)]),
                ("local_unit", [(0, -1, 1, 1)]),
            ]
        ),
        species=OrderedDict(
            [
                (
                    "A",
                    SBMLSpecies(
                        id="A", initial_amount=2, has_only_substance_units=True
                    ),
                ),
                (
                    "B",
                    SBMLSpecies(
                        id="B", initial_amount=0, has_only_substance_units=True
                    ),
                ),
            ]
        ),
        parameters=OrderedDict(
            [("k", SBMLParameter(id="k", value=5, units="global_unit"))]
        ),
        reactions=OrderedDict([("r", reaction)]),
    )

    apply_unit_scaling(model)

    # The local k value is 0.3, while the global k is 0.05.  The emitted law
    # must retain local scope and invert the local coordinate factor 0.1.
    normalized_flux = eval(
        reaction.kinetic_law.math,
        {"__builtins__": {}},
        {"k": 0.3, "A": 0.002},
    )
    assert normalized_flux == pytest.approx(0.001 * 3 * 2)


def test_unit_scaling_keeps_source_time_coordinate_for_rate_laws():
    from bionetgen.atomizer.modern.types import SBMLSpeciesReference

    reaction = SBMLReaction(
        id="r",
        reactants=[SBMLSpeciesReference(species="A", stoichiometry=1)],
        products=[SBMLSpeciesReference(species="B", stoichiometry=1)],
        kinetic_law=SBMLKineticLaw("k"),
    )
    model = SBMLModel(
        id="time-coordinate",
        substance_units="substance",
        volume_units="litre",
        time_units="minute",
        extent_units="substance",
        unit_definitions=OrderedDict(
            [
                ("per_minute", [(0, 0, -1, 60)]),
            ]
        ),
        species=OrderedDict(
            [
                (
                    "A",
                    SBMLSpecies(
                        id="A", initial_amount=1, has_only_substance_units=True
                    ),
                ),
                (
                    "B",
                    SBMLSpecies(
                        id="B", initial_amount=0, has_only_substance_units=True
                    ),
                ),
            ]
        ),
        parameters=OrderedDict(
            [("k", SBMLParameter(id="k", value=6, units="per_minute"))]
        ),
        reactions=OrderedDict([("r", reaction)]),
    )

    apply_unit_scaling(model)

    # Simulation time remains in source minutes; scaling k to per-second and
    # then evaluating it at that same numeric time would double-convert time.
    assert model.parameters["k"].value == pytest.approx(0.1)
    source_rate = eval(reaction.kinetic_law.math, {"__builtins__": {}}, {"k": 0.1})
    assert source_rate == pytest.approx(6)


def test_unit_scaling_uses_common_species_amount_scale_when_extent_units_omitted():
    from bionetgen.atomizer.modern.types import SBMLSpeciesReference

    reaction = SBMLReaction(
        id="r",
        reactants=[SBMLSpeciesReference(species="A", stoichiometry=1)],
        products=[SBMLSpeciesReference(species="B", stoichiometry=1)],
        kinetic_law=SBMLKineticLaw("k"),
    )
    model = SBMLModel(
        id="omitted-extent-units",
        substance_units="milli_item",
        volume_units="litre",
        unit_definitions=OrderedDict([("milli_item", [(0, -3, 1, 1)])]),
        species=OrderedDict(
            [
                (
                    "A",
                    SBMLSpecies(
                        id="A", initial_amount=2, has_only_substance_units=True
                    ),
                ),
                (
                    "B",
                    SBMLSpecies(
                        id="B", initial_amount=0, has_only_substance_units=True
                    ),
                ),
            ]
        ),
        parameters=OrderedDict([("k", SBMLParameter(id="k", value=4))]),
        reactions=OrderedDict([("r", reaction)]),
    )

    apply_unit_scaling(model)

    normalized_rate = eval(reaction.kinetic_law.math, {"__builtins__": {}}, {"k": 4})
    assert normalized_rate == pytest.approx(0.004)


def test_unit_scaling_accounts_for_conversion_factor_coordinate_and_reaction_ids():
    from bionetgen.atomizer.modern.types import SBMLRule, SBMLSpeciesReference

    r1 = SBMLReaction(
        id="r1",
        reactants=[SBMLSpeciesReference(species="A", stoichiometry=1)],
        products=[SBMLSpeciesReference(species="B", stoichiometry=1)],
        kinetic_law=SBMLKineticLaw("v"),
    )
    r2 = SBMLReaction(
        id="r2",
        reactants=[SBMLSpeciesReference(species="B", stoichiometry=1)],
        products=[SBMLSpeciesReference(species="C", stoichiometry=1)],
        kinetic_law=SBMLKineticLaw("r1 + v"),
    )
    model = SBMLModel(
        id="conversion-factor-coordinates",
        substance_units="milli_item",
        volume_units="litre",
        conversion_factor="cf",
        extent_units="centi_item",
        unit_definitions=OrderedDict(
            [
                ("milli_item", [(0, -3, 1, 1)]),
                ("centi_item", [(0, -2, 1, 1)]),
                ("cf_scale", [(0, 0, 1, 2)]),
            ]
        ),
        species=OrderedDict(
            [
                (
                    name,
                    SBMLSpecies(
                        id=name, initial_amount=1, has_only_substance_units=True
                    ),
                )
                for name in ("A", "B", "C")
            ]
        ),
        parameters=OrderedDict(
            [
                ("cf", SBMLParameter(id="cf", value=2, units="cf_scale")),
                ("v", SBMLParameter(id="v", value=3)),
            ]
        ),
        reactions=OrderedDict([("r1", r1), ("r2", r2)]),
        rules=[SBMLRule(type="assignment", variable="q", math="r1 + r2")],
    )

    apply_unit_scaling(model)

    assert model.parameters["cf"].value == pytest.approx(4)
    r1_value = eval(r1.kinetic_law.math, {"__builtins__": {}}, {"v": 3})
    r2_value = eval(
        r2.kinetic_law.math,
        {"__builtins__": {}},
        {"r1": r1_value, "v": 3},
    )
    q_value = eval(
        model.rules[0].math,
        {"__builtins__": {}},
        {"r1": r1_value, "r2": r2_value},
    )
    assert r1_value == pytest.approx(0.0015)
    assert r2_value == pytest.approx(0.003)
    assert q_value == pytest.approx(9)


def test_unit_scaling_treats_zero_dimensional_species_symbols_as_amounts():
    from bionetgen.atomizer.modern.types import SBMLInitialAssignment

    model = SBMLModel(
        id="zero-dimensional",
        substance_units="milli_item",
        volume_units="large_volume",
        unit_definitions=OrderedDict(
            [
                ("milli_item", [(0, -3, 1, 1)]),
                ("large_volume", [(0, 3, 1, 1)]),
            ]
        ),
        compartments=OrderedDict(
            [
                (
                    "space",
                    SBMLCompartment(
                        id="space",
                        size=2,
                        spatial_dimensions=0,
                    ),
                )
            ]
        ),
        species=OrderedDict(
            [
                (
                    "S",
                    SBMLSpecies(
                        id="S",
                        compartment="space",
                        initial_amount=2,
                        has_only_substance_units=False,
                    ),
                )
            ]
        ),
        initial_assignments=[SBMLInitialAssignment(symbol="q", math="S")],
    )

    apply_unit_scaling(model)

    assert model.compartments["space"].size == pytest.approx(2)
    assert eval(
        model.initial_assignments[0].math,
        {"__builtins__": {}},
        {"S": 0.002},
    ) == pytest.approx(2)


@pytest.mark.parametrize("atomize_mode", [True, False], ids=["atomized", "flat"])
def test_zero_dimensional_native_trajectory_matches_roadrunner(atomize_mode):
    import bionetgen._bionetgen_cpp as cpp
    import libsbml
    import numpy as np
    import roadrunner
    from bionetgen import BioNetGenModel
    from bionetgen.atomizer.modern import Atomizer

    source = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2"><model id="zero_dim" substanceUnits="milli_item" volumeUnits="large_volume" timeUnits="second"><listOfUnitDefinitions><unitDefinition id="milli_item"><listOfUnits><unit kind="item" exponent="1" scale="-3" multiplier="1"/></listOfUnits></unitDefinition><unitDefinition id="large_volume"><listOfUnits><unit kind="litre" exponent="1" scale="3" multiplier="1"/></listOfUnits></unitDefinition></listOfUnitDefinitions><listOfCompartments><compartment id="space" size="1" spatialDimensions="0" constant="true"/></listOfCompartments><listOfSpecies><species id="A" compartment="space" initialAmount="2" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/><species id="B" compartment="space" initialAmount="0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/></listOfSpecies><listOfParameters><parameter id="k" value="0.1" constant="true"/></listOfParameters><listOfReactions><reaction id="r" reversible="false"><listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants><listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts><kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k</ci><ci>A</ci></apply></math></kineticLaw></reaction></listOfReactions></model></sbml>"""
    document = libsbml.readSBMLFromString(source)
    document.checkConsistency()
    assert document.getModel() is not None
    assert not [
        document.getError(index).getMessage()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    source_model = roadrunner.RoadRunner(source)
    source_model.integrator.relative_tolerance = 1e-9
    source_model.integrator.absolute_tolerance = 1e-14
    source_result = source_model.simulate(0, 1, 11, selections=["time", "A", "B"])
    translated = Atomizer(
        quiet_mode=True, t_end=1, n_steps=10, atomize=atomize_mode
    ).atomize(source)
    assert translated.success, translated.error
    native = BioNetGenModel(cpp.parse_string(translated.bngl)).simulate(
        method="ode", t_start=0, t_end=1, n_steps=10, rtol=1e-9, atol=1e-14
    )

    np.testing.assert_allclose(
        native.observables["A_amt"], 0.001 * source_result[:, 1], rtol=1e-8, atol=1e-12
    )
    np.testing.assert_allclose(
        native.observables["B_amt"], 0.001 * source_result[:, 2], rtol=1e-8, atol=1e-12
    )


def test_atomizer_refuses_unresolved_function_chain_when_scaled_actual_is_used():
    import libsbml
    from bionetgen.atomizer.modern import Atomizer

    functions = []
    for index in range(22):
        call = f"<ci>f{index + 1}</ci><ci>x</ci>" if index < 21 else "<ci>x</ci>"
        body = f"<apply>{call}</apply>" if index < 21 else "<ci>x</ci>"
        functions.append(
            f'<functionDefinition id="f{index}"><math xmlns="http://www.w3.org/1998/Math/MathML">'
            f"<lambda><bvar><ci>x</ci></bvar>{body}</lambda></math></functionDefinition>"
        )
    source = (
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">'
        '<model id="unresolved_scaled_function" substanceUnits="substance" '
        'volumeUnits="litre" extentUnits="substance">'
        '<listOfUnitDefinitions><unitDefinition id="substance"><listOfUnits>'
        '<unit kind="mole" exponent="1" scale="-3" multiplier="1"/>'
        "</listOfUnits></unitDefinition></listOfUnitDefinitions>"
        "<listOfFunctionDefinitions>"
        + "".join(functions)
        + '</listOfFunctionDefinitions><listOfCompartments><compartment id="cell" '
        'size="1" spatialDimensions="3" constant="true"/></listOfCompartments>'
        '<listOfSpecies><species id="A" compartment="cell" initialAmount="1" '
        'hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>'
        '<species id="B" compartment="cell" initialAmount="0" '
        'hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>'
        '</listOfSpecies><listOfParameters><parameter id="k" value="1" '
        'units="substance" constant="true"/></listOfParameters><listOfReactions>'
        '<reaction id="r" reversible="false"><listOfReactants><speciesReference '
        'species="A" stoichiometry="1" constant="true"/></listOfReactants>'
        '<listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/>'
        '</listOfProducts><kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<apply><times/><ci>k</ci><apply><ci>f0</ci><ci>A</ci></apply></apply>"
        "</math></kineticLaw></reaction></listOfReactions></model></sbml>"
    )
    document = libsbml.readSBMLFromString(source)
    document.checkConsistency()
    assert document.getModel() is not None
    assert not [
        document.getError(index).getMessage()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]

    result = Atomizer(quiet_mode=True).atomize(source)

    assert result.success is False
    assert "unresolved function call" in result.error
    assert "scaled actual arguments" in result.error


def test_atomizer_refuses_reaction_with_unequal_normalized_species_flux_scales():
    import libsbml
    from bionetgen.atomizer.modern import Atomizer

    source = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2"><model id="unequal_flux_scales" substanceUnits="small" volumeUnits="litre"><listOfUnitDefinitions><unitDefinition id="small"><listOfUnits><unit kind="mole" exponent="1" scale="-3" multiplier="1"/></listOfUnits></unitDefinition><unitDefinition id="large"><listOfUnits><unit kind="mole" exponent="1" scale="-2" multiplier="1"/></listOfUnits></unitDefinition></listOfUnitDefinitions><listOfCompartments><compartment id="cell" size="1" spatialDimensions="3" constant="true"/></listOfCompartments><listOfSpecies><species id="A" compartment="cell" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/><species id="B" compartment="cell" initialAmount="0" substanceUnits="large" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/></listOfSpecies><listOfReactions><reaction id="r" reversible="false"><listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants><listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts><kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw></reaction></listOfReactions></model></sbml>"""
    document = libsbml.readSBMLFromString(source)
    document.checkConsistency()
    assert document.getModel() is not None
    assert not [
        document.getError(index).getMessage()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]

    result = Atomizer(quiet_mode=True).atomize(source)

    assert result.success is False
    assert "different normalized flux scales" in result.error

    boundary_source = source.replace(
        'id="B" compartment="cell" initialAmount="0" substanceUnits="large" '
        'hasOnlySubstanceUnits="true" boundaryCondition="false"',
        'id="B" compartment="cell" initialAmount="0" substanceUnits="large" '
        'hasOnlySubstanceUnits="true" boundaryCondition="true"',
    )
    boundary_result = Atomizer(quiet_mode=True).atomize(boundary_source)
    assert boundary_result.success, boundary_result.error
