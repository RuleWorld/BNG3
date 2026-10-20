"""Stochastic-consistency sweep over converted SBML models.

The sweep in ``scripts/ci/check_stochastic_consistency.py`` compares the
ensemble mean of a batched direct-SSA run against the deterministic reading of
the same converted model, for the models whose reaction network is linear
(first order in its species).  This module exercises that machinery on a small,
hermetic selection so that the check itself stays under test in CI.

The selection is a synthetic mini-suite written into a temporary directory in
the layout the sweep expects (``cases/<category>/<id>/<id>-sbml-*.xml`` plus
the published settings and results).  Writing the fixtures here keeps the
test independent of the pinned SBML Test Suite checkout, and keeps it to a
handful of cases.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from scripts.ci.check_stochastic_consistency import (
    DEFAULT_SEED_BASE,
    _compare_trace,
    main,
)

try:  # the sweep needs the native extension: parse BNGL and run the engines
    from bionetgen import _bionetgen_cpp as _native  # noqa: F401
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(
        f"the native BNG3 extension is not importable: {exc}",
        allow_module_level=True,
    )

SBML_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" '
    'level="3" version="2">\n'
    '  <model id="{model}">\n'
    "    <listOfUnitDefinitions>\n"
    '      <unitDefinition id="volume">\n'
    '        <unit kind="litre" exponent="1" scale="0" multiplier="1"/>\n'
    "      </unitDefinition>\n"
    '      <unitDefinition id="substance">\n'
    '        <unit kind="mole" exponent="1" scale="0" multiplier="1"/>\n'
    "      </unitDefinition>\n"
    '      <unitDefinition id="time">\n'
    '        <unit kind="second" exponent="1" scale="0" multiplier="1"/>\n'
    "      </unitDefinition>\n"
    "    </listOfUnitDefinitions>\n"
    "    <listOfCompartments>\n"
    '      <compartment id="c" size="1" constant="true"/>\n'
    "    </listOfCompartments>\n"
    "    <listOfSpecies>\n"
    "{species}"
    "    </listOfSpecies>\n"
    "    <listOfParameters>\n"
    "{parameters}"
    "    </listOfParameters>\n"
    "    <listOfReactions>\n"
    "{reactions}"
    "    </listOfReactions>\n"
    "  </model>\n"
    "</sbml>\n"
)

SPECIES_TEMPLATE = (
    '      <species id="{id}" compartment="c" initialAmount="{amount}" '
    'substanceUnits="substance" hasOnlySubstanceUnits="true" '
    'boundaryCondition="{boundary}" constant="false"/>\n'
)

PARAMETER_TEMPLATE = '      <parameter id="{id}" value="{value}" constant="true"/>\n'

REACTION_TEMPLATE = (
    '      <reaction id="{id}" reversible="false">\n'
    "        <listOfReactants>\n"
    "{reactants}"
    "        </listOfReactants>\n"
    "        <listOfProducts>\n"
    "{products}"
    "        </listOfProducts>\n"
    "        <kineticLaw>\n"
    '          <math xmlns="http://www.w3.org/1998/Math/MathML">\n'
    "            <apply>\n"
    "              <times/>\n"
    "{factors}"
    "            </apply>\n"
    "          </math>\n"
    "        </kineticLaw>\n"
    "      </reaction>\n"
)

SPECIES_REFERENCE_TEMPLATE = (
    '          <speciesReference species="{id}" stoichiometry="1" constant="true"/>\n'
)


def _factor(name: str) -> str:
    return f"              <ci> {name} </ci>\n"


def _write_case(
    directory: Path,
    case_id: str,
    *,
    species: list[tuple[str, float, bool]],
    parameters: list[tuple[str, float]],
    reactions: list[tuple[str, list[str], list[str], list[str]]],
    settings: dict[str, str],
    results: str,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    text = SBML_HEADER.format(
        model=case_id,
        species="".join(
            SPECIES_TEMPLATE.format(
                id=name, amount=amount, boundary=str(boundary).lower()
            )
            for name, amount, boundary in species
        ),
        parameters="".join(
            PARAMETER_TEMPLATE.format(id=name, value=value)
            for name, value in parameters
        ),
        reactions="".join(
            REACTION_TEMPLATE.format(
                id=name,
                reactants="".join(
                    SPECIES_REFERENCE_TEMPLATE.format(id=item) for item in reactants
                ),
                products="".join(
                    SPECIES_REFERENCE_TEMPLATE.format(id=item) for item in products
                ),
                factors="".join(_factor(item) for item in factors),
            )
            for name, reactants, products, factors in reactions
        ),
    )
    (directory / f"{case_id}-sbml-l3v2.xml").write_text(text, encoding="utf-8")
    (directory / f"{case_id}-settings.txt").write_text(
        "".join(f"{key}: {value}\n" for key, value in settings.items()),
        encoding="utf-8",
    )
    (directory / f"{case_id}-results.csv").write_text(results, encoding="utf-8")


def _decay_reference(initial: float, rate: float, times: np.ndarray) -> list[list[str]]:
    """Published deterministic trajectory of a first-order decay."""

    rows = [["time", "S1", "S2"]]
    for time in times:
        remaining = initial * math.exp(-rate * time)
        rows.append(
            [
                f"{time:.17g}",
                f"{remaining:.17g}",
                f"{initial - remaining:.17g}",
            ]
        )
    return rows


def _csv(rows: list[list[str]]) -> str:
    return "".join(",".join(row) + "\n" for row in rows)


def _boundary_reference(
    initial: float, rate: float, times: np.ndarray
) -> list[list[str]]:
    """Published deterministic trajectory when the reactant is a boundary species.

    A boundary species keeps its amount, so the product grows at the constant
    rate ``rate * initial``.
    """

    rows = [["time", "S1", "S2"]]
    for time in times:
        rows.append(
            [
                f"{time:.17g}",
                f"{initial:.17g}",
                f"{rate * initial * time:.17g}",
            ]
        )
    return rows


@pytest.fixture(scope="module")
def mini_suite(tmp_path_factory) -> Path:
    """A four-case synthetic suite in the layout the sweep expects."""

    root = tmp_path_factory.mktemp("stochastic-consistency-suite")
    cases = root / "cases" / "semantic"
    times = np.linspace(0.0, 10.0, 51)

    # 10001: a linear first-order decay with a whole-molecule population.  The
    # stochastic reading must agree with the deterministic one.
    _write_case(
        cases / "10001",
        "10001",
        species=[("S1", 100.0, False), ("S2", 0.0, False)],
        parameters=[("k", 0.5)],
        reactions=[("r1", ["S1"], ["S2"], ["c", "k", "S1"])],
        settings={
            "start": "0",
            "duration": "10",
            "steps": "50",
            "variables": "S1, S2",
            "absolute": "1.000000e-006",
            "relative": "0.0001",
            "amount": "S1, S2",
            "concentration": "",
        },
        results=_csv(_decay_reference(100.0, 0.5, times)),
    )

    # 10002: a bimolecular reaction.  Its propensity is second order, so the
    # ensemble mean does not satisfy the deterministic ODE and the case is not
    # comparable by construction.
    _write_case(
        cases / "10002",
        "10002",
        species=[("A", 10.0, False), ("B", 8.0, False), ("C", 0.0, False)],
        parameters=[("k", 0.1)],
        reactions=[("r1", ["A", "B"], ["C"], ["c", "k", "A", "B"])],
        settings={
            "start": "0",
            "duration": "10",
            "steps": "50",
            "variables": "A, B, C",
            "absolute": "1.000000e-006",
            "relative": "0.0001",
            "amount": "A, B, C",
            "concentration": "",
        },
        results=_csv(
            [["time", "A", "B", "C"]] + [[f"{t:.17g}", "10", "8", "0"] for t in times]
        ),
    )

    # 10003: the same linear decay, but with a fractional initial population.
    # A discrete stochastic process cannot represent that state.
    _write_case(
        cases / "10003",
        "10003",
        species=[("S1", 0.5, False), ("S2", 0.0, False)],
        parameters=[("k", 0.5)],
        reactions=[("r1", ["S1"], ["S2"], ["c", "k", "S1"])],
        settings={
            "start": "0",
            "duration": "10",
            "steps": "50",
            "variables": "S1, S2",
            "absolute": "1.000000e-006",
            "relative": "0.0001",
            "amount": "S1, S2",
            "concentration": "",
        },
        results=_csv(_decay_reference(0.5, 0.5, times)),
    )

    # 10004: a boundary species.  The deterministic reading keeps it fixed;
    # the direct SSA does not, so the two readings disagree.
    _write_case(
        cases / "10004",
        "10004",
        species=[("S1", 100.0, True), ("S2", 0.0, False)],
        parameters=[("k", 0.5)],
        reactions=[("r1", ["S1"], ["S2"], ["c", "k", "S1"])],
        settings={
            "start": "0",
            "duration": "10",
            "steps": "50",
            "variables": "S1, S2",
            "absolute": "1.000000e-006",
            "relative": "0.0001",
            "amount": "S1, S2",
            "concentration": "",
        },
        results=_csv(_boundary_reference(100.0, 0.5, times)),
    )
    # 10005: a source reaction that produces no network reaction.  A rule
    # whose pattern does not name a molecule type yields a network with zero
    # reactions; the two readings then agree trivially, which must never be
    # reported as agreement.
    _write_case(
        cases / "10005",
        "10005",
        species=[("A", 1.0, False), ("B", 1.0, False)],
        parameters=[("k", 1.0)],
        reactions=[("r1", ["A", "B"], ["A", "B"], ["c", "k"])],
        settings={
            "start": "0",
            "duration": "10",
            "steps": "50",
            "variables": "A, B",
            "absolute": "1.000000e-006",
            "relative": "0.0001",
            "amount": "A, B",
            "concentration": "",
        },
        results=_csv([["time", "A", "B"]] + [[f"{t:.17g}", "1", "1"] for t in times]),
    )
    return root


@pytest.fixture(scope="module")
def sweep_report(mini_suite, tmp_path_factory) -> dict:
    report_path = (
        tmp_path_factory.mktemp("stochastic-consistency-report") / "report.json"
    )
    exit_code = main(
        [
            "--suite-dir",
            str(mini_suite),
            "--categories",
            "semantic",
            "--batch-size",
            "800",
            "--seed-base",
            str(DEFAULT_SEED_BASE),
            "--gpu-cpu-parity-cases",
            "0",
            "--json",
            str(report_path),
        ]
    )
    assert exit_code == 0
    return json.loads(report_path.read_text(encoding="utf-8"))


def _case(report: dict, case_id: str) -> dict:
    matches = [record for record in report["cases"] if record["id"] == case_id]
    assert len(matches) == 1, f"case {case_id} missing from the report"
    return matches[0]


def test_sweep_reports_every_case(sweep_report):
    assert {record["id"] for record in sweep_report["cases"]} == {
        "10001",
        "10002",
        "10003",
        "10004",
        "10005",
    }
    assert sweep_report["budget"]["batch_size"] == 800
    assert sweep_report["budget"]["seed_base"] == DEFAULT_SEED_BASE
    assert sweep_report["budget"]["k_sigma"] > 0


def test_a_rule_that_produced_no_reaction_is_a_finding(sweep_report):
    """A network with no reaction must never be reported as agreement.

    A rule whose pattern does not name a molecule type parses without error
    but yields a network with zero reactions; every sampler then reports zero
    events and a flat trajectory, which looks like a working "no
    disagreement" result rather than a broken model.
    """

    record = _case(sweep_report, "10005")
    assert record["status"] != "consistent"
    assert record["status"] == "not_comparable", record.get("reason")
    assert "no_reaction_produced" in record["findings"]
    assert record["network"]["reactions"] == 0
    assert any(entry["id"] == "10005" for entry in sweep_report["conversion_findings"])


def test_linear_decay_is_consistent(sweep_report):
    """A first-order decay: the ensemble mean must track the published curve."""

    record = _case(sweep_report, "10001")
    assert record["status"] == "consistent", record.get("reason")
    assert record["network"]["linear"] is True
    assert record["comparison"]["decisive_violations"] == 0
    # The reference is the published one, and it is independent of BNG3.
    assert record["reference"]["kind"] == "official-deterministic"
    assert record["reference"]["independent"] is True


def test_bimolecular_case_is_not_comparable(sweep_report):
    """A second-order propensity: not a failure, not comparable."""

    record = _case(sweep_report, "10002")
    assert record["status"] == "not_comparable", record.get("reason")
    assert record["network"]["linear"] is False
    assert "not comparable by construction" in record["reason"]


def test_fractional_population_is_not_comparable(sweep_report):
    """A fractional initial population has no discrete stochastic reading."""

    record = _case(sweep_report, "10003")
    assert record["status"] == "not_comparable", record.get("reason")
    assert record["network"]["representable"] is False
    assert "fractional" in record["reason"]


def test_boundary_species_disagreement_is_reported(sweep_report):
    """The direct SSA does not honour a constant (boundary) seed species.

    The deterministic reading keeps the boundary species fixed and the
    stochastic reading consumes it, so the case must be reported as an
    inconsistency with the corresponding mechanism -- never as agreement.
    """

    record = _case(sweep_report, "10004")
    assert record["status"] == "inconsistent", record.get("reason")
    assert "constant-species-not-honoured-by-the-ssa" in record["mechanisms"]
    assert record["comparison"]["decisive_violations"] > 0


def test_no_case_is_reported_as_a_failure_outside_the_taxonomy(sweep_report):
    allowed = {
        "consistent",
        "inconsistent",
        "not_comparable",
        "no_valid_propensity",
        "unsupported",
        "error",
    }
    for record in sweep_report["cases"]:
        assert record["status"] in allowed
        if record["status"] in {"consistent", "inconsistent"}:
            assert record.get("comparison"), "a compared case needs its numbers"


def test_the_sweep_uses_the_reproducible_single_worker_pool(sweep_report):
    """The recorded seed policy has to determine the numbers.

    The multi-worker CPU batch pool shares one ``OdeIntegrator`` across its
    threads and the SSA path writes that integrator's observable scratch when a
    model has a state-dependent rate law, so the multi-worker result is not
    bit-reproducible.  The sweep therefore runs the single-worker pool.
    """

    assert sweep_report["budget"]["cpu_threads"] == 1


def test_statistical_criterion_uses_the_ensemble_standard_error():
    """The band is the ensemble standard error, not a fixed tolerance."""

    reference = np.linspace(10.0, 5.0, 11)
    mean = reference.copy()
    sd = np.full(11, 1.0)
    batch_size = 100

    inside = _compare_trace(
        mean,
        sd,
        reference,
        batch_size=batch_size,
        k_sigma=5.0,
        absolute_tolerance=0.0,
        relative_tolerance=0.0,
    )
    assert inside["violations"] == 0

    # A deviation of four standard errors of the mean stays inside the band.
    inside = _compare_trace(
        mean + 4.0 / math.sqrt(batch_size),
        sd,
        reference,
        batch_size=batch_size,
        k_sigma=5.0,
        absolute_tolerance=0.0,
        relative_tolerance=0.0,
    )
    assert inside["violations"] == 0
    assert inside["max_abs_z"] == pytest.approx(4.0)

    # A deviation of ten standard errors of the mean leaves it.
    outside = _compare_trace(
        mean + 10.0 / math.sqrt(batch_size),
        sd,
        reference,
        batch_size=batch_size,
        k_sigma=5.0,
        absolute_tolerance=0.0,
        relative_tolerance=0.0,
    )
    assert outside["violations"] == 11
    assert outside["max_abs_z"] == pytest.approx(10.0)
