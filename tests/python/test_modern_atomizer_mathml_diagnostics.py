"""MathML operator lowering in the modern atomizer.

``_mathml_to_formula`` passes an unknown ``<apply>`` operator through as a
function call of the same name.  ``convert_math_expression`` then lowers the
names BNGL has no lexer token for onto one-expression equivalents, so an
``<arcsinh/>`` or a non-decimal ``<log/>`` reaches the C++ parser as executable
math rather than as a bare call that would be refused later as a missing
observable.
"""

from __future__ import annotations

from bionetgen.atomizer.modern import Atomizer, SBMLParser
from bionetgen.atomizer.modern.writer import convert_math_expression

MATHML_NS = "http://www.w3.org/1998/Math/MathML"


def _model_with_kinetic_math(math_body: str) -> str:
    return f"""<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="mathml_case">
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.5" constant="true"/>
      <parameter id="x" value="2" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="{MATHML_NS}">{math_body}</math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""


def _model_with_event_trigger(trigger_body: str) -> str:
    return f"""<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="event_case">
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfEvents>
      <event id="E1" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="true">
          <math xmlns="{MATHML_NS}">{trigger_body}</math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="A">
            <math xmlns="{MATHML_NS}"><cn>1</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""


def _mathml_warnings(math_body: str):
    return [
        record
        for record in SBMLParser()
        .parse(_model_with_kinetic_math(math_body))
        .import_warnings
        if record["category"] == "mathml"
    ]


def test_supported_operators_are_not_reported():
    body = (
        "<apply><times/><ci>k</ci>"
        "<apply><plus/>"
        "<apply><arctanh/><ci>x</ci></apply>"
        "<apply><log/><logbase><cn>10</cn></logbase><ci>x</ci></apply>"
        "</apply></apply>"
    )

    assert _mathml_warnings(body) == []
    model = SBMLParser().parse(_model_with_kinetic_math(body))
    assert model.reactions["R1"].kinetic_law.math == "k * (atanh(x) + log10(x))"


def test_mathml_hyperbolic_arc_names_map_onto_bngl_builtins():
    for mathml_name, bngl_name in (
        ("arcsinh", "asinh"),
        ("arccosh", "acosh"),
        ("arctanh", "atanh"),
    ):
        model = SBMLParser().parse(
            _model_with_kinetic_math(
                f"<apply><plus/><apply><{mathml_name}/><ci>x</ci></apply>"
                f"<ci>k</ci></apply>"
            )
        )

        assert model.reactions["R1"].kinetic_law.math == f"{bngl_name}(x) + k"
        assert not [
            record for record in model.import_warnings if record["category"] == "mathml"
        ]


def test_hyperbolic_reciprocals_lower_onto_sinh_and_cosh():
    """``sech``/``csch``/``coth`` must reach BNGL as one-expression rewrites.

    BNGL's lexer makes an unknown name a bare identifier, so a surviving
    ``sech(x)`` is read as an observable reference and refused by the C++
    parser.  Each rewrite below is exact, not an approximation.
    """

    for mathml_name, lowered in (
        ("sech", "(1/cosh(x))"),
        ("csch", "(1/sinh(x))"),
        ("coth", "(cosh(x)/sinh(x))"),
    ):
        assert convert_math_expression(f"k * {mathml_name}(x)") == f"k * {lowered}"


def test_hyperbolic_reciprocals_survive_the_rate_law_path():
    """The generated rate law must not name a function BNGL cannot evaluate."""

    for mathml_name, lowered in (
        ("sech", "(1/cosh(x))"),
        ("csch", "(1/sinh(x))"),
        ("coth", "(cosh(x)/sinh(x))"),
    ):
        result = Atomizer().atomize(
            _model_with_kinetic_math(
                f"<apply><times/><ci>k</ci><apply><{mathml_name}/><ci>x</ci></apply></apply>"
            )
        )

        assert result.success
        rate = next(
            line for line in result.bngl.splitlines() if line.strip().startswith("R1:")
        )
        assert f"k * {lowered}" in rate
        assert mathml_name not in rate


def test_coth_rewrite_does_not_bind_loosely_against_surrounding_operators():
    assert convert_math_expression("2*coth(x)/k") == "2*(cosh(x)/sinh(x))/k"
    assert convert_math_expression("k/(2*csch(x))") == "k/(2*(1/sinh(x)))"


def test_hyperbolic_reciprocals_fold_as_constants_in_event_triggers():
    """The event folder evaluates independently of ``convert_math_expression``.

    A constant trigger has to fold here for the event to lower to a scheduled
    action; an unrecognised function returns ``None`` and the event stays
    untranslated.
    """

    for mathml_name in ("sech", "csch", "coth"):
        result = Atomizer().atomize(
            _model_with_event_trigger(
                f"<apply><gt/><apply><{mathml_name}/><cn>0.3</cn></apply><cn>0.5</cn></apply>"
            )
        )

        assert result.success
        assert "state-dependent" not in result.bngl
