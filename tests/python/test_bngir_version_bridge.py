"""Version-bridge contract for frozen BNGIR v0.1 and v0.2 fixtures."""

import json
import math
from fractions import Fraction
from pathlib import Path

import jsonschema
import pytest

import bionetgen

from _extdep import require_extension

require_extension()


ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "bngir"
LEGACY_FIXTURE = FIXTURES / "v0.1-version-bridge.json"
STRUCTURAL_FIXTURE = FIXTURES / "v0.2-version-bridge.json"


def _schema(version):
    path = ROOT / "provenance" / "schemas" / f"bngir-{version}.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _state_value(pattern):
    return pattern["molecules"][0]["sites"][0]["state"]["value"]


def _assert_hand_reviewed_semantics(document):
    model = document["model"]
    assert model["metadata"]["name"] == "bngir_version_bridge"
    assert model["parameters"] == [
        {
            "constant_value": 0.1,
            "expression": {"kind": "number", "value": 0.1},
            "id": 0,
            "name": "k",
        }
    ]
    assert model["molecule_types"][0]["components"] == [
        {"index": 0, "name": "x", "states": ["u", "p"]}
    ]
    assert model["seeds"][0]["amount"] == {"kind": "number", "value": 10.0}
    assert model["seeds"][0]["pattern"]["molecules"][0]["type"] == "A"
    assert _state_value(model["seeds"][0]["pattern"]) == "u"

    rule = model["rules"][0]
    assert rule["label"] == "convert:"
    assert rule["forward"]["rate"] == {
        "expression": {
            "kind": "parameter_ref",
            "symbol": {"index": 0, "kind": "parameter"},
        },
        "kind": 0,
    }
    assert _state_value(rule["forward"]["reactants"][0]) == "u"
    assert _state_value(rule["forward"]["products"][0]) == "p"
    assert rule["forward"]["mutations"] == [
        {
            "kind": "change_state",
            "source": {"molecule": 0, "pattern": 0, "side": "reactant", "site": 0},
            "state": "p",
            "state_index": 1,
        }
    ]


def test_frozen_v01_migrates_to_pinned_schema_valid_v02_and_round_trips():
    legacy_document = json.loads(LEGACY_FIXTURE.read_text(encoding="utf-8"))
    expected_document = json.loads(STRUCTURAL_FIXTURE.read_text(encoding="utf-8"))
    jsonschema.validate(legacy_document, _schema("0.1"))
    jsonschema.validate(expected_document, _schema("0.2"))
    _assert_hand_reviewed_semantics(expected_document)
    expected_wire = json.dumps(
        expected_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    legacy_model = bionetgen.from_bngir(legacy_document)
    first_export = bionetgen.to_bngir(legacy_model, version="0.2").encode("utf-8")
    second_export = bionetgen.to_bngir(legacy_model, version="0.2").encode("utf-8")

    assert first_export == expected_wire
    assert second_export == expected_wire
    structural_document = json.loads(first_export)
    jsonschema.validate(structural_document, _schema("0.2"))

    restored_model = bionetgen.from_bngir(expected_document)
    assert bionetgen.semantic_equal(legacy_model, restored_model, version="0.2")
    restored_export = bionetgen.to_bngir(restored_model, version="0.2").encode("utf-8")
    assert restored_export == expected_wire
    reverse_export = json.loads(bionetgen.to_bngir(restored_model, version="0.1"))
    jsonschema.validate(reverse_export, _schema("0.1"))
    reverse_model = bionetgen.from_bngir(reverse_export)
    assert bionetgen.semantic_equal(restored_model, reverse_model, version="0.1")

    # Independently enumerate the complete reachable CTMC for the frozen
    # state-transition fixture. State i has i phosphorylated and 10-i
    # unphosphorylated molecules; its only outgoing hazard is (10-i)/10.
    reachable_states = tuple(
        (10 - phosphorylated, phosphorylated) for phosphorylated in range(11)
    )
    exact_edges = {
        (reachable_states[i], reachable_states[i + 1]): Fraction(10 - i, 10)
        for i in range(10)
    }
    assert len(reachable_states) == 11
    assert exact_edges[(reachable_states[0], reachable_states[1])] == Fraction(10, 10)

    native_model = bionetgen.from_bngir(expected_document, native=True)
    assert json.loads(native_model.to_bngir(version="0.2")) == structural_document
    assert bionetgen.semantic_equal(legacy_model, native_model, version="0.2")
    network = native_model.generate_network()
    assert network.generation_converged

    ode = native_model.simulate(method="ode", t_end=2.0, n_steps=10)
    for time, row in zip(ode.time, ode.concentrations):
        values = dict(zip(network.species_names, row))
        expected_p = 10.0 * (1.0 - math.exp(-0.1 * time))
        assert values["A(x~u)"] == pytest.approx(10.0 - expected_p, abs=1e-7)
        assert values["A(x~p)"] == pytest.approx(expected_p, abs=1e-7)

    # Exercise exact conserved-state invariants on a single native SSA path.
    ssa = native_model.simulate(method="ssa", t_end=1.0, n_steps=5, seed=20261102)
    for row in ssa.concentrations:
        assert all(0.0 <= amount <= 10.0 and amount.is_integer() for amount in row)
        assert sum(row) == 10.0

    # The independent source law is ten independent A->P conversion clocks at
    # rate 1/10. At t=2, the phosphorylated count is Binomial(10, 1-exp(-0.2)).
    # Use a fixed bank of 512 fresh SSA seeds and a 1% DKW CDF envelope, whose
    # simultaneous bound is sqrt(log(2/alpha)/(2N)).
    replicate_count = 512
    alpha = 0.01
    end_time = 2.0
    conversion_probability = 1.0 - math.exp(-0.1 * end_time)
    sampled_counts = []
    for seed in range(1, replicate_count + 1):
        path = native_model.simulate(
            method="ssa", t_end=end_time, n_steps=1, seed=seed
        )
        row = path.concentrations[-1]
        values = dict(zip(network.species_names, row))
        assert all(0.0 <= amount <= 10.0 and amount.is_integer() for amount in row)
        assert sum(row) == 10.0
        sampled_counts.append(int(values["A(x~p)"]))

    empirical_cdf = [
        sum(value <= count for value in sampled_counts) / replicate_count
        for count in range(10)
    ]
    exact_cdf = [
        sum(
            math.comb(10, value)
            * conversion_probability**value
            * (1.0 - conversion_probability) ** (10 - value)
            for value in range(count + 1)
        )
        for count in range(10)
    ]
    dkw_bound = math.sqrt(math.log(2.0 / alpha) / (2 * replicate_count))
    assert max(
        abs(observed - expected)
        for observed, expected in zip(empirical_cdf, exact_cdf)
    ) <= dkw_bound
