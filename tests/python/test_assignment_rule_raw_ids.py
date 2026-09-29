"""Raw species ids in assignment-rule and function-definition bodies.

``standardize_name`` runs on a species id only at emission, so a species spelled
``A-B`` reaches ``write_functions`` in its source spelling.  A
``[A-Za-z_][A-Za-z0-9_]*`` token cannot spell that id, and neither can the
whole-id run it does produce be mistaken for an operator.

``bngl_function`` owns the pre-pass that standardizes declared id runs before
its tokenizer sees them.  The assignment-rule loop in ``write_functions`` does
not call ``bngl_function`` -- it emits the bare species observable -- so the same
pre-pass has to reach it, or the raw id lands in the functions block where no
such symbol is declared.
"""

from __future__ import annotations

from collections import OrderedDict

from bionetgen.atomizer.modern import (
    SBMLCompartment,
    SBMLFunctionDefinition,
    SBMLInitialAssignment,
    SBMLModel,
    SBMLParameter,
    SBMLRule,
    SBMLSpecies,
    build_species_composition_table,
    generate_bngl,
    get_molecule_types,
    get_seed_species,
)

from bionetgen.atomizer.modern.writer import write_functions


def _species(species_id: str, amount: float = 1.0) -> SBMLSpecies:
    return SBMLSpecies(
        id=species_id,
        compartment="cell",
        initial_amount=amount,
        initial_amount_set=True,
        has_only_substance_units=True,
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


def _model(
    species_ids,
    rules=(),
    *,
    parameters=(),
    functions=OrderedDict(),
    initial_assignments=(),
) -> SBMLModel:
    return SBMLModel(
        id="raw-assignment",
        compartments=OrderedDict([("cell", SBMLCompartment(id="cell", size=1.0))]),
        species=OrderedDict([(s, _species(s)) for s in species_ids]),
        parameters=OrderedDict(
            [
                ("k1", SBMLParameter(id="k1", value=0.5, constant=True)),
                *parameters,
            ]
        ),
        function_definitions=functions,
        rules=list(rules),
        initial_assignments=list(initial_assignments),
    )


def _target_parameter() -> SBMLParameter:
    return SBMLParameter(id="Q", value=0, constant=False)


# --------------------------------------------------------------------------
# The assignment-rule body: the rate-law path standardizes, this one did not.
# --------------------------------------------------------------------------


def test_assignment_rule_body_does_not_emit_a_raw_species_id():
    model = _model(
        ["A-B", "P"],
        [SBMLRule(type="assignment", variable="Q", math="k1*(A-B)")],
        parameters=[("Q", _target_parameter())],
    )

    functions = _block(model, "functions")
    # ``M_A_B`` is the declared molecule type; ``A_B`` the declared species
    # observable.  ``A-B`` is neither, so it must not reach the block.
    assert "A-B" not in functions, functions
    assert "Q() = 0.5*(A_B)" in functions, functions


def test_assignment_rule_body_matches_the_body_of_its_standardized_spelling():
    # The source spelling of an id must not change what the model means.  These
    # two models differ only in whether the species id needed standardizing.
    raw = _block(
        _model(
            ["A-B", "P"],
            [SBMLRule(type="assignment", variable="Q", math="k1*(A-B)")],
            parameters=[("Q", _target_parameter())],
        ),
        "functions",
    )
    standardized = _block(
        _model(
            ["A_B", "P"],
            [SBMLRule(type="assignment", variable="Q", math="k1*(A_B)")],
            parameters=[("Q", _target_parameter())],
        ),
        "functions",
    )

    assert raw == standardized


# --------------------------------------------------------------------------
# A real operator next to a raw id is not part of the id.
# --------------------------------------------------------------------------


def test_spaced_difference_around_a_raw_species_id_is_not_mangled():
    # ``A - A-B`` is species A minus species ``A-B``.  The pre-pass must consume
    # the trailing run only; consuming the leading ``A`` as part of a longer id
    # would delete an operator the source model actually declares.
    model = _model(
        ["A", "A-B", "P"],
        [SBMLRule(type="assignment", variable="Q", math="k1*(A - A-B)")],
        parameters=[("Q", _target_parameter())],
    )

    functions = _block(model, "functions")
    assert "A-B" not in functions, functions
    assert "Q() = 0.5*(A - A_B)" in functions, functions


def test_undeclared_subtraction_is_not_read_as_a_declared_hyphenated_id():
    # Neither ``A-B`` nor a species standardizing to it is declared here, so the
    # two runs are a difference of two declared species and must stay one.
    model = _model(
        ["A", "B", "P"],
        [SBMLRule(type="assignment", variable="Q", math="k1*(A-B)")],
        parameters=[("Q", _target_parameter())],
    )

    functions = _block(model, "functions")
    assert "Q() = 0.5*(A-B)" in functions, functions


# --------------------------------------------------------------------------
# Neighbouring bodies that share the defect.
# --------------------------------------------------------------------------


def test_initial_assignment_body_does_not_emit_a_raw_species_id():
    model = _model(
        ["A-B", "P"],
        parameters=[("Q", _target_parameter())],
        initial_assignments=[SBMLInitialAssignment(symbol="Q", math="k1*(A-B)")],
    )

    functions = _block(model, "functions")
    assert "A-B" not in functions, functions
    assert "Q() = 0.5*(A_B)" in functions, functions


def test_zero_argument_function_definition_body_does_not_emit_a_raw_species_id():
    model = _model(
        ["A-B", "P"],
        functions=OrderedDict(
            [("g", SBMLFunctionDefinition(id="g", math="k1*(A-B)", arguments=[]))]
        ),
    )

    functions = _block(model, "functions")
    assert "g() = k1*(A_B)" in functions, functions


def test_parameterized_definition_keeps_a_formal_argument_named_like_a_species():
    # Formal arguments are renamed to ``_fargN_*`` before the pre-pass runs, so
    # an argument that shares a species id must stay a bound argument and not be
    # rewritten as a reference to that species.
    model = _model(
        ["A-B", "P"],
        functions=OrderedDict(
            [
                (
                    "h",
                    SBMLFunctionDefinition(
                        id="h", math="(A-B)*(A-B)", arguments=["A-B"]
                    ),
                )
            ]
        ),
    )

    functions = "\n".join(write_functions(model, keep_parameterized=True))
    assert "A-B" not in functions, functions
    assert "h(_farg0_A_B) = (_farg0_A_B)*(_farg0_A_B)" in functions, functions


def test_species_targeted_assignment_rule_body_does_not_emit_a_raw_species_id():
    model = _model(
        ["A-B", "P"],
        [SBMLRule(type="assignment", variable="A-B", math="k1*(A-B)/2")],
    )

    functions = _block(model, "functions")
    assert "A-B" not in functions, functions
