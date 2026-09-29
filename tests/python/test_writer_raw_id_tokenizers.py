"""Raw SBML ids reach the writer unstandardized, so id lookups must read whole ids.

``standardize_name`` runs on a raw species, reaction, rule-variable or function
id only at emission, so an id such as ``A-B`` reaches this module in its source
spelling.  A ``[A-Za-z_][A-Za-z0-9_]*`` token cannot spell such an id: it
matches neither the whole id nor anything that identifies it, and the fragments
it does produce name symbols that do not exist.  Each case below pins the
behaviour that a raw id is recognised as one id -- and, where the reader has no
stake in the id, that it is left exactly as the source spelled it.
"""

from __future__ import annotations

from collections import OrderedDict

from bionetgen.atomizer.modern import (
    SBMLCompartment,
    SBMLKineticLaw,
    SBMLModel,
    SBMLParameter,
    SBMLReaction,
    SBMLRule,
    SBMLSpecies,
    SBMLSpeciesReference,
    SBMLEvent,
    SBMLEventAssignment,
    build_species_composition_table,
    generate_bngl,
    get_molecule_types,
    get_seed_species,
)
from bionetgen.atomizer.modern.writer import (
    _lower_bounded_event_state_delays,
    _rewrite_zero_argument_calls,
    bngl_function,
)


def _species(species_id: str, amount: float = 1.0, constant: bool = False):
    return SBMLSpecies(
        id=species_id,
        compartment="cell",
        initial_amount=amount,
        initial_amount_set=True,
        has_only_substance_units=True,
        constant=constant,
    )


def _emit(model: SBMLModel) -> str:
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    return bngl


def _block(model: SBMLModel, name: str) -> str:
    bngl = _emit(model)
    assert f"begin {name}" in bngl, bngl
    return bngl.split(f"begin {name}")[1].split(f"end {name}")[0].strip()


def _compartment() -> OrderedDict:
    return OrderedDict([("cell", SBMLCompartment(id="cell", size=1.0))])


# --------------------------------------------------------------------------
# Rate expressions: ``map_token`` only ever sees identifier tokens.
# --------------------------------------------------------------------------


def test_bngl_function_maps_a_raw_hyphenated_species_reference():
    species_map = {"A-B": "A-B", "A_B": "A-B", "A": "A", "S": "S"}
    concentration_names = {"A_B", "A", "S"}

    assert (
        bngl_function(
            "k1*(A-B)",
            "R1",
            ["S"],
            ["cell"],
            sbml_to_bngl_id=species_map,
            species_with_conc_functions=concentration_names,
        )
        == "k1*(_c_A_B())"
    )


def test_bngl_function_keeps_a_spaced_difference_apart_from_a_raw_id():
    # ``A - A-B`` is a difference of species A and species ``A-B``; only the
    # trailing run is the hyphenated id.
    species_map = {"A-B": "A-B", "A_B": "A-B", "A": "A", "S": "S"}
    concentration_names = {"A_B", "A", "S"}

    assert (
        bngl_function(
            "k1 * (A - A-B)",
            "R1",
            ["S"],
            ["cell"],
            sbml_to_bngl_id=species_map,
            species_with_conc_functions=concentration_names,
        )
        == "k1 * (_c_A() - _c_A_B())"
    )


def test_reaction_rate_maps_a_raw_hyphenated_species_to_its_amount_observable():
    model = SBMLModel(
        id="rate-raw-species",
        compartments=_compartment(),
        species=OrderedDict([("A-B", _species("A-B")), ("B", _species("B"))]),
        parameters=OrderedDict(
            [("k1", SBMLParameter(id="k1", value=0.5, constant=True))]
        ),
        reactions=OrderedDict(
            [
                (
                    "R1",
                    SBMLReaction(
                        id="R1",
                        reactants=[
                            SBMLSpeciesReference(species="A-B", stoichiometry=1),
                            SBMLSpeciesReference(species="B", stoichiometry=1),
                        ],
                        products=[],
                        kinetic_law=SBMLKineticLaw(math="k1*(A-B)^2"),
                    ),
                )
            ]
        ),
    )

    assert _block(model, "reaction rules") == (
        "R1: @cell:M_A_B() + @cell:M_B() -> 0 k1*(A_B_amt)^2 TotalRate"
    )


# --------------------------------------------------------------------------
# ``rateOf`` inlining: a reaction id is a whole id, not two tokens.
# --------------------------------------------------------------------------


def _rate_of_model(reaction_id: str, rule_math: str) -> SBMLModel:
    return SBMLModel(
        id="rate-of",
        compartments=_compartment(),
        species=OrderedDict([("S1", _species("S1")), ("S2", _species("S2"))]),
        reactions=OrderedDict(
            [
                (
                    reaction_id,
                    SBMLReaction(
                        id=reaction_id,
                        reactants=[SBMLSpeciesReference(species="S1", stoichiometry=1)],
                        products=[SBMLSpeciesReference(species="S2", stoichiometry=1)],
                        kinetic_law=SBMLKineticLaw(math="k1*S1"),
                    ),
                )
            ]
        ),
        parameters=OrderedDict(
            [("k1", SBMLParameter(id="k1", value=0.5, constant=True))]
        ),
        rules=[SBMLRule(type="assignment", variable="S2", math=rule_math)],
    )


def test_rate_of_a_hyphenated_reaction_id_is_inlined():
    hyphenated = _block(_rate_of_model("R-1", "rateOf(R-1)"), "functions")
    assert "R-1" not in hyphenated
    assert "S2() = rateOf((k1*S1_amt))" in hyphenated


def test_hyphenated_reaction_id_inlines_the_same_flux_as_its_standardized_form():
    hyphenated = _block(_rate_of_model("R-1", "rateOf(R-1)"), "functions")
    standardized = _block(_rate_of_model("R_1", "rateOf(R_1)"), "functions")
    assert "S2() = " in hyphenated
    assert hyphenated == standardized


# --------------------------------------------------------------------------
# Zero-argument function calls: the body carries raw ids this pass does not own.
# --------------------------------------------------------------------------


def test_zero_argument_rewrite_leaves_a_raw_species_id_intact():
    assert _rewrite_zero_argument_calls("A-B", ["B"]) == "A-B"
    assert _rewrite_zero_argument_calls("A-B", ["A"]) == "A-B"
    assert _rewrite_zero_argument_calls("A-B", ["A", "B"]) == "A-B"


def test_zero_argument_rewrite_still_applies_to_whole_id_references():
    # A spaced difference is two whole ids, and a bare reference is one.
    assert _rewrite_zero_argument_calls("A - B", ["A", "B"]) == "A() - B()"
    assert _rewrite_zero_argument_calls("A-B + B", ["B"]) == "A-B + B()"
    assert _rewrite_zero_argument_calls("B(2)", ["B"]) == "B(2)"


def test_assignment_rule_body_keeps_a_raw_species_id_usable():
    from bionetgen.atomizer.modern import SBMLFunctionDefinition

    model = SBMLModel(
        id="zero-arg",
        compartments=_compartment(),
        species=OrderedDict([("A-B", _species("A-B"))]),
        parameters=OrderedDict(
            [
                ("k1", SBMLParameter(id="k1", value=0.5, constant=True)),
                ("Q", SBMLParameter(id="Q", value=0, constant=False)),
            ]
        ),
        function_definitions=OrderedDict(
            [("B", SBMLFunctionDefinition(id="B", math="1"))]
        ),
        rules=[SBMLRule(type="assignment", variable="Q", math="k1*(A-B)")],
    )

    functions = _block(model, "functions")
    assert "B() = 1" in functions
    # The species reference must not be rewritten into a call of the function
    # whose name is its own fragment.
    assert "A-(1)" not in functions
    assert "A-B()" not in functions


# --------------------------------------------------------------------------
# Assignment-rule references: the variables are raw rule variables.
# --------------------------------------------------------------------------


def _referencing_rule_model(reference: str) -> SBMLModel:
    return SBMLModel(
        id="rule-reference",
        compartments=_compartment(),
        species=OrderedDict([("S", _species("S"))]),
        parameters=OrderedDict(
            [("k1", SBMLParameter(id="k1", value=0.5, constant=True))]
            + [
                (variable, SBMLParameter(id=variable, value=0, constant=False))
                for variable in ("A-B", "C-D")
            ]
        ),
        rules=[
            SBMLRule(type="assignment", variable="A-B", math="1"),
            SBMLRule(type="assignment", variable="C-D", math=f"k1*({reference})"),
        ],
    )


def test_raw_rule_variable_reference_emits_the_same_body_as_its_standardized_form():
    raw = _block(_referencing_rule_model("A-B"), "functions")
    standardized = _block(_referencing_rule_model("A_B"), "functions")
    assert "A-B" not in raw.split("C_D() = ")[1]
    assert raw == standardized


# --------------------------------------------------------------------------
# Two rule targets that normalize to one BNGL function name.
# --------------------------------------------------------------------------


def _colliding_rule_model(species_ids) -> SBMLModel:
    return SBMLModel(
        id="rule-collision",
        compartments=_compartment(),
        species=OrderedDict((sid, _species(sid)) for sid in species_ids),
        parameters=OrderedDict(
            [("k1", SBMLParameter(id="k1", value=0.5, constant=True))]
            + [
                (variable, SBMLParameter(id=variable, value=0, constant=False))
                for variable in ("A-B", "A_B")
            ]
        ),
        rules=[
            SBMLRule(type="assignment", variable="A-B", math="1"),
            SBMLRule(type="assignment", variable="A_B", math="2"),
        ],
    )


def test_colliding_rule_targets_record_a_dropped_identifier_naming_both_ids():
    model = _colliding_rule_model(("S",))
    _emit(model)

    dropped = [
        dict(warning)
        for warning in model.import_warnings
        if warning.get("category") == "identifier"
        and warning.get("severity") == "dropped"
    ]
    assert len(dropped) == 1, [dict(w) for w in model.import_warnings]
    assert "'A-B'" in dropped[0]["message"]
    assert "'A_B'" in dropped[0]["message"]
    assert '"A_B"' in dropped[0]["message"]


def test_colliding_rule_targets_record_the_collision_when_a_species_shares_the_name():
    # The lowered species rule and the raw rule variable declare the same BNGL
    # function; the writer does not resolve that, so it has to say so.
    model = _colliding_rule_model(("A_B",))
    _block(model, "functions")

    assert any(
        warning.get("category") == "identifier"
        and "'A-B'" in warning.get("message", "")
        and "'A_B'" in warning.get("message", "")
        for warning in model.import_warnings
    ), [dict(w) for w in model.import_warnings]


def test_distinct_rule_targets_record_no_identifier_collision():
    model = SBMLModel(
        id="no-collision",
        compartments=_compartment(),
        species=OrderedDict([("S", _species("S"))]),
        parameters=OrderedDict(
            [("k1", SBMLParameter(id="k1", value=0.5, constant=True))]
            + [
                (variable, SBMLParameter(id=variable, value=0, constant=False))
                for variable in ("A-B", "C-D")
            ]
        ),
        rules=[
            SBMLRule(type="assignment", variable="A-B", math="1"),
            SBMLRule(type="assignment", variable="C-D", math="2"),
        ],
    )
    functions = _block(model, "functions")

    assert "A_B() = 1" in functions
    assert "C_D() = 2" in functions
    assert not [
        warning
        for warning in model.import_warnings
        if warning.get("category") == "identifier"
    ]


# --------------------------------------------------------------------------
# Bounded delay folding over a raw state id.
# --------------------------------------------------------------------------


def _delay_model(state_id: str, assigned_id: str) -> SBMLModel:
    return SBMLModel(
        id="delay",
        compartments=_compartment(),
        species=OrderedDict(
            [("A-B", _species("A-B", 5.0)), ("A_B", _species("A_B", 4.0))]
        ),
        rules=[
            SBMLRule(type="assignment", variable="Q", math=f"delay({state_id}, 10)")
        ],
        events=[
            SBMLEvent(
                id="E1",
                trigger="geq(time, 0)",
                trigger_initial_value=False,
                assignments=[SBMLEventAssignment(assigned_id, "7")],
            )
        ],
    )


def test_t0_event_assignment_keeps_a_delay_on_that_raw_state_intact():
    model = _delay_model("A-B", "A-B")
    assert _lower_bounded_event_state_delays(model, 10.0) == 0
    assert model.rules[0].math == "delay(A-B, 10)"


def test_t0_event_assignment_on_another_state_still_folds_the_delay():
    # The guard is about who writes the delayed state, not about the shape of
    # its id: a delay on ``A_B`` is unaffected by an event that writes ``A-B``.
    model = _delay_model("A_B", "A-B")
    assert _lower_bounded_event_state_delays(model, 10.0) == 1
    assert model.rules[0].math == "4.0"
