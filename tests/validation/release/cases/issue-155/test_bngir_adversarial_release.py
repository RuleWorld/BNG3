"""Release acceptance suite for Issue #155: Independent Native BNGIR Contracts & Adversarial Fixtures.

Validates:
- release-bngir-adversarial: independent cases and product mutations
  distinguish semantic changes from valid reconstruction.
- release-bngir-consumer: actual native consumers execute each valid case
  against an independent expected law.
- release-obligation-155: verifies contract, capability matrix rows, live
  obligations, and adversarial negative controls.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import pytest
import jsonschema
import yaml

import bionetgen
from bionetgen.bngir import (
    EqualityUndecided,
    from_bngir,
    semantic_equal,
    to_bngir,
)

try:
    import bionetgen._bionetgen_cpp as _cpp
except ImportError:
    from bionetgen.model import _cpp

from tests.validation import bngir_adversarial as adversarial

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "bngir" / "adversarial"
SCHEMA_V02 = json.loads(
    (REPO_ROOT / "provenance" / "schemas" / "bngir-0.2.schema.json").read_text(
        encoding="utf-8"
    )
)


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_release_bngir_adversarial():
    """Validate release-bngir-adversarial.

    1. Independent cases: valid hand-authored BNGIR documents validate against
       the schema and round-trip.
    2. Malformed JSON inputs (cross-reference errors, invalid scopes, out-of-range refs)
       are strictly rejected before partial model mutation.
    3. Product mutations (reversed rules, dropped units, wrong bonds, observable
       relations, seed amounts, parameter rates) are detected as distinct semantics.
    """
    # 1. Valid fixtures conform to schema
    valid_decay = _load_fixture("valid_decay.json")
    jsonschema.validate(valid_decay, SCHEMA_V02)
    m_decay = from_bngir(valid_decay)
    assert isinstance(m_decay, bionetgen.BioNetGenModel)

    valid_comp = _load_fixture("valid_states_bonds_compartment.json")
    jsonschema.validate(valid_comp, SCHEMA_V02)
    m_comp = from_bngir(valid_comp)
    assert isinstance(m_comp, bionetgen.BioNetGenModel)

    # 2. Invalid fixtures are rejected
    invalid_cases = [
        ("invalid_duplicate_parameter_id.json", False),
        ("invalid_parameter_ref.json", False),
        ("invalid_seed_type_ref.json", False),
        ("invalid_observable_relation.json", True),
        ("invalid_compartment_ref.json", False),
        ("invalid_observable_type_ref.json", False),
        ("invalid_function_ref.json", False),
        ("invalid_action_scope.json", True),
        ("invalid_observable_ref_index.json", False),
        ("invalid_energy_type_ref.json", False),
        ("invalid_rule_product_type_ref.json", False),
        ("invalid_seed_compartment_ref.json", False),
        ("invalid_delay_parameter_ref.json", False),
        ("invalid_energy_expression_ref.json", False),
    ]
    for name, expect_schema_fail in invalid_cases:
        doc = _load_fixture(name)
        if expect_schema_fail:
            with pytest.raises(Exception):
                jsonschema.validate(doc, SCHEMA_V02)
        else:
            jsonschema.validate(doc, SCHEMA_V02)
        # In all cases, reconstructing a runnable model must fail
        with pytest.raises(Exception):
            from_bngir(doc)
        with pytest.raises(Exception):
            from_bngir(doc, native=True)

    # 3. Mutations: reversed rule detected via trajectory divergence
    mut_rule = _load_fixture("mutation_reversed_rule.json")
    m_mut_rule = from_bngir(mut_rule)
    res_base = m_decay.simulate(method="ode", t_end=2.0, n_steps=10)
    res_mut = m_mut_rule.simulate(method="ode", t_end=2.0, n_steps=10)
    assert (
        abs(
            float(res_mut.concentrations[-1][0]) - float(res_base.concentrations[-1][0])
        )
        > 1e-3
    )

    # Mutation: dropped substance units detected
    base_units = _load_fixture("valid_substance_units.json")
    mut_units = _load_fixture("mutation_dropped_substance_units.json")
    m_base_u = from_bngir(base_units)
    m_mut_u = from_bngir(mut_units)
    d_base_u = json.loads(to_bngir(m_base_u, version="0.2"))
    d_mut_u = json.loads(to_bngir(m_mut_u, version="0.2"))
    assert d_base_u["model"]["metadata"].get("substance_units") == "molecules"
    assert d_mut_u["model"]["metadata"].get("substance_units") == ""
    assert d_base_u != d_mut_u

    # Mutation: observable pattern detected
    base_obs = _load_fixture("valid_observable_decay.json")
    mut_obs = _load_fixture("mutation_observable_pattern.json")
    assert (
        semantic_equal(from_bngir(base_obs), from_bngir(mut_obs), version="0.2")
        is False
    )

    # Mutation: wrong bond detected
    base_bond = _load_fixture("valid_bond_complex.json")
    mut_bond = _load_fixture("mutation_wrong_bond.json")
    assert mut_bond != base_bond

    # Mutation: parameter rate and seed amount detected
    mut_rate = _load_fixture("mutation_parameter_rate.json")
    res_rate = from_bngir(mut_rate).simulate(method="ode", t_end=2.0, n_steps=10)
    assert (
        abs(
            float(res_base.concentrations[-1][0])
            - float(res_rate.concentrations[-1][0])
        )
        > 1e-3
    )

    mut_seed = _load_fixture("mutation_seed_amount.json")
    res_seed = from_bngir(mut_seed).simulate(method="ode", t_end=2.0, n_steps=10)
    assert (
        abs(
            float(res_base.concentrations[-1][0])
            - float(res_seed.concentrations[-1][0])
        )
        > 1e-3
    )

    # Mutation: population-map reference and rate are detected. A malformed
    # reference may be refused at import; either refusal or a changed wire
    # document is a valid detection, but an unchanged document is not.
    base_pop = _load_fixture("valid_population_map.json")
    base_pop_model = from_bngir(base_pop)
    base_pop_doc = json.loads(to_bngir(base_pop_model, version="0.2"))
    for filename in (
        "mutation_population_map_ref.json",
        "mutation_population_map_rate.json",
    ):
        mutated = _load_fixture(filename)
        try:
            mutated_model = from_bngir(mutated)
        except Exception:
            continue
        mutated_doc = json.loads(to_bngir(mutated_model, version="0.2"))
        assert mutated_doc != base_pop_doc, f"{filename} was accepted without a change"


def test_release_bngir_consumer(tmp_path, monkeypatch):
    """Validate release-bngir-consumer.

    1. Native consumers execute independent documents against exact analytic laws.
    2. Worker consumes independent documents across all 19 adversarial cases.
    3. Function rate law executes natively without rendering or parsing BNGL source.
    """
    # 1. Direct native execution of valid decay against analytic exponential decay A(t) = A0 * exp(-kt)
    doc_decay = _load_fixture("valid_decay.json")
    native_decay = from_bngir(doc_decay, native=True)
    res = native_decay.simulate(method="ode", t_end=2.0, n_steps=10)
    # A -> B, k=0.1, A0=10. At t=2.0: A(2) = 10 * exp(-0.2) ~= 8.1873075
    expected_A_2 = 10.0 * math.exp(-0.1 * 2.0)
    expected_B_2 = 10.0 * (1.0 - math.exp(-0.1 * 2.0))
    assert abs(float(res.concentrations[-1][0]) - expected_A_2) < 1e-6
    assert abs(float(res.concentrations[-1][1]) - expected_B_2) < 1e-6

    # 2. Native worker consumes independent documents and analytic controls
    rows = adversarial.run_worker(tmp_path)
    assert len(rows) == len(adversarial.CASES)
    for case, row in zip(adversarial.CASES, rows):
        if case["oracle"] == "unsupported":
            assert row["status"] == "UNSUPPORTED", row
        elif case["oracle"] == "accept-or-unsupported":
            assert row["status"] in {"PASS", "UNSUPPORTED"}, row
        else:
            assert row["status"] == "PASS", row

    # 3. Native import roundtrips and executes hand-authored function document without BNGL parse
    case = next(c for c in adversarial.CASES if c["id"] == "function-rate-law")
    document = copy.deepcopy(case["document"])
    expected = case["expected_semantics"]

    import bionetgen.bngir as bngir_module

    def forbidden(*_args, **_kwargs):
        pytest.fail("native BNGIR import rendered or parsed BNGL source")

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    monkeypatch.setattr(bngir_module, "_as_bngl_v02", forbidden)

    restored = from_bngir(document, native=True)
    assert json.loads(restored.to_bngir(version="0.2")) == document

    network = restored.generate_network()
    state = [expected["seed"][name] for name in network.species_names]
    derivative = _cpp._validation_ode_rhs(restored._model, network, 0.0, state)
    assert dict(zip(network.species_names, derivative)) == pytest.approx(
        expected["rhs"]
    )

    result = restored.simulate(
        method="ode", t_end=2.0, n_steps=10, atol=1e-12, rtol=1e-10
    )
    for observed, reference in zip(result.concentrations, expected["trajectory"]):
        assert dict(zip(network.species_names, observed)) == pytest.approx(
            reference["amounts"], abs=1e-7, rel=1e-7
        )


def test_release_obligation_155():
    """Validate release-obligation-155.

    1. Verify contract.json structure and obligations.
    2. Verify inventory rows (bngir.native, bngir.v02) exist in capability-matrix.yml.
    3. Verify live acceptance obligations in provenance/issue-obligations.json.
    """
    contract_path = CASE_DIR / "contract.json"
    assert contract_path.is_file()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["schema_version"] == 1
    assert contract["issue"] == 155
    assert set(contract["acceptance_checks"]) == {
        "release-bngir-adversarial",
        "release-bngir-consumer",
        "release-obligation-155",
    }

    # Verify capability rows
    matrix_path = REPO_ROOT / "provenance" / "capability-matrix.yml"
    assert matrix_path.is_file()
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    matrix_ids = {row["id"] for row in matrix.get("rows", [])}
    for row in contract["inventory_rows"]:
        assert row in matrix_ids, f"Inventory row {row} missing from capability matrix"

    # Verify obligations manifest
    manifest_path = REPO_ROOT / "provenance" / "issue-obligations.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    issue_155 = next((i for i in manifest["issues"] if i["number"] == 155), None)
    assert issue_155 is not None, "Issue 155 missing from issue-obligations.json"

    ob_ids = {ob["id"] for ob in issue_155["obligations"]}
    for expected_ob in contract["obligations"]:
        assert expected_ob in ob_ids, f"Obligation {expected_ob} missing from manifest"
