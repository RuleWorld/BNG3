"""Regression tests for SBML delayed reads of a rate and of an initial value.

SBML Level 3 Version 2 Core Sec. 3.4.6 ("Use of csymbol elements in MathML
expressions in SBML") and Sec. 3.4.8 ("Initial conditions and special
considerations") fix the two boundary rules that the Atomizer has to honour:

* "The rateOf value for any valid target in SBML for time *t* < 0 will always
  be zero."  A delayed read of a rate therefore observes zero while the
  delayed time is still before the start of the simulation.  The official
  SBML Test Suite cases ``semantic/01400``, ``01401``, ``01403``, ``01406`` and
  ``01409`` check exactly this: each of them assigns
  ``P1 = delay(rateOf(S1), 1)`` and the official reference gives ``P1 = 0``
  until the delayed time reaches the start of the simulation.

* "Any InitialAssignment definition continues to take effect" for times
  before the simulation starts, "since these contain mathematical formulas,
  different values may be computed at each time step".  A delayed read of such
  a symbol therefore returns the assignment evaluated at the delayed time, not
  the symbol's value at ``t = 0``.  The official cases ``semantic/00941`` and
  ``00943`` check that for a parameter; ``00938``, ``00940`` and ``00942`` check
  it for a species.
"""

from __future__ import annotations

import numpy as np
import pytest

from bionetgen.atomizer.modern import Atomizer
from bionetgen.atomizer.modern.parser import SBMLParser
from bionetgen.atomizer.modern.writer import _lower_bounded_event_state_delays

_DELAYED_RATE = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="delayed_rate">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialConcentration="5"
               hasOnlySubstanceUnits="false" boundaryCondition="false"
               constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="P0" constant="false"/>
      <parameter id="P1" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="P0">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text"
                     definitionURL="http://www.sbml.org/sbml/symbols/rateOf"> rateOf </csymbol>
            <ci> S1 </ci>
          </apply>
        </math>
      </assignmentRule>
      <assignmentRule variable="P1">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text"
                     definitionURL="http://www.sbml.org/sbml/symbols/delay"> delay </csymbol>
            <apply>
              <csymbol encoding="text"
                       definitionURL="http://www.sbml.org/sbml/symbols/rateOf"> rateOf </csymbol>
              <ci> S1 </ci>
            </apply>
            <cn type="integer"> 1 </cn>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="J0" reversible="true">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn> 0.1 </cn><ci> S1 </ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""


_DELAYED_INITIAL_ASSIGNMENT = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="delayed_initial_assignment">
    <listOfParameters>
      <parameter id="x" value="0" constant="false"/>
      <parameter id="y" constant="false"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="x">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <sin/>
            <apply>
              <times/><cn type="integer"> 10 </cn>
              <csymbol encoding="text"
                       definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol>
            </apply>
          </apply>
        </math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfRules>
      <assignmentRule variable="y">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <plus/><cn type="integer"> 2 </cn>
            <apply>
              <csymbol encoding="text"
                       definitionURL="http://www.sbml.org/sbml/symbols/delay"> delay </csymbol>
              <ci> x </ci><cn> 0.5 </cn>
            </apply>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>"""


_DELAYED_CONSTANT_ASSIGNMENT = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
    level="3" version="2">
  <model id="delayed_constant_assignment">
    <listOfParameters>
      <parameter id="x" value="1" constant="false"/>
      <parameter id="y" value="1" constant="false"/>
      <parameter id="z" value="1" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="x">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol>
        </math>
      </rateRule>
      <assignmentRule variable="y">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
            <ci>x</ci><cn type="integer">3</cn>
          </apply>
        </math>
      </assignmentRule>
      <algebraicRule>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <minus/><ci>z</ci>
            <apply>
              <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
              <ci>y</ci>
              <apply>
                <divide/>
                <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol>
                <cn type="integer">2</cn>
              </apply>
            </apply>
          </apply>
        </math>
      </algebraicRule>
    </listOfRules>
  </model>
</sbml>"""


_CASE_SENSITIVE_TIME_ID = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
    level="3" version="2">
  <model id="case_sensitive_time_id">
    <listOfParameters>
      <parameter id="Time" value="2" constant="false"/>
      <parameter id="y" value="1" constant="false"/>
      <parameter id="z" value="1" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="Time">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0</cn></math>
      </rateRule>
      <assignmentRule variable="y">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <piecewise>
            <piece>
              <cn>1</cn>
              <apply>
                <geq/>
                <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol>
                <cn>0</cn>
              </apply>
            </piece>
            <otherwise><cn>0</cn></otherwise>
          </piecewise>
        </math>
      </assignmentRule>
      <algebraicRule>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <minus/><ci>z</ci>
            <apply>
              <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
              <ci>y</ci><ci>Time</ci>
            </apply>
          </apply>
        </math>
      </algebraicRule>
    </listOfRules>
  </model>
</sbml>"""


def _atomize(xml: str) -> str:
    result = Atomizer(atomize=False, quiet_mode=True).atomize(xml)
    assert result.success, result.error
    return result.bngl


def _function_body(bngl: str, name: str) -> str:
    for line in bngl.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{name}() = "):
            return stripped[len(f"{name}() = ") :]
    raise AssertionError(f"no function {name} in\n{bngl}")


def test_delayed_rate_is_zero_before_the_simulation_starts():
    """The official reference for ``semantic/01400``.

    ``P1 = delay(rateOf(S1), 1)`` is zero for every ``t < 1`` and equals the
    rate at ``t - 1`` afterwards.
    """

    bngl = _atomize(_DELAYED_RATE)
    body = _function_body(bngl, "P1")

    assert "if(time() < (1), 0," in body


def test_delayed_rate_matches_the_official_reference():
    bngl = _atomize(_DELAYED_RATE)

    from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp

    model = cpp.parse_string(bngl)
    times = [float(index) for index in range(11)]
    result = BioNetGenModel(model).simulate(
        method="ode",
        t_start=0,
        t_end=10,
        n_steps=0,
        sample_times=times,
        rtol=1e-9,
        atol=1e-14,
    )

    expected = [
        0.0,
        -0.5,
        -0.45241870901797976,
        -0.4093653765389908,
        -0.3704091103408587,
        -0.3351600230178194,
        -0.3032653300178906,
        -0.2744058180016994,
        -0.2482926520017343,
        -0.2246644820017064,
        -0.2032848300017318,
    ]
    np.testing.assert_allclose(result.functions["P1"], expected, rtol=0, atol=1e-9)


def test_initial_assignment_keeps_its_t0_value_and_its_history():
    """The official reference for ``semantic/00941``.

    ``x`` is assigned ``sin(10 * time)`` by an initial assignment, so it holds
    ``sin(0) = 0`` for the whole run, while a delayed read of it observes the
    assignment evaluated at the delayed time.
    """

    bngl = _atomize(_DELAYED_INITIAL_ASSIGNMENT)

    assert _function_body(bngl, "x") == "0.0"
    body = _function_body(bngl, "y")
    assert "sin((10 * (time() - 0.5)))" in body
    assert "time() < 0.5" in body


def test_delayed_initial_assignment_matches_the_official_reference():
    bngl = _atomize(_DELAYED_INITIAL_ASSIGNMENT)

    from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp

    model = cpp.parse_string(bngl)
    times = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    result = BioNetGenModel(model).simulate(
        method="ode",
        t_start=0,
        t_end=1,
        n_steps=0,
        sample_times=times,
        rtol=1e-9,
        atol=1e-14,
    )

    expected = [
        2 + np.sin(-5.0),
        2 + np.sin(-4.0),
        2 + np.sin(-3.0),
        2 + np.sin(-2.0),
        2 + np.sin(-1.0),
        2.0,
        2.0,
        2.0,
        2.0,
        2.0,
        2.0,
    ]
    np.testing.assert_allclose(result.functions["y"], expected, rtol=0, atol=1e-9)
    np.testing.assert_allclose(result.functions["x"], 0.0, rtol=0, atol=1e-12)


def test_bounded_dynamic_delay_of_constant_assignment_is_folded_exactly():
    """The nested delay in official semantic/01142 is constant through t=1.

    The rate rule for x only acts for t > 0.  For y(t)=delay(x, 3),
    y(t)=1 on [0, 1], and z(t)=delay(y, t/2) therefore also equals 1.
    The dynamic lag is finite and nonnegative throughout this requested
    simulation interval, so lowering it to the proven value is exact.
    """
    libsbml = pytest.importorskip("libsbml", exc_type=ImportError)
    source_document = libsbml.readSBMLFromString(_DELAYED_CONSTANT_ASSIGNMENT)
    assert source_document.getNumErrors() == 0, source_document.getErrorLog().toString()

    model = SBMLParser().parse(_DELAYED_CONSTANT_ASSIGNMENT)

    lowered = _lower_bounded_event_state_delays(model, 1.0)

    assert lowered == 2
    rules = {rule.variable: rule.math for rule in model.rules if rule.variable}
    assert rules["y"] == "1.0"
    assert "delay(" not in rules["z"].lower()


def test_bounded_dynamic_delay_keeps_invalid_duration_unfolded():
    """Folding may not erase SBML's nonnegative-duration requirement."""
    xml = _DELAYED_CONSTANT_ASSIGNMENT.replace(
        '<cn type="integer">2</cn>', '<cn type="integer">-2</cn>'
    )
    model = SBMLParser().parse(xml)

    lowered = _lower_bounded_event_state_delays(model, 1.0)

    rules = {rule.variable: rule.math for rule in model.rules if rule.variable}
    assert lowered == 1
    assert rules["y"] == "1.0"
    assert "delay(" in rules["z"].lower()


def test_bounded_dynamic_delay_keeps_nonfinite_duration_unfolded():
    """An unbounded duration such as time/0 keeps its runtime domain check."""
    xml = _DELAYED_CONSTANT_ASSIGNMENT.replace(
        '<cn type="integer">2</cn>', '<cn type="integer">0</cn>'
    )
    model = SBMLParser().parse(xml)

    _lower_bounded_event_state_delays(model, 1.0)

    rules = {rule.variable: rule.math for rule in model.rules if rule.variable}
    assert "delay(" in rules["z"].lower()


def test_bounded_dynamic_delay_does_not_assume_history_outside_horizon():
    """The static lag of x stops being constant after the rate rule starts."""
    model = SBMLParser().parse(_DELAYED_CONSTANT_ASSIGNMENT)

    _lower_bounded_event_state_delays(model, 4.0)

    rules = {rule.variable: rule.math for rule in model.rules if rule.variable}
    assert "delay(" in rules["y"].lower()
    assert "delay(" in rules["z"].lower()


def test_sbml_parameter_named_time_is_not_the_time_csymbol():
    """SBML SIds are case-sensitive; `Time` here stays equal to 2."""
    model = SBMLParser().parse(_CASE_SENSITIVE_TIME_ID)

    # The parser's MathML printer uses its own geq(...) spelling, whereas the
    # bounded-expression prover consumes the normalized if/comparison form
    # emitted by this same writer. Keep the source fixture authoritative for
    # identifiers, and express the equivalent assignment in that form here.
    y_rule = next(rule for rule in model.rules if rule.variable == "y")
    y_rule.math = "if(time >= 0, 1, 0)"

    _lower_bounded_event_state_delays(model, 1.0)

    rules = {rule.variable: rule.math for rule in model.rules if rule.variable}
    assert "delay(" in rules["z"].lower()
