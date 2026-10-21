"""Regression tests for the SBML ``time`` csymbol against a model symbol.

SBML Level 3 Version 2 Core defines the built-in MathML ``csymbol`` elements
by their ``definitionURL``; the element text is only a display label and may
be empty or misleading.  The ``time`` csymbol is therefore the simulation
clock, and it is not the same thing as a model symbol that happens to be
called ``time``.

The official SBML Test Suite pins this in ``semantic/01821``: the model
declares parameters ``time`` (10), ``Time`` (11) and ``TIME`` (12), and its
initial assignments read the parameter through ``<ci>`` and the clock through
the ``time`` ``csymbol``.  The official results give ``a = 10``, ``b = 11``,
``c = 12`` and ``d = 0`` -- the clock is zero at the start of a simulation.
"""

from __future__ import annotations

import pytest

from bionetgen.atomizer.modern import Atomizer, SBMLParser

MATHML_NS = "http://www.w3.org/1998/Math/MathML"
TIME_CSYMBOL = (
    '<csymbol encoding="text" '
    'definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol>'
)


def _model(parameters: str, initial_assignments: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
      <model id="time_csymbol">
        <listOfParameters>{parameters}</listOfParameters>
        <listOfInitialAssignments>{initial_assignments}</listOfInitialAssignments>
      </model>
    </sbml>
    """


def _initial_assignment(symbol: str, math: str) -> str:
    return (
        f'<initialAssignment symbol="{symbol}">'
        f'<math xmlns="{MATHML_NS}">{math}</math>'
        f"</initialAssignment>"
    )


def test_time_csymbol_is_the_clock_not_a_parameter_named_time():
    # semantic/01821: <ci> time </ci> reads the parameter, while the time
    # csymbol reads the simulation clock, which is zero at t=0.
    model = SBMLParser().parse(
        _model(
            '<parameter id="time" value="10" constant="true"/>'
            '<parameter id="Time" value="11" constant="true"/>'
            '<parameter id="TIME" value="12" constant="true"/>'
            '<parameter id="a" constant="true"/>'
            '<parameter id="b" constant="true"/>'
            '<parameter id="c" constant="true"/>'
            '<parameter id="d" constant="true"/>',
            _initial_assignment("a", "<ci> time </ci>")
            + _initial_assignment("b", "<ci> Time </ci>")
            + _initial_assignment("c", "<ci> TIME </ci>")
            + _initial_assignment("d", TIME_CSYMBOL),
        )
    )

    # The <ci> references read the declared parameters ...
    assert model.parameters["a"].value == pytest.approx(10.0)
    assert model.parameters["b"].value == pytest.approx(11.0)
    assert model.parameters["c"].value == pytest.approx(12.0)
    # ... and the csymbol reads the clock, which is zero when the initial
    # values are established.  It must not pick up the parameter named
    # "time", whose declared value is 10.
    assert model.parameters["d"].value == pytest.approx(0.0)


def test_time_csymbol_stays_the_clock_in_the_generated_model():
    # The generated model must keep the two apart as well: the parameter is
    # emitted under a non-reserved spelling, and the clock stays the clock.
    res = Atomizer(atomize=False, quiet_mode=True).atomize(
        _model(
            '<parameter id="time" value="10" constant="true"/>'
            '<parameter id="d" constant="true"/>',
            _initial_assignment("d", TIME_CSYMBOL),
        )
    )
    assert res.success, res.error
    parameters = {}
    in_parameters = False
    for line in res.bngl.splitlines():
        stripped = line.strip()
        if stripped == "begin parameters":
            in_parameters = True
            continue
        if stripped == "end parameters":
            break
        if in_parameters and stripped and not stripped.startswith("#"):
            name, _, value = stripped.partition(" ")
            parameters[name] = value
    assert parameters.get("time_id") == "10", parameters
    assert parameters.get("d") == "0", parameters
    assert "time" not in parameters, parameters
