"""Regression tests for SBML elements whose MathML content is missing.

SBML Level 3 Version 2 Core made the ``math`` element optional on the
constructs that carry one, and gave each of them a defined meaning when the
element is absent:

* ``InitialAssignment`` (Sec. 4.8.3): "no assignments or other changes to the
  model are carried out when there is no math element.  This leaves the model
  unchanged".
* ``Rule`` (Sec. 4.9.1): the same no-op wording for assignment, rate and
  algebraic rules.
* ``FunctionDefinition`` (Sec. 4.3.2): the definition "has no mathematical
  meaning"; Sec. 4.3.4 adds that a call to such a function "is mathematically
  meaningless in a model".

The official SBML Test Suite encodes the same intent: cases ``semantic/01234``
through ``semantic/01244`` and ``semantic/01271`` state that an element
without a MathML child "is ignored", and their reference trajectories are the
unchanged values of the model's own definitions.

In SBML Level 2 and Level 3 Version 1 the ``math`` element is *required*, so a
document that omits it does not conform to the specification and must not be
reported as a supported model.

``Reaction`` is different (Sec. 4.11.1): a reaction without a kinetic law has
an undefined rate, and the specification states that a simulator's choice is
not standardized, so the model stays unsupported -- but the emitted reaction
must not invent a rate that the source never gave it.

Every regression here fails on the unfixed source.
"""

from __future__ import annotations

import math

import pytest

from bionetgen.atomizer.modern import Atomizer

SBML_NS = "http://www.w3.org/1998/Math/MathML"


def _atomize(sbml: str) -> tuple[Atomizer, object]:
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(sbml)
    assert result.success, result.error
    return atomizer, result


def _warnings(atomizer: Atomizer, category: str = "missingMath") -> list[dict]:
    return [
        warning
        for warning in atomizer.model.import_warnings
        if warning["category"] == category
    ]


def _limitations(atomizer: Atomizer) -> list[dict]:
    """Return the warnings that make a model unsupported for the harness."""

    return [
        warning
        for warning in atomizer.model.import_warnings
        if warning["severity"] in {"dropped", "approximated"}
        and warning["category"] != "units"
    ]


def _sbml(
    body: str, *, level: int = 3, version: int = 2, namespace: str | None = None
) -> str:
    if namespace is None:
        namespace = (
            f"http://www.sbml.org/sbml/level{level}/version{version}/core"
            if level == 3
            else f"http://www.sbml.org/sbml/level{level}/version{version}"
        )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<sbml xmlns="{namespace}" level="{level}" version="{version}">'
        f'<model id="m">{body}</model></sbml>'
    )


# ---------------------------------------------------------------------------
# SBML Level 3 Version 2 Core Sec. 4.8.3 -- initial assignment
# ---------------------------------------------------------------------------


def test_level3v2_initial_assignment_without_math_is_a_no_op():
    """SBML Level 3 Version 2 Core Sec. 4.8.3 (official case semantic/01234)."""

    sbml = _sbml("""
        <listOfParameters>
          <parameter id="p" value="3" constant="true"/>
        </listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="p"/>
        </listOfInitialAssignments>
        """)
    atomizer, result = _atomize(sbml)

    warnings = _warnings(atomizer)
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "info"
    assert "4.8.3" in warnings[0]["message"]
    assert not _limitations(atomizer), atomizer.model.import_warnings

    # The declared value survives: the assignment makes no change.
    assert "p 3" in result.bngl


# ---------------------------------------------------------------------------
# SBML Level 3 Version 2 Core Sec. 4.9.1 -- rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "kind"),
    [
        ('<assignmentRule variable="p"/>', "assignment"),
        ('<rateRule variable="p"/>', "rate"),
        ("<algebraicRule/>", "algebraic"),
    ],
)
def test_level3v2_rule_without_math_is_a_no_op(rule, kind):
    """SBML Level 3 Version 2 Core Sec. 4.9.1 (official cases 01235/01236/01244)."""

    sbml = _sbml(f"""
        <listOfParameters>
          <parameter id="p" value="3" constant="false"/>
        </listOfParameters>
        <listOfRules>
          {rule}
        </listOfRules>
        """)
    atomizer, result = _atomize(sbml)

    warnings = _warnings(atomizer)
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "info"
    assert "4.9.1" in warnings[0]["message"]
    assert not _limitations(atomizer), atomizer.model.import_warnings

    # No rule is emitted, so the parameter keeps its declared value.
    assert "p 3" in result.bngl
    assert "__assign_rule__" not in result.bngl


# ---------------------------------------------------------------------------
# SBML Level 3 Version 2 Core Sec. 4.3.2 / 4.3.4 -- function definitions
# ---------------------------------------------------------------------------


def test_level3v2_unused_function_definition_without_math_is_not_emitted():
    """SBML Level 3 Version 2 Core Sec. 4.3.2 (official case semantic/01271).

    The definition has no mathematical meaning, and the model never calls it,
    so the model is unchanged without it.  Emitting it as the constant zero
    function would invent a definition the source never made.
    """

    sbml = _sbml("""
        <listOfFunctionDefinitions>
          <functionDefinition id="foo"/>
        </listOfFunctionDefinitions>
        <listOfParameters>
          <parameter id="p1" value="2" constant="true"/>
        </listOfParameters>
        """)
    atomizer, result = _atomize(sbml)

    warnings = _warnings(atomizer)
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "info"
    assert "4.3.2" in warnings[0]["message"]
    assert not _limitations(atomizer), atomizer.model.import_warnings

    assert not [
        line for line in result.bngl.splitlines() if line.strip().startswith("foo")
    ], result.bngl


def test_level3v2_called_function_definition_without_math_stays_unsupported():
    """SBML Level 3 Version 2 Core Sec. 4.3.4.

    A call to a function that has no math content is mathematically
    meaningless, so the model is not claimed to be supported.
    """

    sbml = _sbml(f"""
        <listOfFunctionDefinitions>
          <functionDefinition id="foo"/>
        </listOfFunctionDefinitions>
        <listOfParameters>
          <parameter id="p1" value="2" constant="true"/>
        </listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="p2">
            <math xmlns="{SBML_NS}">
              <apply><ci>foo</ci><cn type="integer">1</cn></apply>
            </math>
          </initialAssignment>
        </listOfInitialAssignments>
        """)
    atomizer, _ = _atomize(sbml)

    warnings = _warnings(atomizer)
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "approximated"
    assert "4.3.4" in warnings[0]["message"]
    assert _limitations(atomizer)


# ---------------------------------------------------------------------------
# Level 2 / Level 3 Version 1 require the math element
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "version", "namespace"),
    [
        (2, 5, "http://www.sbml.org/sbml/level2/version5"),
        (3, 1, "http://www.sbml.org/sbml/level3/version1/core"),
    ],
)
def test_missing_math_in_older_levels_is_reported_as_an_invalid_document(
    level, version, namespace
):
    """The ``math`` element is required before SBML Level 3 Version 2."""

    sbml = _sbml(
        """
        <listOfParameters>
          <parameter id="p" value="3" constant="true"/>
        </listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="p"/>
        </listOfInitialAssignments>
        """,
        level=level,
        version=version,
        namespace=namespace,
    )
    atomizer, _ = _atomize(sbml)

    warnings = _warnings(atomizer, category="invalidSource")
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "dropped"
    assert "does not conform to the SBML" in warnings[0]["message"]
    assert _limitations(atomizer)


# ---------------------------------------------------------------------------
# SBML Level 3 Version 2 Core Sec. 4.11.1 -- reaction without a kinetic law
# ---------------------------------------------------------------------------


def test_reaction_without_kinetic_law_is_emitted_with_rate_zero():
    """SBML Level 3 Version 2 Core Sec. 4.11.1.

    The rate of a reaction with no kinetic law is undefined and the
    specification states that a simulator's choice is not standardized, so the
    model stays unsupported.  The emitted reaction must not carry an invented
    rate; zero is the reading the specification names that leaves the rest of
    the mathematical model intact.
    """

    sbml = _sbml("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1" constant="false"/>
          <species id="S2" compartment="C" initialAmount="0" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1"/>
            </listOfProducts>
          </reaction>
        </listOfReactions>
        """)
    atomizer, result = _atomize(sbml)

    warnings = _warnings(atomizer)
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "dropped"
    assert "4.11.1" in warnings[0]["message"]
    assert _limitations(atomizer)

    reaction_lines = [
        line.strip()
        for line in result.bngl.splitlines()
        if line.strip().startswith("J0:")
    ]
    assert reaction_lines, result.bngl
    assert reaction_lines[0].endswith(" 0"), reaction_lines[0]


# ---------------------------------------------------------------------------
# SBML Level 3 Version 2 Core validation rule 10207 -- <cn> content
# ---------------------------------------------------------------------------


def test_rational_cn_with_separator_is_lowered_exactly():
    """A rational ``cn`` is ``numerator<sep/>denominator`` in MathML 2.0."""

    sbml = _sbml(f"""
        <listOfParameters>
          <parameter id="p" value="0" constant="true"/>
        </listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="p">
            <math xmlns="{SBML_NS}">
              <cn type="rational">3<sep/>4</cn>
            </math>
          </initialAssignment>
        </listOfInitialAssignments>
        """)
    atomizer, result = _atomize(sbml)

    assert not [w for w in atomizer.model.import_warnings if w["category"] == "mathml"]
    assert "p 0.75" in result.bngl


def test_cn_with_separator_and_an_impermissible_type_is_reported_as_invalid():
    """SBML Level 3 Version 2 Core validation rule 10207.

    Only ``e-notation``, ``real``, ``integer`` and ``rational`` are permitted
    on a ``cn`` element, so any other type is a malformed source document
    rather than a construct BNG3 declines to support.
    """

    sbml = _sbml(f"""
        <listOfParameters>
          <parameter id="p" value="0" constant="true"/>
        </listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="p">
            <math xmlns="{SBML_NS}">
              <cn type="fraction">3<sep/>4</cn>
            </math>
          </initialAssignment>
        </listOfInitialAssignments>
        """)
    atomizer, _ = _atomize(sbml)

    warnings = _warnings(atomizer, category="invalidSource")
    assert len(warnings) == 1
    assert "not valid SBML" in warnings[0]["message"]
    assert _limitations(atomizer)


# ---------------------------------------------------------------------------
# SBML Level 3 Version 2 Core validation rule 10202 -- MathML constants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("constant", "expression"),
    [("infinity", "exp(1000)"), ("notanumber", "sqrt(-1)")],
)
def test_mathml_constants_preserve_nonfinite_values(constant, expression):
    """Valid MathML non-finite constants survive initial-assignment lowering."""
    sbml = _sbml(f"""
        <listOfParameters>
          <parameter id="p" value="0" constant="true"/>
        </listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="p">
            <math xmlns="{SBML_NS}"><{constant}/></math>
          </initialAssignment>
        </listOfInitialAssignments>
        """)
    atomizer, result = _atomize(sbml)

    assert atomizer.model.initial_assignments[0].symbol == "p"
    assert atomizer.model.initial_assignments[0].math == expression
    assert not _warnings(atomizer, category="mathml")
    assert not _warnings(atomizer, category="invalidSource")
    assert not _limitations(atomizer)

    from bionetgen import _bionetgen_cpp as cpp

    model = cpp.parse_string(result.bngl)
    emitted = next(
        function.expression for function in model.functions if function.name == "p"
    )
    # Evaluate the emitted constant expression through the native parameter evaluator.
    probe = cpp.parse_string(
        f"begin model\nbegin parameters\nprobe {emitted}\nend parameters\nend model"
    )
    value = probe.parameters[0].value
    if constant == "infinity":
        assert math.isinf(value) and value > 0
    else:
        assert math.isnan(value)


# ---------------------------------------------------------------------------
# The reason text has to keep the two sides of the boundary apart
# ---------------------------------------------------------------------------


def test_valid_source_limitation_says_so_for_a_rate_less_reaction():
    """The same distinction for a reaction whose rate the source never gives."""

    sbml = _sbml("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1" constant="false"/>
          <species id="S2" compartment="C" initialAmount="0" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1"/>
            </listOfProducts>
          </reaction>
        </listOfReactions>
        """)
    atomizer, _ = _atomize(sbml)

    message = next(
        warning["message"]
        for warning in atomizer.model.import_warnings
        if warning["category"] == "missingMath"
    )
    assert "the source document is valid SBML" in message, message
    assert "does not conform" not in message, message
    assert "not valid SBML" not in message, message


# ---------------------------------------------------------------------------
# The campaign's coverage inventory classifies a gap by matching its reason
# text against these needles.  A reworded diagnostic that stops matching would
# silently change the campaign's construct taxonomy.
# ---------------------------------------------------------------------------


def _reason_for_needle(needle: str) -> str:
    if needle == "no mathml expression":
        sbml = _sbml("""
            <listOfParameters>
              <parameter id="p" value="3" constant="true"/>
            </listOfParameters>
            <listOfInitialAssignments>
              <initialAssignment symbol="p"/>
            </listOfInitialAssignments>
            """)
        category = "missingMath"
    elif needle == "have no mathml kinetic law":
        sbml = _sbml("""
            <listOfCompartments>
              <compartment id="C" size="1" constant="true"/>
            </listOfCompartments>
            <listOfSpecies>
              <species id="S1" compartment="C" initialAmount="1" constant="false"/>
              <species id="S2" compartment="C" initialAmount="0" constant="false"/>
            </listOfSpecies>
            <listOfReactions>
              <reaction id="J0" reversible="false">
                <listOfReactants>
                  <speciesReference species="S1" stoichiometry="1"/>
                </listOfReactants>
                <listOfProducts>
                  <speciesReference species="S2" stoichiometry="1"/>
                </listOfProducts>
              </reaction>
            </listOfReactions>
            """)
        category = "missingMath"

    atomizer, _ = _atomize(sbml)
    return next(
        warning["message"]
        for warning in atomizer.model.import_warnings
        if warning["category"] == category
    )


@pytest.mark.parametrize(
    "needle",
    [
        "no mathml expression",
        "have no mathml kinetic law",
    ],
)
def test_reason_text_keeps_the_inventory_needles(needle):
    """``scripts/ci/sbml_campaign_inventory.py`` maps a reason to a construct
    by matching these needles, so a reworded diagnostic must keep them."""

    message = _reason_for_needle(needle)
    assert needle in message.lower(), message
