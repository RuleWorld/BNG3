"""A reaction's rate is an output of the generated model, not a frozen constant.

SBML Level 3 Version 2 Core, Sec. 4.11.8: "The value of the ``id``
attribute of a Reaction can be used as the content of a ``ci`` element in
MathML formulas elsewhere in the model.  Such a ``ci`` element or symbol
represents the rate of the given reaction as given by the reaction's
KineticLaw object."  Sec. 4.2.5 makes that rate the rate of change of the
reaction's *extent*, and Sec. 4.6 makes a species' value its amount when it
has ``hasOnlySubstanceUnits="true"`` and its concentration otherwise.

The official SBML Test Suite asks for a reaction's rate by naming the
reaction id as a result variable.  The twenty-two cases below are the ones
whose official reference does exactly that; their reference columns are the
reaction's extent rate.  Each case is reproduced here from the pinned suite
revision ``cf38585fac5de8e0e90112febb62851ee2181816`` with its own
``-settings.txt`` tolerances and its own ``-results.csv`` numbers, so the
assertions are the official reference's own numbers.

Before the change the Atomizer emitted nothing that carried a reaction's
rate, so the generated model could not state it and the official reference
was not comparable at all.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

FIXTURES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "sbml_test_suite_reaction_rate"
)

# The official cases whose reference names a reaction id as a result variable.
# The value beside each id is the reference column that carries the
# reaction's rate; the reference columns are read from the case's own
# ``-results.csv``.
REACTION_RATE_CASES = [
    ("01344", ["J1"]),
    ("01345", ["J1"]),
    ("01346", ["J1"]),
    ("01347", ["J1"]),
    ("01348", ["J1"]),
    ("01349", ["J1"]),
    ("01350", ["J1"]),
    ("01351", ["J1", "A__J2"]),
    ("01352", ["J1"]),
    ("01360", ["A__J2"]),
    ("01369", ["A__J2"]),
    ("01378", ["A__J2"]),
    ("01380", ["J1"]),
    ("01381", ["J1"]),
    ("01382", ["J1"]),
    ("01383", ["J1"]),
    ("01384", ["J1"]),
    ("01385", ["J1"]),
    ("01386", ["J1"]),
    ("01387", ["J1", "A__J2"]),
    ("01388", ["J1"]),
    ("01389", ["J1"]),
]


def _settings(case_id: str) -> dict[str, str]:
    text = (FIXTURES / f"{case_id}-settings.txt").read_text(encoding="utf-8")
    settings = {}
    for line in text.splitlines():
        if ": " in line:
            key, _, value = line.partition(": ")
            settings[key.strip()] = value.strip()
    return settings


def _reference_rows(case_id: str) -> list[dict[str, str]]:
    with (FIXTURES / f"{case_id}-results.csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _source(case_id: str) -> str:
    return (FIXTURES / f"{case_id}-sbml-l3v2.xml").read_text(encoding="utf-8")


def _atomized(case_id: str):
    from bionetgen.atomizer.modern import Atomizer

    result = Atomizer(atomize=False, quiet_mode=True).atomize(_source(case_id))
    assert result.success, result.error
    return result


def _simulate(bngl: str, times: list[float]):
    import bionetgen._bionetgen_cpp as cpp
    from bionetgen import BioNetGenModel

    model = cpp.parse_string(bngl)
    return BioNetGenModel(model).simulate(
        method="ode",
        t_start=times[0],
        t_end=times[-1],
        n_steps=0,
        sample_times=times,
        rtol=1e-9,
        atol=1e-14,
    )


@pytest.mark.parametrize("case_id,rate_columns", REACTION_RATE_CASES)
def test_official_reference_reaction_rate_is_reproduced(case_id, rate_columns):
    """The generated model states the reaction's rate the reference reports."""

    settings = _settings(case_id)
    rows = _reference_rows(case_id)
    times = [float(row["time"]) for row in rows]
    absolute = float(settings["absolute"])
    relative = float(settings["relative"])

    result = _atomized(case_id)
    simulation = _simulate(result.bngl, times)
    functions = simulation.functions

    for column in rate_columns:
        # The Atomizer names the function that carries the reaction's rate.
        function_name = result.reaction_rate_functions.get(column)
        assert (
            function_name
        ), f"{case_id}: the generated model states no rate for reaction {column}"
        assert f"{function_name}()" in result.bngl

        expected = [float(row[column]) for row in rows]
        actual = list(functions[function_name])
        assert len(actual) == len(expected)
        for index, (want, got) in enumerate(zip(expected, actual)):
            tolerance = absolute + relative * abs(want)
            assert abs(want - got) <= tolerance, (
                f"{case_id}: reaction {column} rate at t={times[index]} is {got}, "
                f"the official reference reports {want}"
            )


@pytest.mark.parametrize("case_id,rate_columns", REACTION_RATE_CASES)
def test_harness_maps_a_reaction_id_onto_the_rate_function(case_id, rate_columns):
    """The comparison harness selects the rate function for a reaction id."""

    from scripts.ci import validate_sbml_test_suite as runner
    from bionetgen.atomizer.modern import SBMLParser
    from bionetgen.atomizer.modern.types import standardize_name

    parsed = SBMLParser().parse(_source(case_id))
    result = _atomized(case_id)
    reference = {"amount": [], "concentration": []}

    for column in rate_columns:
        target = runner._reference_output_target(
            column,
            reference,
            parsed,
            dict(result.observable_map),
            standardize_name,
            dict(result.reaction_rate_functions),
        )
        assert target == result.reaction_rate_functions[column]


def test_the_rate_is_a_function_of_the_state_and_not_a_frozen_constant():
    """A state-dependent rate is evaluated along the trajectory."""

    import bionetgen._bionetgen_cpp as cpp
    from bionetgen import BioNetGenModel
    from bionetgen.atomizer.modern import Atomizer

    source = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="state_dependent_rate">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialConcentration="3" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
      <species id="S2" compartment="C" initialConcentration="1" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.5" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="J1" reversible="false">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="S2" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>S1</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(source)
    assert result.success, result.error
    # ``S1`` has no substance units, so the SBML symbol denotes its
    # concentration (Sec. 4.6) and the rate is ``k * [S1]``.
    assert "J1_rate() = k * _c_S1()" in result.bngl

    model = cpp.parse_string(result.bngl)
    times = [0.0, 1.0, 2.0, 3.0, 4.0]
    simulation = BioNetGenModel(model).simulate(
        method="ode",
        t_start=0.0,
        t_end=4.0,
        n_steps=0,
        sample_times=times,
        rtol=1e-9,
        atol=1e-14,
    )
    rates = list(simulation.functions["J1_rate"])
    concentrations = list(simulation.observables["S1"])
    assert rates[0] == pytest.approx(0.5 * concentrations[0])
    # The rate falls with the substrate, so it is not frozen at ``t = 0``.
    assert rates[-1] < rates[0]
    for index, rate in enumerate(rates):
        assert rate == pytest.approx(0.5 * concentrations[index])


def test_a_reaction_without_a_kinetic_law_states_no_rate():
    """A reaction with no kinetic law has an undefined rate (Sec. 4.11.2)."""

    from bionetgen.atomizer.modern import Atomizer

    source = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="no_kinetic_law">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialConcentration="3" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J1" reversible="false">
        <listOfProducts>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
        </listOfProducts>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(source)
    assert "J1" not in result.reaction_rate_functions


def test_the_vendored_fixtures_match_the_pinned_suite_revision():
    """The vendored official inputs are the pinned suite's own bytes."""

    selection = json.loads((FIXTURES / "selection.json").read_text(encoding="utf-8"))
    assert selection["suite_revision"] == "cf38585fac5de8e0e90112febb62851ee2181816"
    import hashlib

    for entry in selection["cases"]:
        for name, digest in entry["files"].items():
            data = (FIXTURES / name).read_bytes()
            assert "sha256:" + hashlib.sha256(data).hexdigest() == digest, name


def test_every_closed_case_is_covered_by_the_regression_table():
    """The table names the cases the cluster closed, and no others."""

    assert len(REACTION_RATE_CASES) == 22
    assert [case for case, _ in REACTION_RATE_CASES] == sorted(
        case for case, _ in REACTION_RATE_CASES
    )
    for case_id, columns in REACTION_RATE_CASES:
        header = (
            (FIXTURES / f"{case_id}-results.csv")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        names = [name.strip() for name in header.split(",")]
        for column in columns:
            assert column in names
        # The rate column names a reaction, not a species or a parameter.
        from bionetgen.atomizer.modern import SBMLParser

        parsed = SBMLParser().parse(_source(case_id))
        for column in columns:
            assert column in parsed.reactions
            assert column not in parsed.species
            assert column not in parsed.parameters
            assert re.match(r"^[A-Za-z_][A-Za-z_0-9]*$", column)
