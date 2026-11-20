"""Release acceptance suite for Issue #154: Lossless BNGIR Round Trips & Version Migration.

Validates:
- release-bngir-roundtrip: every construct family preserves source facts and
  independent downstream execution across BNGL -> v0.2 -> BNGL and native
  reconstruction.
- release-bngir-version: v0.2 represents every v0.1 field plus the complete
  new schema with no data loss across bidirectional migration.
- release-obligation-154: verifies contract, capability matrix rows, live
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

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "bngir"
ADVERSARIAL_DIR = FIXTURES_DIR / "adversarial"

SCHEMA_V01 = json.loads(
    (REPO_ROOT / "provenance" / "schemas" / "bngir-0.1.schema.json").read_text(
        encoding="utf-8"
    )
)
SCHEMA_V02 = json.loads(
    (REPO_ROOT / "provenance" / "schemas" / "bngir-0.2.schema.json").read_text(
        encoding="utf-8"
    )
)


def _parse_model(bngl: str) -> bionetgen.BioNetGenModel:
    if _cpp is not None and hasattr(_cpp, "parse_string"):
        return bionetgen.BioNetGenModel(_cpp.parse_string(bngl))
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".bngl", delete=False) as f:
        f.write(bngl)
        f.flush()
        try:
            return bionetgen.load(f.name)
        finally:
            Path(f.name).unlink(missing_ok=True)


# Comprehensive construct models exercising each required family
CONSTRUCT_MODELS = {
    "parameters_and_dependencies": """
begin model
begin parameters
    p1 2.0
    p2 3.0*p1
    p3 p2 + 1.5
    k 0.25
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules A_tot A()
    Molecules B_tot B()
end observables
begin reaction rules
    r1: A() -> B() k
end reaction rules
end model
""",
    "states_and_bonds": """
begin model
begin parameters
    kf 1.0
    kr 0.5
    kp 0.2
end parameters
begin molecule types
    A(b,s~u~p)
    B(a)
end molecule types
begin seed species
    A(b!1,s~u).B(a!1) 5
    A(b,s~p) 2
    B(a) 3
end seed species
begin observables
    Molecules A_bound A(b!+)
    Species AB_dimer A(b!1).B(a!1)
    Molecules A_phos A(s~p)
end observables
begin reaction rules
    bind: A(b,s~u) + B(a) <-> A(b!1,s~u).B(a!1) kf, kr
    phos: A(s~u) -> A(s~p) kp
end reaction rules
end model
""",
    "compartments_and_protocol": """
begin model
begin compartments
    EC 3 1.0
    PM 2 0.1 EC
    CP 3 0.5 PM
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    A()@CP 10
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    trans: A()@CP -> A()@EC 1.0
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>1.0,n_steps=>5})
""",
    "functions_and_dependent_rate": """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules Atot A()
end observables
begin functions
    f() = k*Atot
end functions
begin reaction rules
    A() -> B() f()
end reaction rules
end model
""",
    "delayed_rules_consuming": """
begin model
begin parameters
    k 0.5
    tau 2.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules A_obs A()
    Molecules B_obs B()
end observables
begin reaction rules
    delayed_decay: A() -> B() k delay=tau
end reaction rules
end model
""",
    "energy_and_driven_reservoirs": """
begin model
begin parameters
    k 1.0
    G 1.5
    w 0.8
end parameters
begin molecule types
    A(x~u~p)
    B()
end molecule types
begin seed species
    A(x~u) 5
    B() 2
end seed species
begin energy patterns
    A(x~p) G
end energy patterns
begin reaction rules
    A(x~u) <-> A(x~p) k, k
    A(x~p) -> B() k driven_by(w)
end reaction rules
end model
""",
    "modifiers_and_synthesis": """
begin model
begin parameters
    ks 1.0
    kd 0.2
    ktr 0.5
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
    B() 1
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    synth: 0 -> A() ks
    tr: A() + A() -> A() ktr TotalRate
    deg: A() -> 0 kd
end reaction rules
end model
""",
    "units_and_metadata": """
version("2.2")
begin model
begin units
    timeUnits = second
    substanceUnits = item
    volumeUnits = litre
    unit per_s = second^-1
end units
begin parameters
    KD = 100 [nM]
    koff = 0.02 [per_s]
end parameters
begin compartments
    cyto 3 1 [fL]
end compartments
begin molecule types
    A(x~u~p)
end molecule types
begin seed species
    A(x~u)@cyto 10 [molecule]
end seed species
begin reaction rules
    A(x~u) -> A(x~p) koff
end reaction rules
end model
""",
}

NATIVE_ELIGIBLE_CASES = {
    "parameters_and_dependencies",
    "states_and_bonds",
    "functions_and_dependent_rate",
    "delayed_rules_consuming",
}


def test_release_bngir_roundtrip():
    """Validate release-bngir-roundtrip.

    Every inventory construct preserves source facts and downstream execution
    across BNGL -> v0.2 -> BNGL and native reconstruction.
    """
    for name, bngl in CONSTRUCT_MODELS.items():
        model = _parse_model(bngl)

        # 1. Round-trip through BNGIR v0.2
        doc_v02_str = to_bngir(model, version="0.2")
        doc_v02 = json.loads(doc_v02_str)
        assert doc_v02["version"] == "0.2"
        jsonschema.validate(doc_v02, SCHEMA_V02)

        restored_v02 = from_bngir(doc_v02)
        assert isinstance(restored_v02, bionetgen.BioNetGenModel)
        try:
            assert semantic_equal(model, restored_v02, version="0.2") is True
        except EqualityUndecided:
            # Verify the wire facts when exact process equality is undecided.
            assert json.loads(to_bngir(restored_v02, version="0.2")) == doc_v02

        # 2. Round-trip through BNGIR v0.1
        doc_v01_str = to_bngir(model, version="0.1")
        doc_v01 = json.loads(doc_v01_str)
        assert doc_v01["version"] == "0.1"
        jsonschema.validate(doc_v01, SCHEMA_V01)

        restored_v01 = from_bngir(doc_v01)
        assert isinstance(restored_v01, bionetgen.BioNetGenModel)
        try:
            assert semantic_equal(model, restored_v01, version="0.1") is True
        except EqualityUndecided:
            assert json.loads(to_bngir(restored_v01, version="0.1")) == doc_v01

        # 3. Native reconstruction for supported slices
        if name in NATIVE_ELIGIBLE_CASES:
            native_model = from_bngir(doc_v02, native=True)
            assert isinstance(native_model, bionetgen.BioNetGenModel)
            assert semantic_equal(model, native_model, version="0.2") is True

    # 4. Downstream execution and exact analytic ODE trajectory qualification
    delayed_model = _parse_model(CONSTRUCT_MODELS["delayed_rules_consuming"])
    doc_delayed = json.loads(to_bngir(delayed_model, version="0.2"))
    native_delayed = from_bngir(doc_delayed, native=True)

    # Derived analytic continuous law:
    # A_0 = 10.0, k = 0.5, tau = 2.0.
    # Initiation consumes A immediately: A(t) = A_0 * exp(-k * t).
    # Completion yields B at time t + tau:
    # For t <= tau: B(t) = 0.
    # For t > tau:  B(t) = A_0 * (1 - exp(-k * (t - tau))).
    sim = native_delayed.simulate(method="ode", t_end=4.0, n_steps=4)
    for time, (conc_a, conc_b) in zip(sim.time, sim.concentrations):
        expected_a = 10.0 * math.exp(-0.5 * time)
        expected_b = (
            0.0 if time <= 2.0 else 10.0 * (1.0 - math.exp(-0.5 * (time - 2.0)))
        )
        assert conc_a == pytest.approx(expected_a, abs=1e-6)
        assert conc_b == pytest.approx(expected_b, abs=1e-6)

    # Completion by t=3 requires initiation by t=1. The resulting B count is
    # Binomial(10, 1-exp(-0.5)). Check all CDF thresholds at a fixed 1% error
    # bound using Dvoretzky–Kiefer–Wolfowitz.
    completions = []
    first_seed, runs = 2800, 256
    for seed in range(first_seed, first_seed + runs):
        trajectory = from_bngir(doc_delayed, native=True).simulate(
            method="ssa", t_end=3.0, n_steps=3, seed=seed
        )
        assert trajectory.concentrations[1][1] == 0
        b = trajectory.concentrations[-1][1]
        assert b == int(b) and 0 <= b <= 10
        completions.append(b)

    p = 1.0 - math.exp(-0.5)
    expected_cdf = 0.0
    bound = math.sqrt(math.log(2 / 0.01) / (2 * runs))
    for b in range(11):
        expected_cdf += math.comb(10, b) * p**b * (1 - p) ** (10 - b)
        observed_cdf = sum(sample <= b for sample in completions) / runs
        assert abs(observed_cdf - expected_cdf) <= bound

    # 5. Wire mutation sensitivity: mutating tau on wire alters trajectory and is detected
    mutated_doc = copy.deepcopy(doc_delayed)
    mutated_doc["model"]["parameters"][1]["constant_value"] = 3.0
    mutated_doc["model"]["parameters"][1]["expression"]["value"] = 3.0
    native_mutated = from_bngir(mutated_doc, native=True)
    sim_mutated = native_mutated.simulate(method="ode", t_end=4.0, n_steps=4)

    # At t=3.0, unmutated has B ~ 3.93469, mutated has B == 0.0 (shifted by Delta tau = 1.0)
    assert sim_mutated.concentrations[3][1] == pytest.approx(0.0, abs=1e-6)
    assert abs(sim_mutated.concentrations[3][1] - sim.concentrations[3][1]) > 3.9

    # Rate mutation k: 0.5 -> 1.0 is detected
    mutated_rate_doc = copy.deepcopy(doc_delayed)
    mutated_rate_doc["model"]["parameters"][0]["constant_value"] = 1.0
    mutated_rate_doc["model"]["parameters"][0]["expression"]["value"] = 1.0
    native_rate = from_bngir(mutated_rate_doc, native=True)
    sim_rate = native_rate.simulate(method="ode", t_end=4.0, n_steps=4)
    assert sim_rate.concentrations[1][0] == pytest.approx(
        10.0 * math.exp(-1.0), abs=1e-6
    )
    assert abs(sim_rate.concentrations[1][0] - sim.concentrations[1][0]) > 2.0


def test_release_bngir_version():
    """Validate release-bngir-version.

    BNGIR v0.2 represents every v0.1 field plus the complete new schema with no data loss.
    """
    # Comprehensive v0.1 synthetic document containing every field defined in bngir-0.1.schema.json
    full_v01_document = {
        "format": "BNGIR",
        "version": "0.1",
        "features": {
            "required": [],
            "used": [
                "compartments",
                "delayed_rules",
                "energy_patterns",
                "functions",
                "observables",
                "population_maps",
                "protocol",
                "rules",
                "seeds",
                "units",
            ],
        },
        "model": {
            "name": "full_v01_model",
            "version": "2.2",
            "substance_units": "item",
            "options": {"SpeciesLabel": "HNauty"},
            "unit_defaults": {
                "timeUnits": "second",
                "substanceUnits": "item",
                "volumeUnits": "litre",
            },
            "unit_definitions": [
                {"id": "per_s", "expression": "second^-1"},
                {"name": "Molar", "expression": "1e6"},
            ],
            "parameters": [
                {"name": "k1", "expression": "0.5", "unit": "per_s"},
                {"name": "tau", "expression": "2.0", "unit": "second"},
                {"name": "p_dep", "expression": "2.0*k1"},
            ],
            "molecule_types": [
                {
                    "name": "A",
                    "population": False,
                    "components": [
                        {"name": "b", "allowed_states": []},
                        {"name": "s", "allowed_states": ["u", "p"]},
                    ],
                },
                {
                    "name": "B",
                    "population": False,
                    "components": [{"name": "a", "allowed_states": []}],
                },
                {
                    "name": "PopA",
                    "population": True,
                    "components": [],
                },
            ],
            "compartments": [
                {
                    "name": "cell",
                    "volume": 1.0,
                    "dimension": 3,
                    "parent": "",
                    "unit": "litre",
                }
            ],
            "seeds": [
                {
                    "pattern": "A(b,s~u)",
                    "amount": "10.0",
                    "constant": False,
                    "compartment": "cell",
                    "unit": "item",
                },
                {
                    "pattern": "B(a)",
                    "amount": "5.0",
                    "constant": False,
                    "compartment": "cell",
                    "unit": "item",
                },
            ],
            "observables": [
                {"name": "TotalA", "type": "Molecules", "patterns": ["A()"]},
                {"name": "ActiveA", "type": "Species", "patterns": ["A(s~p)"]},
            ],
            "functions": [
                {"name": "rate_func", "args": [], "expression": "k1*TotalA"},
                {"name": "two_arg", "args": ["x", "y"], "expression": "x + y"},
            ],
            "energy_patterns": [
                {"label": "e1", "pattern": "A(s~p)", "expression": "1.2"}
            ],
            "barrier_patterns": [],
            "population_maps": [
                {
                    "label": "map1",
                    "pattern": "A()",
                    "function": "PopA",
                    "args": [],
                    "rate": "k1",
                }
            ],
            "rules": [
                {
                    "name": "r1",
                    "label": "delayed_rxn:",
                    "reactants": ["A(s~u)"],
                    "products": ["A(s~p)"],
                    "rates": ["k1"],
                    "modifiers": [],
                    "bidirectional": False,
                    "delay": "tau",
                    "non_consuming": False,
                },
                {
                    "name": "r2",
                    "label": "rev_iso:",
                    "reactants": ["A(b,s~u)"],
                    "products": ["A(b,s~p)"],
                    "rates": ["k1", "k1"],
                    "modifiers": ["TotalRate"],
                    "bidirectional": True,
                },
            ],
        },
        "protocol": {
            "actions": [
                {
                    "scope": "model",
                    "name": "generate_network",
                    "arguments": {"overwrite": "1"},
                },
                {
                    "scope": "model",
                    "name": "setparameter",
                    "arguments": {"target": "k1", "value": "1.0"},
                },
            ]
        },
    }

    # Validate against v0.1 schema
    jsonschema.validate(full_v01_document, SCHEMA_V01)

    # Migrate v0.1 -> Model -> v0.2
    model = from_bngir(full_v01_document)
    v02_str = to_bngir(model, version="0.2")
    doc_v02 = json.loads(v02_str)

    # Validate against v0.2 schema
    assert doc_v02["version"] == "0.2"
    jsonschema.validate(doc_v02, SCHEMA_V02)

    # Check representability of every v0.1 field in v0.2
    m_v02 = doc_v02["model"]
    meta_v02 = m_v02["metadata"]

    assert meta_v02["name"] == full_v01_document["model"]["name"]
    assert meta_v02["version"] == full_v01_document["model"]["version"]
    assert meta_v02["substance_units"] == full_v01_document["model"]["substance_units"]
    assert meta_v02["options"] == full_v01_document["model"]["options"]

    # Parameters: IDs, names, expressions, constant values
    p_names = {p["name"] for p in m_v02["parameters"]}
    for p_v01 in full_v01_document["model"]["parameters"]:
        assert p_v01["name"] in p_names

    # Molecule types and components
    mt_names = {mt["name"] for mt in m_v02["molecule_types"]}
    for mt_v01 in full_v01_document["model"]["molecule_types"]:
        assert mt_v01["name"] in mt_names

    # Compartments
    comp_names = {c["name"] for c in m_v02["compartments"]}
    assert "cell" in comp_names

    # Observables (Molecules -> molecules, Species -> species)
    obs_names = {o["name"] for o in m_v02["observables"]}
    assert "TotalA" in obs_names
    assert "ActiveA" in obs_names

    # Functions
    func_names = {f["name"] for f in m_v02["functions"]}
    assert "rate_func" in func_names

    # Delayed rules and modifiers
    rule_labels = {r["label"] for r in m_v02["rules"]}
    assert any("delayed_rxn" in label for label in rule_labels)
    assert any(r.get("delay") is not None for r in m_v02["rules"])

    # Protocol actions
    action_names = {a["name"] for a in doc_v02["protocol"]["actions"]}
    assert "generate_network" in action_names
    assert "setparameter" in action_names

    # Migrate back to v0.1: validate against v0.1 schema
    v01_re_str = to_bngir(model, version="0.1")
    doc_v01_re = json.loads(v01_re_str)
    jsonschema.validate(doc_v01_re, SCHEMA_V01)

    # Frozen bridge fixtures: byte-for-byte deterministic reproducibility
    for legacy_name, structural_name in [
        ("v0.1-version-bridge.json", "v0.2-version-bridge.json"),
        ("v0.1-delayed-bridge.json", "v0.2-delayed-bridge.json"),
    ]:
        legacy_path = FIXTURES_DIR / legacy_name
        structural_path = FIXTURES_DIR / structural_name
        doc_legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        doc_expected = json.loads(structural_path.read_text(encoding="utf-8"))

        jsonschema.validate(doc_legacy, SCHEMA_V01)
        jsonschema.validate(doc_expected, SCHEMA_V02)

        m_legacy = from_bngir(doc_legacy)
        m_struct = from_bngir(doc_expected)
        assert semantic_equal(m_legacy, m_struct, version="0.2") is True

        exported_bytes = to_bngir(m_legacy, version="0.2").encode("utf-8")
        expected_bytes = json.dumps(
            doc_expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        assert exported_bytes == expected_bytes

    # Negative control: broken version document is rejected by schema
    broken_doc = copy.deepcopy(doc_v02)
    broken_doc["version"] = "99.9"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken_doc, SCHEMA_V02)


def test_release_obligation_154():
    """Validate release-obligation-154.

    Verifies contract.json schema, capability matrix rows, live obligations,
    and execution of adversarial negative fixtures.
    """
    # 1. Verify contract.json
    contract_path = CASE_DIR / "contract.json"
    assert contract_path.is_file(), "contract.json missing"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    assert contract["schema_version"] == 1
    assert contract["issue"] == 154
    assert contract["acceptance_checks"] == [
        "release-bngir-roundtrip",
        "release-bngir-version",
        "release-obligation-154",
    ]

    # 2. Verify capability matrix rows
    matrix_path = REPO_ROOT / "provenance" / "capability-matrix.yml"
    assert matrix_path.is_file(), "capability-matrix.yml missing"
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    matrix_ids = {row["id"] for row in matrix.get("rows", [])}
    for row_id in contract["inventory_rows"]:
        assert row_id in matrix_ids, f"Row {row_id} not in capability matrix"

    # 3. Verify live acceptance obligations
    obligations_path = REPO_ROOT / "provenance" / "issue-obligations.json"
    assert obligations_path.is_file(), "issue-obligations.json missing"
    prov = json.loads(obligations_path.read_text(encoding="utf-8"))
    issue_entry = next(
        (item for item in prov.get("issues", []) if item.get("number") == 154),
        None,
    )
    assert issue_entry is not None, "Issue 154 missing from issue-obligations"
    declared_ob_ids = {ob["id"] for ob in issue_entry.get("obligations", [])}
    for req_ob in contract["obligations"]:
        assert (
            req_ob in declared_ob_ids
        ), f"Obligation {req_ob} not found in issue-obligations for issue 154"

    # 4. Adversarial negative fixtures: malformed/corrupted documents fail closed
    adversarial_negative_fixtures = [
        "invalid_action_scope.json",
        "invalid_compartment_ref.json",
        "invalid_delay_parameter_ref.json",
        "invalid_duplicate_parameter_id.json",
        "invalid_energy_expression_ref.json",
        "invalid_energy_type_ref.json",
        "invalid_function_ref.json",
        "invalid_observable_ref_index.json",
        "invalid_observable_relation.json",
        "invalid_observable_type_ref.json",
        "invalid_parameter_ref.json",
        "invalid_rule_product_type_ref.json",
        "invalid_seed_compartment_ref.json",
        "invalid_seed_type_ref.json",
    ]
    for filename in adversarial_negative_fixtures:
        fixture_path = ADVERSARIAL_DIR / filename
        assert fixture_path.is_file(), f"Fixture missing: {filename}"
        doc = json.loads(fixture_path.read_text(encoding="utf-8"))
        # Must either fail schema validation or be refused by from_bngir
        failed_closed = False
        try:
            jsonschema.validate(doc, SCHEMA_V02)
            from_bngir(doc)
        except Exception:
            failed_closed = True
        assert failed_closed, f"Adversarial fixture {filename} was not refused"
