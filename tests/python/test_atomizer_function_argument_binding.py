"""Regression tests for the argument binding of SBML function definitions.

SBML Level 3 Version 2 Core (Sec. 4.3.5, *FunctionDefinition*) defines a
function definition as a MathML ``<lambda>``: the ``<bvar>`` elements declare
the function's arguments and the lambda's body is evaluated with those
arguments bound.  A call site's argument expressions are evaluated in the
*caller's* scope and only then bound to the callee's ``bvar`` names.

Substituting the formal arguments one at a time re-scans the text that the
previous substitution just inserted, so a caller argument that happens to
spell one of the callee's formal names is captured by the wrong binding.  The
official SBML Test Suite cases ``semantic/01492`` and ``semantic/01493`` exist
to check exactly this: their ``my_piecewise`` definition has the formal names
``x``, ``y`` and ``z``, and the caller's own ``x`` and ``y`` are rate-ruled
parameters.
"""

from __future__ import annotations

import numpy as np

from bionetgen.atomizer.modern import Atomizer

_MODEL = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="function_binding">
    <listOfFunctionDefinitions>
      <functionDefinition id="my_piecewise">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <lambda>
            <bvar><ci> x </ci></bvar>
            <bvar><ci> y </ci></bvar>
            <bvar><ci> z </ci></bvar>
            <piecewise>
              <piece><ci> x </ci><ci> y </ci></piece>
              <otherwise><ci> z </ci></otherwise>
            </piecewise>
          </lambda>
        </math>
      </functionDefinition>
      <functionDefinition id="my_gt">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <lambda>
            <bvar><ci> x </ci></bvar>
            <bvar><ci> y </ci></bvar>
            <apply><gt/><ci> x </ci><ci> y </ci></apply>
          </lambda>
        </math>
      </functionDefinition>
      <functionDefinition id="my_lteq">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <lambda>
            <bvar><ci> x </ci></bvar>
            <bvar><ci> y </ci></bvar>
            <apply><leq/><ci> x </ci><ci> y </ci></apply>
          </lambda>
        </math>
      </functionDefinition>
    </listOfFunctionDefinitions>
    <listOfParameters>
      <parameter id="z" constant="false"/>
      <parameter id="y" value="2" constant="false"/>
      <parameter id="x" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="z">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><ci> my_piecewise </ci>
            <apply><ci> my_piecewise </ci>
              <cn type="integer"> 2 </cn>
              <apply><ci> my_gt </ci><ci> y </ci><cn> 1.49 </cn></apply>
              <cn type="integer"> 1 </cn>
            </apply>
            <apply><ci> my_lteq </ci><ci> x </ci><cn> 0.49 </cn></apply>
            {otherwise}
          </apply>
        </math>
      </assignmentRule>
      <rateRule variable="y">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <cn type="integer"> -2 </cn>
        </math>
      </rateRule>
      <rateRule variable="x">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <cn type="integer"> 1 </cn>
        </math>
      </rateRule>
    </listOfRules>
  </model>
</sbml>"""


def _atomize(otherwise: str):
    sbml = _MODEL.format(otherwise=otherwise)
    result = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert result.success, result.error
    return result.bngl


def _simulate(bngl: str, sample_times):
    from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp

    model = cpp.parse_string(bngl)
    return BioNetGenModel(model).simulate(
        method="ode",
        t_start=0,
        t_end=1,
        n_steps=0,
        sample_times=list(sample_times),
        rtol=1e-9,
        atol=1e-14,
    )


def _assignment_rule_body(bngl: str, variable: str) -> str:
    """Return the emitted body of the assignment rule for ``variable``."""

    for line in bngl.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{variable}() = "):
            return stripped[len(f"{variable}() = ") :]
    raise AssertionError(f"no assignment rule body for {variable} in\n{bngl}")


def test_caller_argument_is_not_captured_by_the_callee_formal_name():
    """The official reference for ``semantic/01492``.

    ``z = my_piecewise(my_piecewise(2, my_gt(y, 1.49), 1), my_lteq(x, 0.49), 0)``
    reads the caller's rate-ruled ``x`` and ``y``.  The callee's formal names
    ``x`` and ``y`` must not capture them.
    """

    bngl = _atomize('<cn type="integer"> 0 </cn>')

    # ``my_gt(y, 1.49)`` has to read the caller's ``y``; the value of the
    # caller's ``x`` may only appear in the ``my_lteq(x, 0.49)`` term.
    body = _assignment_rule_body(bngl, "z")
    assert "y_amt" in body
    assert body.count("x_amt") == 1


def test_official_01492_trajectory():
    """The official reference values for ``semantic/01492``."""

    bngl = _atomize('<cn type="integer"> 0 </cn>')
    times = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    result = _simulate(bngl, times)

    expected = [2, 2, 2, 1, 1, 0, 0, 0, 0, 0, 0]
    np.testing.assert_allclose(result.functions["z"], expected, rtol=0, atol=1e-12)


def test_official_01493_trajectory():
    """The official reference values for ``semantic/01493``.

    The nested ``otherwise`` term reads the caller's ``y`` a second time, so
    the same binding rule has to hold for it.
    """

    otherwise = (
        "<apply><ci> my_piecewise </ci>"
        '<cn type="integer"> 1 </cn>'
        "<apply><ci> my_gt </ci><ci> y </ci><cn> 0.49 </cn></apply>"
        '<cn type="integer"> 0 </cn>'
        "</apply>"
    )
    bngl = _atomize(otherwise)
    times = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    result = _simulate(bngl, times)

    expected = [2, 2, 2, 1, 1, 1, 1, 1, 0, 0, 0]
    np.testing.assert_allclose(result.functions["z"], expected, rtol=0, atol=1e-12)
