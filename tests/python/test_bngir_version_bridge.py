"""Version-bridge contract for frozen BNGIR v0.1 and v0.2 fixtures."""

import copy
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
DELAY_LEGACY_FIXTURE = FIXTURES / "v0.1-delayed-bridge.json"
DELAY_STRUCTURAL_FIXTURE = FIXTURES / "v0.2-delayed-bridge.json"


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
        path = native_model.simulate(method="ssa", t_end=end_time, n_steps=1, seed=seed)
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
    assert (
        max(
            abs(observed - expected)
            for observed, expected in zip(empirical_cdf, exact_cdf)
        )
        <= dkw_bound
    )


def _assert_hand_reviewed_delayed_semantics(document):
    model = document["model"]
    assert model["metadata"]["name"] == "bngir_delayed_bridge"
    assert model["parameters"] == [
        {
            "constant_value": 0.5,
            "expression": {"kind": "number", "value": 0.5},
            "id": 0,
            "name": "k",
        },
        {
            "constant_value": 2.0,
            "expression": {"kind": "number", "value": 2.0},
            "id": 1,
            "name": "tau",
        },
    ]
    assert len(model["molecule_types"]) == 2
    assert model["molecule_types"][0]["name"] == "A"
    assert model["molecule_types"][1]["name"] == "B"
    assert model["seeds"][0]["amount"] == {"kind": "number", "value": 10.0}
    assert model["seeds"][0]["pattern"]["molecules"][0]["type"] == "A"
    assert len(model["observables"]) == 2
    assert model["observables"][0]["name"] == "A_obs"
    assert model["observables"][1]["name"] == "B_obs"

    rule = model["rules"][0]
    assert rule["label"] == "delayed_decay:"
    assert rule["delay"] == {
        "kind": "parameter_ref",
        "symbol": {"index": 1, "kind": "parameter"},
    }
    assert rule["forward"]["rate"] == {
        "expression": {
            "kind": "parameter_ref",
            "symbol": {"index": 0, "kind": "parameter"},
        },
        "kind": 0,
    }
    assert rule["forward"]["reactants"][0]["molecules"][0]["type"] == "A"
    assert rule["forward"]["products"][0]["molecules"][0]["type"] == "B"


def test_delayed_rule_v01_migrates_to_v02_and_roundtrips():
    legacy_document = json.loads(DELAY_LEGACY_FIXTURE.read_text(encoding="utf-8"))
    expected_document = json.loads(DELAY_STRUCTURAL_FIXTURE.read_text(encoding="utf-8"))
    jsonschema.validate(legacy_document, _schema("0.1"))
    jsonschema.validate(expected_document, _schema("0.2"))
    _assert_hand_reviewed_delayed_semantics(expected_document)

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


def test_delayed_rule_native_reconstruction_and_analytic_ode_trajectory():
    expected_document = json.loads(DELAY_STRUCTURAL_FIXTURE.read_text(encoding="utf-8"))
    legacy_document = json.loads(DELAY_LEGACY_FIXTURE.read_text(encoding="utf-8"))
    legacy_model = bionetgen.from_bngir(legacy_document)

    native_model = bionetgen.from_bngir(expected_document, native=True)
    assert json.loads(native_model.to_bngir(version="0.2")) == expected_document
    assert bionetgen.semantic_equal(legacy_model, native_model, version="0.2")

    network = native_model.generate_network()
    assert network.generation_converged

    # Derived analytic law from source semantics:
    # A_0 = 10, k = 0.5, tau = 2.0.
    # Initiation consumes A immediately: dA/dt = -k A(t) => A(t) = A_0 * exp(-k*t).
    # Completion yields B at time t + tau:
    # For t < tau: B(t) = 0.
    # For t >= tau: B(t) = A_0 * (1 - exp(-k * (t - tau))).
    # Observation grid t in [0.0, 1.0, 2.0, 3.0, 4.0]:
    # - t=1.0: immediate reaction would give B=3.93469, but delayed reaction gives B=0.0.
    #   Consumption at initiation gives A(1.0) = 10*exp(-0.5) = 6.06531 < 10 (distinguishing consuming from NonConsuming).
    # - t=2.0 (delay horizon): A(2.0) = 10*exp(-1.0) = 3.67879, B(2.0) = 0.0.
    # - t=3.0 (first epoch after completions): A(3.0) = 10*exp(-1.5) = 2.23130, B(3.0) = 10*(1 - exp(-0.5)) = 3.93469.
    # - t=4.0: A(4.0) = 10*exp(-2.0) = 1.35335, B(4.0) = 10*(1 - exp(-1.0)) = 6.32121.
    ode = native_model.simulate(method="ode", t_end=4.0, n_steps=4)
    for time, row in zip(ode.time, ode.concentrations):
        values = dict(zip(network.species_names, row))
        expected_a = 10.0 * math.exp(-0.5 * time)
        expected_b = (
            0.0 if time <= 2.0 else 10.0 * (1.0 - math.exp(-0.5 * (time - 2.0)))
        )
        assert values["A()"] == pytest.approx(expected_a, abs=1e-6)
        assert values["B()"] == pytest.approx(expected_b, abs=1e-6)

    # Also verify the v0.2 BNGL text round trip route:
    text_restored_model = bionetgen.from_bngir(expected_document, native=False)
    ode_text = text_restored_model.simulate(method="ode", t_end=4.0, n_steps=4)
    for time, row in zip(ode_text.time, ode_text.concentrations):
        values = dict(zip(network.species_names, row))
        expected_a = 10.0 * math.exp(-0.5 * time)
        expected_b = (
            0.0 if time <= 2.0 else 10.0 * (1.0 - math.exp(-0.5 * (time - 2.0)))
        )
        assert values["A()"] == pytest.approx(expected_a, abs=1e-6)
        assert values["B()"] == pytest.approx(expected_b, abs=1e-6)


def test_delayed_rule_wire_mutation_sensitivity():
    expected_document = json.loads(DELAY_STRUCTURAL_FIXTURE.read_text(encoding="utf-8"))

    # Valid execution-changing wire mutation: mutate tau from 2.0 to 3.0 on wire
    # while keeping rate k=0.5 fixed.
    mutated = copy.deepcopy(expected_document)
    mutated["model"]["parameters"][1]["constant_value"] = 3.0
    mutated["model"]["parameters"][1]["expression"]["value"] = 3.0

    mutated_model = bionetgen.from_bngir(mutated, native=True)
    mutated_ode = mutated_model.simulate(method="ode", t_end=4.0, n_steps=4)

    # A(t) trajectory must remain invariant under delay-only change.
    # B(t) must shift by exactly Delta tau = 1.0:
    # At t=3.0, B is 0.0 (unmutated was ~3.93469).
    # At t=4.0, B is 10*(1 - exp(-0.5)) = ~3.93469 (unmutated was ~6.32121).
    for time, row in zip(mutated_ode.time, mutated_ode.concentrations):
        species_map = dict(zip(["A()", "B()"], row))
        expected_a = 10.0 * math.exp(-0.5 * time)
        expected_b = (
            0.0 if time <= 3.0 else 10.0 * (1.0 - math.exp(-0.5 * (time - 3.0)))
        )
        assert species_map["A()"] == pytest.approx(expected_a, abs=1e-6)
        assert species_map["B()"] == pytest.approx(expected_b, abs=1e-6)

    # Comparison detects difference and rejects unmutated trajectory:
    orig_b_at_3 = 10.0 * (1.0 - math.exp(-0.5 * (3.0 - 2.0)))
    assert mutated_ode.concentrations[3][1] == pytest.approx(0.0, abs=1e-6)
    assert abs(mutated_ode.concentrations[3][1] - orig_b_at_3) > 3.9

    # Mutation on rate k from 0.5 to 1.0 (keeping tau=2.0 fixed):
    mutated_rate = copy.deepcopy(expected_document)
    mutated_rate["model"]["parameters"][0]["constant_value"] = 1.0
    mutated_rate["model"]["parameters"][0]["expression"]["value"] = 1.0
    m_rate_model = bionetgen.from_bngir(mutated_rate, native=True)
    m_rate_ode = m_rate_model.simulate(method="ode", t_end=4.0, n_steps=4)
    # A(1.0) = 10*exp(-1.0) ~ 3.67879 (was 6.06531)
    # B(3.0) = 10*(1 - exp(-1.0)) ~ 6.32121 (was 3.93469)
    assert m_rate_ode.concentrations[1][0] == pytest.approx(
        10.0 * math.exp(-1.0), abs=1e-6
    )
    assert m_rate_ode.concentrations[3][1] == pytest.approx(
        10.0 * (1.0 - math.exp(-1.0)), abs=1e-6
    )

    # Mutation on legacy v0.1 wire document (independently authored input):
    legacy_doc = json.loads(DELAY_LEGACY_FIXTURE.read_text(encoding="utf-8"))
    mutated_v1 = copy.deepcopy(legacy_doc)
    mutated_v1["model"]["parameters"][1]["expression"] = "3.0"
    m_v1_model = bionetgen.from_bngir(mutated_v1)
    migrated_v2 = json.loads(bionetgen.to_bngir(m_v1_model, version="0.2"))
    m_v1_native = bionetgen.from_bngir(migrated_v2, native=True)
    m_v1_ode = m_v1_native.simulate(method="ode", t_end=4.0, n_steps=4)
    assert m_v1_ode.concentrations[3][1] == pytest.approx(0.0, abs=1e-6)
    assert m_v1_ode.concentrations[4][1] == pytest.approx(
        10.0 * (1.0 - math.exp(-0.5)), abs=1e-6
    )


def test_delayed_rule_protocol_actions_and_continuation_guard():
    expected_document = json.loads(DELAY_STRUCTURAL_FIXTURE.read_text(encoding="utf-8"))
    native_model = bionetgen.from_bngir(expected_document, native=True)

    # Re-parameterization action on reconstructed native model:
    native_model.set_parameter("tau", 3.0)
    re_sim = native_model.simulate(method="ode", t_end=4.0, n_steps=4)
    assert re_sim.concentrations[3][1] == pytest.approx(0.0, abs=1e-6)
    assert re_sim.concentrations[4][1] == pytest.approx(
        10.0 * (1.0 - math.exp(-0.5)), abs=1e-6
    )

    # Invariant check: continuation leg fails closed if delay is altered mid-flight.
    # Model document specifies static structure with quiescent history prior to t=0.
    # Live simulation continuation requires carrying active pending delays or preserving delay constancy.
    native_model.set_parameter("tau", 2.0)
    native_model.simulate(method="ode", t_end=1.0, n_steps=2)
    native_model.set_parameter("tau", 5.0)
    with pytest.raises(RuntimeError, match="delays to remain constant"):
        native_model.simulate(
            method="ode",
            t_start=1.0,
            t_end=3.0,
            n_steps=4,
            continue_simulation=True,
        )
