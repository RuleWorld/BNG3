"""Regression tests for n-ary MathML relational operators.

MathML permits a relation such as ``gt`` to take more than two operands, and
SBML defines such an n-ary relation as the conjunction of the successive
pairs.  The official SBML Test Suite case ``semantic/01216`` exists to check
exactly this, and its note says an interpreter must "check each successive
pair of variables" because the third and further arguments "change the
results of various 'piecewise' tests".

A C-style chained comparison is a different expression: ``2 > 1 > 2`` is
``(2 > 1) > 2``, which is true, while the pairwise conjunction
``(2 > 1) && (1 > 2)`` is false.
"""

from __future__ import annotations

import pytest

from bionetgen.atomizer.modern.writer import convert_math_expression


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("gt(2, 1)", "(2 > 1)"),
        ("gt(2, 1, 2)", "((2 > 1) && (1 > 2))"),
        ("lt(1, 2, 1)", "((1 < 2) && (2 < 1))"),
        ("geq(2, 1, 2)", "((2 >= 1) && (1 >= 2))"),
        ("leq(1, 2, 1)", "((1 <= 2) && (2 <= 1))"),
        ("eq(1, 1, 2)", "((1 == 1) && (1 == 2))"),
        ("neq(1, 1, 2)", "((1 != 1) && (1 != 2))"),
        (
            "gt(2, 1, 0, 0, -1)",
            "((2 > 1) && (1 > 0) && (0 > 0) && (0 > -1))",
        ),
    ],
)
def test_nary_relation_is_the_conjunction_of_successive_pairs(expression, expected):
    assert convert_math_expression(expression) == expected


def test_variadic_and_and_or_keep_their_nary_meaning():
    # MathML already defines ``and``/``or`` as n-ary conjunction and
    # disjunction, so they must not become a pairwise conjunction.
    assert convert_math_expression("and(1, 2, 3)") == "(1 && 2 && 3)"
    assert convert_math_expression("or(1, 2, 3)") == "(1 || 2 || 3)"


def test_official_01216_piecewise_conditions_use_the_pairwise_conjunction():
    """The official reference for semantic/01216.

    ``a = piecewise(1, gt(2, 1, 2), 3)`` is 3, because the pairwise
    conjunction ``(2 > 1) && (1 > 2)`` is false, while the chained
    comparison ``2 > 1 > 2`` would be true and select the wrong branch.
    """

    from bionetgen.atomizer.modern import Atomizer

    sbml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="nary">
        <listOfRules>
          <assignmentRule variable="a">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <piecewise>
                <piece>
                  <cn type="integer"> 1 </cn>
                  <apply><gt/>
                    <cn type="integer"> 2 </cn>
                    <cn type="integer"> 1 </cn>
                    <cn type="integer"> 2 </cn>
                  </apply>
                </piece>
                <otherwise><cn type="integer"> 3 </cn></otherwise>
              </piecewise>
            </math>
          </assignmentRule>
        </listOfRules>
      </model>
    </sbml>"""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert result.success, result.error
    assert "(2 > 1) && (1 > 2)" in result.bngl
    assert "2 > 1 > 2" not in result.bngl
