"""Regression tests for the Atomizer's static MathML expression evaluator.

SBML Level 3 Version 2 Core (Sec. 4.11.3) lets a species reference name a
model-level symbol that holds its stoichiometry, and Sec. 4.8 lets an initial
assignment set a symbol's value once, at the start of the simulation.  The
values those constructs carry are MathML expressions, and the official SBML
Test Suite exercises them with the MathML built-ins: ``semantic/01516`` and
``semantic/01517`` assign ``abs(-1)``, ``arccos(-1)``, ``root(2, 4)`` and
friends to thirty-eight species references.

Three properties have to hold together:

* the evaluator has to know the MathML built-ins, otherwise a resolvable
  stoichiometry is reported as unresolvable;
* the value it folds has to be the value of the expression the writer
  emits, down to the last bit, or the folded constant and the emitted model
  describe different systems; and
* a stoichiometry that a BNGL reaction pattern cannot spell -- a negative or
  a fractional one -- has to be carried by the deterministic flux lowering
  instead of being dropped.
"""

from __future__ import annotations

import ast
import math
import re

import pytest

from bionetgen.atomizer.modern import Atomizer, SBMLParser
from bionetgen.atomizer.modern.math_builtins import (
    TRUNCATED_E,
    TRUNCATED_LN10,
    evaluate_math_builtin,
)
from bionetgen.atomizer.modern.parser import _evaluate_static_arithmetic
from bionetgen.atomizer.modern.writer import convert_math_expression

# The BNGL built-ins a lowered MathML expression can name, with the Python
# function that computes the same value.
_BNGL_FUNCTIONS = {
    "ln": math.log,
    "log10": math.log10,
    "abs": abs,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "asinh": math.asinh,
    "acosh": math.acosh,
    "atanh": math.atanh,
    "floor": math.floor,
    "ceil": math.ceil,
    "factorial": lambda value: math.factorial(int(value)),
}


def _numeric_expression_value(text: str) -> float:
    """Evaluate a purely numeric BNGL expression without using ``eval``."""

    # BNGL's conditional is a call, not Python's conditional expression.
    tree = ast.parse(re.sub(r"\bif\(", "_if(", text.replace("^", "**")), mode="eval")

    def value(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return value(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = value(node.operand)
            return operand if isinstance(node.op, ast.UAdd) else -operand
        if isinstance(node, ast.BinOp):
            left = value(node.left)
            right = value(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            return left**right
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left = value(node.left)
            right = value(node.comparators[0])
            operator = node.ops[0]
            if isinstance(operator, ast.Gt):
                return float(left > right)
            if isinstance(operator, ast.GtE):
                return float(left >= right)
            if isinstance(operator, ast.Lt):
                return float(left < right)
            if isinstance(operator, ast.LtE):
                return float(left <= right)
            if isinstance(operator, ast.Eq):
                return float(left == right)
            if isinstance(operator, ast.NotEq):
                return float(left != right)
            raise AssertionError(f"unsupported comparison: {ast.dump(node)}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            arguments = [value(argument) for argument in node.args]
            if name == "_if" and len(arguments) == 3:
                return arguments[1] if arguments[0] else arguments[2]
            function = _BNGL_FUNCTIONS.get(name)
            assert function is not None, f"unsupported call: {name}"
            return float(function(*arguments))
        raise AssertionError(f"unsupported expression node: {ast.dump(node)}")

    return value(tree)


def _model_with_stoichiometry_math(math_body: str) -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="builtin_stoichiometry">
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="C" initialAmount="0" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants/>
            <listOfProducts>
              <speciesReference species="A" constant="true">
                <stoichiometryMath>
                  <math xmlns="http://www.w3.org/1998/Math/MathML">{math_body}</math>
                </stoichiometryMath>
              </speciesReference>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""


def _model_with_parameter_initial_assignment(math_body: str) -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="builtin_initial_assignment">
        <listOfParameters>
          <parameter id="k" constant="true"/>
        </listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="k">
            <math xmlns="http://www.w3.org/1998/Math/MathML">{math_body}</math>
          </initialAssignment>
        </listOfInitialAssignments>
      </model>
    </sbml>"""


@pytest.mark.parametrize(
    ("math_body", "expected"),
    [
        ("<apply><abs/><cn>-1</cn></apply>", 1.0),
        ("<apply><arccos/><cn>-1</cn></apply>", math.pi),
        ("<apply><arccos/><cn>0.5</cn></apply>", math.acos(0.5)),
        ("<apply><arcsin/><cn>-0.5</cn></apply>", -math.pi / 6),
        ("<apply><arctan/><cn>2.8</cn></apply>", math.atan(2.8)),
        ("<apply><ceiling/><cn>3.55</cn></apply>", 4.0),
        ("<apply><ceiling/><cn>-4.6</cn></apply>", -4.0),
        ("<apply><floor/><cn>-4.6</cn></apply>", -5.0),
        ("<apply><factorial/><cn>4</cn></apply>", 24.0),
        ("<apply><exp/><cn>1</cn></apply>", TRUNCATED_E),
        ("<apply><ln/><cn>0.2</cn></apply>", math.log(0.2)),
        (
            "<apply><root/><degree><cn>2</cn></degree><cn>4</cn></apply>",
            2.0,
        ),
        (
            "<apply><root/><degree><cn>2</cn></degree><cn>7.4</cn></apply>",
            7.4**0.5,
        ),
        ("<apply><sin/><cn>2.1</cn></apply>", math.sin(2.1)),
        ("<apply><tan/><cn>-6</cn></apply>", math.tan(-6)),
        ("<apply><tanh/><cn>-6</cn></apply>", math.tanh(-6)),
        (
            "<apply><power/><cn>1.4</cn><cn>5.1</cn></apply>",
            1.4**5.1,
        ),
    ],
)
def test_mathml_builtin_stoichiometry_folds_to_its_value(math_body, expected):
    """A stoichiometry the MathML built-ins determine is a constant."""

    model = SBMLParser().parse(_model_with_stoichiometry_math(math_body))
    reference = model.reactions["J0"].products[0]

    assert reference.variable_stoichiometry is False
    assert reference.stoichiometry == pytest.approx(expected, rel=1e-12, abs=0.0)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("exp(2)", TRUNCATED_E**2),
        ("log10(100)", math.log(100.0) / TRUNCATED_LN10),
        ("sqrt(2)", 2.0**0.5),
        ("sqr(1.5)", 1.5**2),
        ("abs(-2.5)", 2.5),
        ("root(2, 4)", 4.0 ** (1.0 / 2.0)),
        ("power(1.4, 5.1)", 1.4**5.1),
        ("sec(0.5)", 1.0 / math.cos(0.5)),
        ("csc(0.5)", 1.0 / math.sin(0.5)),
        ("cot(0.5)", math.cos(0.5) / math.sin(0.5)),
        ("arcsec(2)", math.acos(1.0 / 2.0)),
        ("arccsc(2)", math.asin(1.0 / 2.0)),
        ("arccot(2)", math.atan(1.0 / 2.0)),
        ("arcsech(0.5)", math.acosh(1.0 / 0.5)),
        ("arccsch(0.5)", math.asinh(1.0 / 0.5)),
        ("sech(0.5)", 1.0 / math.cosh(0.5)),
        ("csch(0.5)", 1.0 / math.sinh(0.5)),
        ("coth(0.5)", math.cosh(0.5) / math.sinh(0.5)),
        ("factorial(5)", 120.0),
    ],
)
def test_the_evaluator_computes_the_value_of_the_emitted_lowering(expression, expected):
    """The folded value is the value of the expression the writer emits."""

    folded = _evaluate_static_arithmetic(expression, {})
    emitted = convert_math_expression(expression)

    assert folded == expected
    assert _numeric_expression_value(emitted) == expected


def test_the_folded_value_uses_the_writers_truncated_constants():
    """``exp`` and ``log10`` fold to what the emitted model computes.

    The writer lowers ``exp`` onto a power of a truncated constant and
    ``log10`` onto a quotient by a truncated ``ln(10)``.  A folded value
    that used the ideal constant would differ from the emitted model in its
    last bits.
    """

    assert _evaluate_static_arithmetic("exp(1)", {}) == TRUNCATED_E
    assert _evaluate_static_arithmetic("exp(1)", {}) != math.exp(1)
    assert _evaluate_static_arithmetic("log10(100)", {}) == (
        math.log(100.0) / TRUNCATED_LN10
    )
    assert _evaluate_static_arithmetic("log10(100)", {}) != math.log10(100.0)


@pytest.mark.parametrize(
    ("math_body", "formula", "expected"),
    [
        (
            "<apply><exp/><cn>2</cn></apply>",
            "exp(2)",
            TRUNCATED_E**2,
        ),
        (
            "<apply><log/><logbase><cn>10</cn></logbase><cn>100</cn></apply>",
            "log10(100)",
            math.log(100.0) / TRUNCATED_LN10,
        ),
        (
            "<apply><root/><degree><cn>2</cn></degree><cn>4</cn></apply>",
            "root(2, 4)",
            2.0,
        ),
        (
            "<apply><abs/><cn>-1</cn></apply>",
            "abs(-1)",
            1.0,
        ),
        (
            "<apply><factorial/><cn>4</cn></apply>",
            "factorial(4)",
            24.0,
        ),
    ],
)
def test_the_emitted_literal_denotes_the_folded_double(math_body, formula, expected):
    """A folded constant and the model emitted from it are one double."""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        _model_with_parameter_initial_assignment(math_body)
    )

    assert result.success, result.error
    folded = _evaluate_static_arithmetic(formula, {})
    assert folded == expected
    literal = re.search(r"^  k (.+)$", result.bngl, re.MULTILINE)
    assert literal is not None, result.bngl
    assert float(literal.group(1)) == folded


def test_a_fractional_stoichiometry_keeps_every_digit_in_the_flux_coefficient():
    """The lowered rule *is* the species' derivative.

    A coefficient rounded to six significant digits changes the trajectory,
    so the deterministic flux lowering has to carry the source value.
    """

    stoichiometry = 5.562281727754396
    sbml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="fractional_flux">
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="C" initialAmount="1" constant="false"/>
          <species id="B" compartment="C" initialAmount="0" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants>
              <speciesReference species="A" stoichiometry="{stoichiometry!r}" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="B" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)

    assert result.success, result.error
    assert f"({stoichiometry!r})" in result.bngl
    assert "5.56228)" not in result.bngl


def test_a_negative_stoichiometry_is_carried_by_the_flux_lowering():
    """SBML allows a negative stoichiometry; BNGL's pattern does not.

    SBML Level 3 Version 2 Core Sec. 4.11.3 defines the stoichiometry of a
    species reference, and a negative value means the species is consumed
    where it is listed as a product.  A BNGL reaction pattern can only spell
    a nonnegative molecule count, so the sign has to live in the rate
    coefficient of the deterministic flux lowering.
    """

    sbml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="negative_stoichiometry">
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="C" initialAmount="0" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants/>
            <listOfProducts>
              <speciesReference species="A" stoichiometry="-2.5" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""

    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(sbml)

    assert result.success, result.error
    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning["category"] == "stoichiometry" and warning["severity"] == "dropped"
    ], atomizer.model.import_warnings
    # The species is consumed, so the derivative is negative.
    assert "J0_consume_A: @C:M_A() -> 0 (2.5) * (1) TotalRate" in result.bngl


def test_a_negative_assigned_stoichiometry_is_carried_by_the_flux_lowering():
    """The same holds for a stoichiometry an initial assignment sets."""

    sbml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="negative_assigned_stoichiometry">
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="C" initialAmount="0" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants/>
            <listOfProducts>
              <speciesReference id="A_sr" species="A" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfInitialAssignments>
          <initialAssignment symbol="A_sr">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><asin/><cn>-0.5</cn></apply>
            </math>
          </initialAssignment>
        </listOfInitialAssignments>
      </model>
    </sbml>"""

    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(sbml)

    assert result.success, result.error
    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning["category"] == "stoichiometry" and warning["severity"] == "dropped"
    ], atomizer.model.import_warnings
    assert "@C:M_A() -> 0 (0.5235987755982988) * (1) TotalRate" in result.bngl


def test_an_unknown_builtin_is_not_folded():
    """A function the table does not know keeps the expression dynamic."""

    assert _evaluate_static_arithmetic("nosuchfunction(1)", {}) is None
    assert evaluate_math_builtin("nosuchfunction", [1.0]) is None
