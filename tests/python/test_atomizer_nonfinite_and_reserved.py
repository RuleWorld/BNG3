"""Regression tests for non-finite parameter values and the reserved ``time`` id.

Two SBML constructs the Atomizer used to accept silently:

* a parameter whose declared value is ``INF``, ``-INF`` or ``NaN`` has no
  exact BNGL spelling.  The parser replaced the declaration with a finite
  number and the writer substituted a large finite value for an infinity
  without saying so, so the model silently disagreed with its source.
* a parameter whose identifier is ``time`` collides with BNGL's reserved
  ``time`` operand.  The Atomizer emits it under a non-reserved spelling, so
  a reference to that parameter has to be compared against that spelling
  instead of against the simulation time.

The harness-side contract for the reserved id is covered by
``tests/python/test_sbml_validation_contracts.py``.
"""

from __future__ import annotations

import math

from bionetgen.atomizer.modern import Atomizer


def _model(parameters: str) -> str:
    return (
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" '
        'level="3" version="2">'
        f'<model id="reserved"><listOfParameters>{parameters}</listOfParameters>'
        "</model>"
        "</sbml>"
    )


def _atomize(parameters: str):
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(_model(parameters))
    assert result.success, result.error
    return atomizer, result


def _parameter_warnings(atomizer: Atomizer) -> list[dict]:
    return [
        warning
        for warning in atomizer.model.import_warnings
        if warning.category == "parameter"
    ]


def test_infinite_parameter_value_is_not_reported_as_an_approximation():
    atomizer, _ = _atomize('<parameter id="P" value="INF" constant="true"/>')

    assert not _parameter_warnings(atomizer)


def test_negative_infinite_parameter_value_is_not_reported_as_an_approximation():
    atomizer, _ = _atomize('<parameter id="Q" value="-INF" constant="true"/>')

    assert not _parameter_warnings(atomizer)


def test_nan_parameter_value_is_not_reported_as_an_approximation():
    atomizer, _ = _atomize('<parameter id="R" value="NaN" constant="true"/>')

    assert not _parameter_warnings(atomizer)


def test_non_finite_parameter_value_is_kept_in_the_model():
    # The declared value must survive parsing: replacing it with a finite
    # number would make the model disagree with its source before the writer
    # ever gets the chance to report the approximation.
    atomizer, _ = _atomize(
        '<parameter id="P" value="INF" constant="true"/>'
        '<parameter id="Q" value="-INF" constant="true"/>'
        '<parameter id="R" value="NaN" constant="true"/>'
    )

    assert math.isinf(atomizer.model.parameters["P"].value)
    assert atomizer.model.parameters["P"].value > 0
    assert math.isinf(atomizer.model.parameters["Q"].value)
    assert atomizer.model.parameters["Q"].value < 0
    assert math.isnan(atomizer.model.parameters["R"].value)


def test_non_finite_parameter_values_are_emitted_exactly():
    import pytest

    _, result = _atomize(
        '<parameter id="P" value="INF" constant="true"/>'
        '<parameter id="Q" value="-INF" constant="true"/>'
        '<parameter id="R" value="NaN" constant="true"/>'
    )

    parameters = result.bngl.split("begin parameters", 1)[1].split(
        "end parameters", 1
    )[0]
    assert "P exp(1000)" in parameters
    assert "Q -exp(1000)" in parameters
    assert "R sqrt(-1)" in parameters
    assert "1e20" not in parameters
    assert " R 0" not in parameters
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    cpp.parse_string(result.bngl)


def test_a_parameter_named_time_is_emitted_under_a_non_reserved_spelling():
    _, result = _atomize(
        '<parameter id="time" value="10" constant="true"/>'
        '<parameter id="Time" value="11" constant="true"/>'
        '<parameter id="TIME" value="12" constant="true"/>'
    )

    parameters = [
        line.strip()
        for line in result.bngl.splitlines()
        if line.strip().startswith(("time", "Time", "TIME"))
    ]
    assert "time_id 10" in parameters
    assert "Time 11" in parameters
    assert "TIME 12" in parameters
