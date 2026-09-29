"""Scope of the generated-identifier collision diagnostic.

``standardize_name`` maps every non-alphanumeric character to ``_``, so distinct
SBML SIds such as ``A-B`` and ``A_B`` generate the same BNGL spelling.  Whether
that is a real defect depends on the namespace: a namespace whose generated
spelling becomes a *declaration* collides with itself, while a namespace whose
spelling is disambiguated at emission time does not.

These tests pin both directions: every namespace that really corrupts must still
report, and every namespace that survives must stay silent so a correct model
keeps its numerical claim.
"""

from collections import OrderedDict

from bionetgen.atomizer.modern import (
    SBMLCompartment,
    SBMLFunctionDefinition,
    SBMLKineticLaw,
    SBMLModel,
    SBMLParameter,
    SBMLReaction,
    SBMLSpecies,
    SBMLSpeciesReference,
    build_species_composition_table,
    generate_bngl,
    get_molecule_types,
    get_seed_species,
)

from bionetgen.atomizer.modern import writer as writer_module


def _species(identifier, amount, compartment="c"):
    return SBMLSpecies(
        id=identifier,
        compartment=compartment,
        initial_amount=amount,
        initial_amount_set=True,
    )


def _reaction(identifier, reactants, products, math):
    return SBMLReaction(
        id=identifier,
        reversible=False,
        reactants=[SBMLSpeciesReference(species=s) for s in reactants],
        products=[SBMLSpeciesReference(species=s) for s in products],
        kinetic_law=SBMLKineticLaw(math=math),
    )


def _render(model):
    sct = build_species_composition_table(model)
    result = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    return result.bngl


def _identifier_warnings(model):
    return [
        warning
        for warning in getattr(model, "import_warnings", None) or []
        if warning.get("category") == "identifier"
    ]


def _section(bngl, name):
    return bngl.split(f"begin {name}", 1)[1].split(f"end {name}", 1)[0]


def _entries(bngl, section):
    return [
        line.strip() for line in _section(bngl, section).splitlines() if line.strip()
    ]


def _simple_model(**overrides):
    model = SBMLModel(
        id="collision_scope",
        compartments=OrderedDict([("c", SBMLCompartment(id="c", size=1))]),
        species=OrderedDict(
            [
                ("A", _species("A", 10)),
                ("B", _species("B", 4)),
                ("P", _species("P", 0)),
                ("Q", _species("Q", 0)),
            ]
        ),
        parameters=OrderedDict([("kf", SBMLParameter(id="kf", value=0.5))]),
        reactions=OrderedDict(
            [
                ("R1", _reaction("R1", ["A"], ["P"], "kf*A")),
                ("R2", _reaction("R2", ["B"], ["Q"], "kf*B")),
            ]
        ),
    )
    for attribute, value in overrides.items():
        setattr(model, attribute, value)
    return model


# --------------------------------------------------------------------- species
def test_colliding_species_report_the_lost_seed_amount():
    model = _simple_model(
        species=OrderedDict(
            [
                ("A-B", _species("A-B", 10)),
                ("A_B", _species("A_B", 3)),
                ("P", _species("P", 0)),
                ("Q", _species("Q", 0)),
            ]
        ),
        reactions=OrderedDict(
            [
                ("R1", _reaction("R1", ["A-B"], ["P"], "kf*A-B")),
                ("R2", _reaction("R2", ["A_B"], ["Q"], "kf*A_B")),
            ]
        ),
    )

    bngl = _render(model)

    # The two SBML species really do collapse: one seed amount survives, and
    # both reaction patterns name the same molecule type.
    seeds = _entries(bngl, "seed species")
    assert seeds == ["@c:M_A_B() 10", "@c:M_P() 0", "@c:M_Q() 0"]
    rules = _entries(bngl, "reaction rules")
    assert sum("M_A_B()" in rule for rule in rules) == 2

    warnings = _identifier_warnings(model)
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["severity"] == "dropped"
    assert "SBML species ids 'A-B', 'A_B'" in warning["message"]
    assert 'normalize to the single BNGL identifier "A_B"' in warning["message"]
    # The message must name what is actually lost rather than assert a merge
    # of two definitions.
    assert "seed" in warning["message"]


# ----------------------------------------------------------------- compartment
def test_colliding_compartments_report_the_duplicate_declaration():
    model = _simple_model(
        compartments=OrderedDict(
            [
                ("C-1", SBMLCompartment(id="C-1", size=2)),
                ("C_1", SBMLCompartment(id="C_1", size=5)),
            ]
        ),
        species=OrderedDict(
            [
                ("A", _species("A", 10, compartment="C-1")),
                ("B", _species("B", 4, compartment="C_1")),
                ("P", _species("P", 0, compartment="C-1")),
            ]
        ),
    )

    bngl = _render(model)

    # The BNGL compartment block really does declare one compartment twice
    # with two different sizes.
    assert _entries(bngl, "compartments") == ["C_1 3 2", "C_1 3 5"]

    warnings = _identifier_warnings(model)
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["severity"] == "dropped"
    assert "SBML compartment ids 'C-1', 'C_1'" in warning["message"]
    assert "twice" in warning["message"]


# ------------------------------------------------------------------ parameter
_PARAMETER_COLLISION_XML = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core">
  <model id="parameter_collision">
    <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="10"/>
      <species id="B" compartment="C" initialAmount="4"/>
      <species id="P" compartment="C" initialAmount="0"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k-1" value="1.0" constant="true"/>
      <parameter id="k_1" value="7.0" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="R0" reversible="false">
        <listOfReactants><speciesReference species="A"/></listOfReactants>
        <listOfProducts><speciesReference species="P"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k-1</ci></apply></math></kineticLaw>
      </reaction>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="B"/></listOfReactants>
        <listOfProducts><speciesReference species="P"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_1</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""


def test_colliding_parameter_ids_do_not_report_because_the_parser_uniquifies(
    monkeypatch,
):
    """Parameter SIds are made unique before the writer ever sees them.

    The SBML parser renames ``k-1`` and ``k_1`` to ``k_1`` and ``k_1_2``, so the
    parameter block declares two distinct names and the model is correct.  A
    ``dropped`` record here would cost a correct model its numerical claim, so
    this pins the exclusion against re-opening it.
    """
    from bionetgen.atomizer import modern as modern_package
    from bionetgen.atomizer.modern import Atomizer

    captured = {}
    original = writer_module.generate_bngl

    def capture(model, sct, *args, **kwargs):
        captured["parameters"] = list(model.parameters)
        return original(model, sct, *args, **kwargs)

    monkeypatch.setattr(modern_package, "generate_bngl", capture)

    result = Atomizer(quiet_mode=True, t_end=1, n_steps=10).atomize(
        _PARAMETER_COLLISION_XML
    )

    assert result.success, result.error
    assert captured["parameters"] == ["k_1", "k_1_2"]

    parameters = _entries(result.bngl, "parameters")
    assert "k_1 1" in parameters
    assert "k_1_2 7" in parameters
    declared = [line.split()[0] for line in parameters]
    assert len(set(declared)) == len(declared)
    assert "identifier:" not in result.bngl


def test_hand_built_colliding_parameters_are_out_of_scope():
    """Pin the exclusion itself, not just the observable import behavior.

    The parser uniquifies parameter SIds, so the import path can never deliver
    colliding parameters to the writer.  A diagnostic aimed at a model the
    writer is never handed would be a fail-closed rule with no reachable
    defect behind it, so the scope stops at the namespaces that reach the
    writer colliding.
    """
    model = _simple_model(
        parameters=OrderedDict(
            [
                ("kf", SBMLParameter(id="kf", value=0.5)),
                ("k-1", SBMLParameter(id="k-1", value=1.0)),
                ("k_1", SBMLParameter(id="k_1", value=7.0)),
            ]
        ),
        reactions=OrderedDict(
            [
                ("R1", _reaction("R1", ["A"], ["P"], "k-1*A")),
                ("R2", _reaction("R2", ["B"], ["Q"], "k_1*B")),
            ]
        ),
    )

    _render(model)

    assert _identifier_warnings(model) == []


# ------------------------------------------------------------------- function
def test_colliding_zero_argument_functions_report_the_duplicate_declaration():
    model = _simple_model(
        function_definitions=OrderedDict(
            [
                ("f-1", SBMLFunctionDefinition(id="f-1", math="_c_A()", arguments=[])),
                ("f_1", SBMLFunctionDefinition(id="f_1", math="_c_B()", arguments=[])),
            ]
        ),
        reactions=OrderedDict(
            [
                ("R1", _reaction("R1", ["A"], ["P"], "kf*f-1()")),
                ("R2", _reaction("R2", ["B"], ["Q"], "kf*f_1()")),
            ]
        ),
    )

    bngl = _render(model)

    # Zero-argument definitions are declared, and the two SBML ids land on one
    # BNGL name with two different bodies.
    declared = [line for line in _entries(bngl, "functions") if line.startswith("f_")]
    assert declared == ["f_1() = _c_A()", "f_1() = _c_B()"]


def _argument_function_model(second_id):
    return _simple_model(
        function_definitions=OrderedDict(
            [
                ("f-1", SBMLFunctionDefinition(id="f-1", math="2*x", arguments=["x"])),
                (
                    second_id,
                    SBMLFunctionDefinition(id=second_id, math="7*x", arguments=["x"]),
                ),
            ]
        ),
        reactions=OrderedDict(
            [
                ("R1", _reaction("R1", ["A"], ["P"], "kf*f-1(A)")),
                ("R2", _reaction("R2", ["B"], ["Q"], f"kf*{second_id}(B)")),
            ]
        ),
    )


def test_colliding_argument_taking_functions_do_not_report():
    """Argument-taking definitions are inlined at their call sites.

    ``write_functions`` skips them, so nothing is declared.  The two rates show
    each call site kept its own definition's body: with a colliding partner the
    second rule still evaluates ``7*x`` while the control with a distinct id
    gives the identical result.
    """

    colliding = _render(_argument_function_model("f_1"))
    control = _render(_argument_function_model("f2"))

    assert _entries(colliding, "reaction rules") == _entries(control, "reaction rules")
    assert _entries(colliding, "reaction rules") == [
        "R1: @c:M_A() -> @c:M_P() 1",
        "R2: @c:M_B() -> @c:M_Q() 3.5",
    ]
    assert not [
        line for line in _entries(colliding, "functions") if line.startswith("f")
    ]

    assert _identifier_warnings(_argument_function_model("f_1")) == []


def test_mixed_argument_and_zero_argument_collision_does_not_report():
    """Only the declared side of the collision reaches the functions block."""

    model = _simple_model(
        function_definitions=OrderedDict(
            [
                ("f-1", SBMLFunctionDefinition(id="f-1", math="2*x", arguments=["x"])),
                ("f_1", SBMLFunctionDefinition(id="f_1", math="7", arguments=[])),
            ]
        ),
        reactions=OrderedDict(
            [
                ("R1", _reaction("R1", ["A"], ["P"], "kf*f-1(A)")),
                ("R2", _reaction("R2", ["B"], ["Q"], "kf*f_1()")),
            ]
        ),
    )

    bngl = _render(model)

    assert [line for line in _entries(bngl, "functions") if line.startswith("f_")] == [
        "f_1() = 7"
    ]
    assert _identifier_warnings(model) == []


# ------------------------------------------------------------------- reaction
def test_colliding_reaction_ids_do_not_report_because_rules_stay_distinct():
    """Reaction labels are disambiguated at emission time.

    The two colliding ids produce two correct, distinct rules whose rates match
    the non-colliding control, so a ``dropped`` record would cost a correct
    model its numerical claim for nothing.
    """

    control = _simple_model(
        reactions=OrderedDict(
            [
                ("R-1", _reaction("R-1", ["A"], ["P"], "kf*A")),
                ("R2", _reaction("R2", ["B"], ["Q"], "3*kf*B")),
            ]
        )
    )
    colliding = _simple_model(
        reactions=OrderedDict(
            [
                ("R-1", _reaction("R-1", ["A"], ["P"], "kf*A")),
                ("R_1", _reaction("R_1", ["B"], ["Q"], "3*kf*B")),
            ]
        )
    )

    control_rules = _entries(_render(control), "reaction rules")
    colliding_rules = _entries(_render(colliding), "reaction rules")

    assert control_rules == [
        "R_1: @c:M_A() -> @c:M_P() 0.5",
        "R2: @c:M_B() -> @c:M_Q() 1.5",
    ]
    assert len(colliding_rules) == 2
    assert colliding_rules[0] == control_rules[0]
    # Only the label is suffixed; the rule body and its rate are unchanged.
    assert colliding_rules[1].split(":", 1)[1] == control_rules[1].split(":", 1)[1]
    assert colliding_rules[1] == "R_1_2: @c:M_B() -> @c:M_Q() 1.5"

    assert _identifier_warnings(colliding) == []


def test_only_the_colliding_namespace_is_reported():
    """A reaction collision alongside a species collision reports one record."""

    model = _simple_model(
        species=OrderedDict(
            [
                ("A-B", _species("A-B", 10)),
                ("A_B", _species("A_B", 3)),
                ("P", _species("P", 0)),
                ("Q", _species("Q", 0)),
            ]
        ),
        reactions=OrderedDict(
            [
                ("R-1", _reaction("R-1", ["A-B"], ["P"], "kf*A-B")),
                ("R_1", _reaction("R_1", ["A_B"], ["Q"], "3*kf*A_B")),
            ]
        ),
    )

    _render(model)

    warnings = _identifier_warnings(model)
    assert len(warnings) == 1
    assert "SBML species ids 'A-B', 'A_B'" in warnings[0]["message"]
    assert "reaction ids" not in warnings[0]["message"]


def test_clean_model_reports_nothing():
    model = _simple_model()

    _render(model)

    assert _identifier_warnings(model) == []


def test_all_five_namespaces_agree_with_the_diagnostic():
    """One sweep over all five namespaces, checked against real output.

    ``parameters``, ``reactions`` and argument-taking ``function_definitions``
    survive a collision and must stay silent; ``compartments`` and ``species``
    corrupt and must report.  ``parameters`` is excluded because the parser
    uniquifies them first, which its own test covers end to end.
    """

    collisions = _simple_model(
        compartments=OrderedDict(
            [
                ("C-1", SBMLCompartment(id="C-1", size=1)),
                ("C_1", SBMLCompartment(id="C_1", size=2)),
            ]
        ),
        species=OrderedDict(
            [
                ("A-B", _species("A-B", 10, compartment="C-1")),
                ("A_B", _species("A_B", 3, compartment="C_1")),
                ("P", _species("P", 0, compartment="C-1")),
                ("Q", _species("Q", 0, compartment="C_1")),
            ]
        ),
        parameters=OrderedDict(
            [
                ("kf", SBMLParameter(id="kf", value=0.5)),
                ("k-1", SBMLParameter(id="k-1", value=1.0)),
                ("k_1", SBMLParameter(id="k_1", value=7.0)),
            ]
        ),
        function_definitions=OrderedDict(
            [
                ("f-1", SBMLFunctionDefinition(id="f-1", math="2*x", arguments=["x"])),
                ("f_1", SBMLFunctionDefinition(id="f_1", math="7*x", arguments=["x"])),
            ]
        ),
        reactions=OrderedDict(
            [
                ("R-1", _reaction("R-1", ["A-B"], ["P"], "k-1*f-1(A-B)")),
                ("R_1", _reaction("R_1", ["A_B"], ["Q"], "k_1*f_1(A_B)")),
            ]
        ),
    )

    _render(collisions)

    reported = " ".join(
        warning["message"] for warning in _identifier_warnings(collisions)
    )
    for namespace in ("compartment", "species"):
        assert f"SBML {namespace} ids" in reported
    for namespace in ("parameter", "reaction", "function"):
        assert f"SBML {namespace} ids" not in reported
