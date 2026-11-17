"""Analytic fixtures for Core rows absent from the official SSTS suite.

Four `sbml.core.*` inventory rows have no case in the pinned official suite:
Parameter.units, Constraint.message, Reaction.compartment and
LocalParameter.units. Each fixture below exercises the construct in otherwise
identical source semantics (A -> 0 with rate 1 from A0=100), so the independent
analytic law A(t) = 100 - t (constant unit flux) qualifies the translation and execution path.
These are pre-requisite fixtures for release-ssts-coverage; they do not by
themselves discharge the reviewed row-to-case mapping.
"""

from pathlib import Path

import pytest

from bionetgen.atomizer.modern import Atomizer

_FIXTURES = Path(__file__).resolve().parents[5] / "provenance/core-fixtures"
import bionetgen._bionetgen_cpp as cpp

ROWS = {
    "parameter-units": "sbml.core.Parameter.units",
    "constraint-message": "sbml.core.Constraint.message",
    "reaction-compartment": "sbml.core.Reaction.compartment",
    "localparameter-units": "sbml.core.LocalParameter.units",
}


@pytest.mark.parametrize("fixture", sorted(ROWS))
def test_core_fixture_matches_analytic_decay(fixture):
    source = _FIXTURES / f"{fixture}.xml"
    assert source.is_file()
    text = source.read_text(encoding="utf-8")
    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=1.0, n_steps=10).atomize(
        text, source_path=source
    )
    assert atomized.success, atomized.error

    model = cpp.parse_string(atomized.bngl)
    network = cpp.generate_network(model, max_iter=100)
    result = cpp.simulate_ode(model, network, t_end=1.0, n_steps=10)
    observed = float(result["observables"]["A_amt"][-1])
    expected = 100.0 - 1.0  # constant flux of 1 for one time unit
    assert abs(observed - expected) <= 1e-6 * max(1.0, expected)


@pytest.mark.parametrize("fixture", sorted(ROWS))
def test_fixture_actually_contains_its_construct(fixture):
    text = (_FIXTURES / f"{fixture}.xml").read_text(encoding="utf-8")
    tokens = {
        "parameter-units": 'units="time"',
        "constraint-message": "<message>",
        "reaction-compartment": 'compartment="C"',
        "localparameter-units": "<localParameter",
    }
    assert tokens[fixture] in text
