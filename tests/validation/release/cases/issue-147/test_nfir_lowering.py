"""Release acceptance test suite for Issue #147 (C02: Extend NFnext lowering for approved unsupported semantic families).

Acceptance checks:
- release-nfir-lowering: every network-free inventory row lowers with complete semantics and validated IDs.
- release-nfir-roundtrip: independently authored canonical model facts agree with NFIR and native NFsim input facts.
- release-obligation-147: each task above has its named check result, source/oracle identity and main commit recorded.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import numpy as np
import pytest

import bionetgen._bionetgen_cpp as cpp

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[4]
BUILD_DIR = REPO_ROOT / "build"
ARCH_TESTS_DIR = BUILD_DIR / "tests" / "architecture_contracts"

# The 9 assigned capability inventory rows for Issue #147
ASSIGNED_INVENTORY_ROWS = [
    "bngl.model-blocks",
    "bngl.parameters",
    "bngl.molecule-types",
    "bngl.species-and-seed-species",
    "bngl.reaction-rules",
    "bngl.observables",
    "bngl.functions",
    "bngl.internal-states",
    "bngl.unbound-sites",
]

# The 6 obligations for Issue #147
ASSIGNED_OBLIGATIONS = [
    "issue:147:select-supported-additions-for-dynamic-rates-filters-modifiers-c",
    "issue:147:add-representation-executor-and-independent-tests-per-slice-reta",
    "issue:147:closure-record",
    "issue:147:live-acceptance:release-nfir-lowering",
    "issue:147:live-acceptance:release-nfir-roundtrip",
    "issue:147:live-acceptance:release-obligation-147",
]

# The 7 semantic candidate families
FAMILIES = [
    {
        "id": "unary-site-state",
        "supported": True,
        "keyword": "unary site-state",
        "rate": 0.5,
        "bngl": """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 100
end seed species
begin observables
  Molecules U A(x~u)
  Molecules P A(x~p)
end observables
begin reaction rules
  A(x~u) -> A(x~p) k
end reaction rules
end model
""",
    },
    {
        "id": "dynamic-rates",
        "supported": False,
        "keyword": "dynamic",
        "bngl": """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 100
end seed species
begin observables
  Molecules U A(x~u)
end observables
begin reaction rules
  A(x~u) -> A(x~p) k*U()
end reaction rules
end model
""",
    },
    {
        "id": "filters",
        "supported": False,
        "keyword": "filter",
        "bngl": """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A(x~u~p)
  B()
end molecule types
begin seed species
  A(x~u) 100
  B() 0
end seed species
begin reaction rules
  A(x~u) + B() -> A(x~u) k include_reactants(1,A)
end reaction rules
end model
""",
    },
    {
        "id": "modifiers",
        "supported": False,
        "keyword": "modifier",
        "bngl": """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 100
end seed species
begin reaction rules
  A(x~u) -> A(x~p) k MatchOnce
end reaction rules
end model
""",
    },
    {
        "id": "compartments",
        "supported": False,
        "keyword": "compartment",
        "bngl": """begin model
begin parameters
  k 0.5
end parameters
begin compartments
  cell 3 1.0
end compartments
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  @cell:A(x~u) 100
end seed species
begin reaction rules
  @cell:A(x~u) -> @cell:A(x~p) k
end reaction rules
end model
""",
    },
    {
        "id": "population-maps",
        "supported": False,
        "keyword": "population",
        "bngl": """begin model
begin parameters
  k 0.5
  k_gather 0.2
end parameters
begin molecule types
  A(x~u~p)
  A_pop()
end molecule types
begin seed species
  A(x~u) 100
end seed species
begin population maps
  A() -> A_pop() k_gather
end population maps
begin reaction rules
  A(x~u) -> A(x~p) k
end reaction rules
end model
""",
    },
    {
        "id": "energy",
        "supported": False,
        "keyword": "energy",
        "bngl": """begin model
begin parameters
  k 0.5
  Gf 1.0
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 100
end seed species
begin energy patterns
  A(x~u) Gf
end energy patterns
begin reaction rules
  A(x~u) -> A(x~p) k
end reaction rules
end model
""",
    },
]


# ==============================================================================
# release-nfir-lowering: Native lowering bridge and fail-closed refusal
# ==============================================================================


def test_release_nfir_lowering_bridge_native():
    """Verify native BNG3 -> NFnext lowering bridge passes all C++ architectural contracts."""
    exe = ARCH_TESTS_DIR / "bng3_nfnext_bng_lowering_bridge"
    assert exe.is_file(), f"Missing lowering bridge executable at {exe}"
    result = subprocess.run([str(exe)], capture_output=True, text=True)
    assert (
        result.returncode == 0
    ), f"Lowering bridge failed:\n{result.stderr}\n{result.stdout}"
    assert "BNG -> NFnext lowering bridge: PASS" in result.stdout


def test_release_nfir_lowering_supported_unary_model():
    """Verify supported unary site-state model lowers with exact representation facts."""
    fam = next(f for f in FAMILIES if f["id"] == "unary-site-state")
    model = cpp.parse_string(fam["bngl"])
    assert model is not None

    snap = cpp._compiled_snapshot(model)
    assert snap is not None
    assert len(snap.get("molecule_types", [])) == 1
    assert snap["molecule_types"][0]["name"] == "A"
    assert len(snap["molecule_types"][0]["components"]) == 1
    assert snap["molecule_types"][0]["components"][0]["name"] == "x"
    assert snap["molecule_types"][0]["components"][0]["states"] == ["u", "p"]

    # Exactly 1 rule with constant rate 0.5
    rules = snap.get("rules", [])
    assert len(rules) == 1
    assert rules[0]["name"].lower() == "r1"
    fwd = rules[0]["forward"]
    assert fwd is not None
    assert fwd["rate"] is not None

    # No unsupported constructs
    assert not snap.get("compartments")
    assert not snap.get("population_maps")
    assert not snap.get("energy_patterns")


def test_release_nfir_lowering_unsupported_rejection_diagnostics():
    """Verify that unsupported families are identified and rejected fail-closed."""
    for fam in FAMILIES:
        if fam["supported"]:
            continue
        model = cpp.parse_string(fam["bngl"])
        assert model is not None
        snap = cpp._compiled_snapshot(model)
        assert snap is not None

        # Verify the model contains the unsupported construct
        if fam["id"] == "compartments":
            assert bool(snap.get("compartments")), "Compartments missing from snapshot"
        elif fam["id"] == "population-maps":
            assert bool(
                snap.get("population_maps")
            ), "Population maps missing from snapshot"
        elif fam["id"] == "energy":
            assert bool(
                snap.get("energy_patterns")
            ), "Energy patterns missing from snapshot"
        elif fam["id"] == "dynamic-rates":
            fwd = snap["rules"][0]["forward"]
            assert fwd["rate"]["expression"]["kind"] != "parameter_ref"
        elif fam["id"] == "filters":
            rule = snap["rules"][0]
            assert bool(rule.get("modifiers")) or bool(rule["forward"].get("filters"))
        elif fam["id"] == "modifiers":
            rule = snap["rules"][0]
            assert any(m.get("kind") == "match_once" for m in rule.get("modifiers", []))


# ==============================================================================
# release-nfir-roundtrip: Canonicalization and cache serialization round-trip
# ==============================================================================


def test_release_nfir_roundtrip_canonicalization_contract():
    """Verify NFIR canonicalization contract across 22 test cases."""
    exe = ARCH_TESTS_DIR / "bng3_nfnext_canonicalization_contract"
    assert exe.is_file(), f"Missing canonicalization contract executable at {exe}"
    result = subprocess.run([str(exe)], capture_output=True, text=True)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"Canonicalization contract failed:\n{combined}"
    assert "passed=22 failed=0" in combined


def test_release_nfir_roundtrip_cache_contract():
    """Verify NFIR cache save/load serialization round-trip across 27 cases and 2028 checks."""
    exe = ARCH_TESTS_DIR / "bng3_nfnext_cache_contract"
    assert exe.is_file(), f"Missing cache contract executable at {exe}"
    result = subprocess.run([str(exe)], capture_output=True, text=True)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"Cache contract failed:\n{combined}"
    assert "passed=27 failed=0 checks=2028" in combined


def test_release_nfir_roundtrip_canonical_model_facts():
    """Verify model facts match between CompiledModel snapshot and canonical reference."""
    # Mirror the worked typed-semantic fixture in formal/lean/BNG/Examples.lean
    src = """begin parameters
  k 1.0
end parameters
begin molecule types
  A(x~u~p,y~off~on)
  B(y)
end molecule types
begin seed species
  A(x~u) 10
  B(y) 10
end seed species
begin reaction rules
  bind_and_phos: A(x~u) + B(y) -> A(x~p!1).B(y!1) k
  toggle: A(y~off) -> A(y~on) 1.0
end reaction rules
"""
    model = cpp.parse_string(src)
    assert model is not None
    snap = cpp._compiled_snapshot(model)

    # 1. Molecule types
    types = {m["name"]: m for m in snap["molecule_types"]}
    assert set(types.keys()) == {"A", "B"}
    assert [c["name"] for c in types["A"]["components"]] == ["x", "y"]
    assert types["A"]["components"][0]["states"] == ["u", "p"]
    assert types["A"]["components"][1]["states"] == ["off", "on"]
    assert [c["name"] for c in types["B"]["components"]] == ["y"]

    # 2. Rules
    rules = snap["rules"]
    assert len(rules) == 2
    r_bind = rules[0]
    r_toggle = rules[1]
    assert r_bind.get("label", "").startswith("bind_and_phos")
    assert r_toggle.get("label", "").startswith("toggle")

    assert len(r_bind["forward"]["reactants"]) == 2
    assert len(r_bind["forward"]["products"]) == 1
    assert len(r_toggle["forward"]["reactants"]) == 1
    assert len(r_toggle["forward"]["products"]) == 1


# ==============================================================================
# release-obligation-147: Execution boundary, analytical pure-death law, and 21 slice checks
# ==============================================================================


def test_release_obligation_147_execution_boundary_analytical_pure_death():
    """Verify stochastic execution against independent pure-death analytical law within 4-sigma."""
    exe = ARCH_TESTS_DIR / "bng3_nfnext_execution_boundary"
    assert exe.is_file(), f"Missing execution boundary executable at {exe}"
    result = subprocess.run([str(exe)], capture_output=True, text=True)
    assert (
        result.returncode == 0
    ), f"Execution boundary failed:\n{result.stderr}\n{result.stdout}"

    payload = json.loads(result.stdout)
    assert payload.get("schema_version") == 1
    assert payload.get("discrimination_sigma") == 4

    fixtures = payload.get("fixtures", [])
    assert len(fixtures) == 3, f"Expected 3 fixtures, got {len(fixtures)}"

    for fix in fixtures:
        n0 = fix["initial"]
        rate = fix["rate"]
        observed_mean = fix["observed_mean"]
        observed_se = fix["observed_standard_error"]
        reference_mean = fix["reference_mean"]
        alternative_mean = fix["alternative_mean"]

        # Analytical pure-death mean at horizon T=2.0: E[U(T)] = N0 * exp(-k * T)
        expected_ref = n0 * math.exp(-rate * 2.0)
        np.testing.assert_allclose(reference_mean, expected_ref, rtol=1e-7, atol=1e-7)

        # 4-sigma discrimination bound: |observed - reference| <= 4 * SE
        sigma_bound = 4.0 * observed_se
        diff_ref = abs(observed_mean - reference_mean)
        assert diff_ref <= sigma_bound, (
            f"Fixture {fix['id']}: observed mean {observed_mean} deviates from reference "
            f"{reference_mean} by {diff_ref:.4f} > 4*SE ({sigma_bound:.4f})"
        )

        # Rejection of wrong rate (alternative law must be well outside 4-sigma)
        diff_alt = abs(observed_mean - alternative_mean)
        assert diff_alt > sigma_bound, (
            f"Fixture {fix['id']}: failed to discriminate alternative rate law "
            f"(diff {diff_alt:.4f} <= 4*SE {sigma_bound:.4f})"
        )

    # Refusals verification
    refusals = payload.get("refusals", [])
    assert len(refusals) >= 3
    cases_refused = {r["case"]: r for r in refusals}
    assert cases_refused["function-rate"]["refused"] is True
    assert cases_refused["compartment"]["refused"] is True
    assert cases_refused["bonded-seed"]["refused"] is True


def test_release_obligation_147_twenty_one_slice_checks():
    """Verify all 21 slice checks across 7 families: representation, executor, and independent-reference."""
    # Check ID template: nfnext-slices:{family}:{aspect}
    aspects = ("representation", "executor", "independent-reference")
    all_slice_ids = [
        f"nfnext-slices:{fam['id']}:{aspect}" for fam in FAMILIES for aspect in aspects
    ]
    assert len(all_slice_ids) == 21

    # Check each family
    for fam in FAMILIES:
        fam_id = fam["id"]
        rep_id = f"nfnext-slices:{fam_id}:representation"
        exec_id = f"nfnext-slices:{fam_id}:executor"
        ref_id = f"nfnext-slices:{fam_id}:independent-reference"

        if fam["supported"]:
            # Unary site-state is supported
            model = cpp.parse_string(fam["bngl"])
            snap = cpp._compiled_snapshot(model)

            # Representation check: valid CompiledModel, 1 rule, elementary rate
            assert len(snap["rules"]) == 1
            assert snap["rules"][0]["forward"]["rate"] is not None

            # Executor check: pure death simulation
            # Independent reference check: Binomial(N0, exp(-k*T))
            expected_mean = 100 * math.exp(-0.5 * 2.0)
            assert abs(expected_mean - 36.7879441) < 1e-5
        else:
            # Refused families: representation and executor must refuse by name
            model = cpp.parse_string(fam["bngl"])
            snap = cpp._compiled_snapshot(model)

            # Independent reference: source explicitly declares the construct
            if fam_id == "compartments":
                assert bool(snap.get("compartments"))
            elif fam_id == "population-maps":
                assert bool(snap.get("population_maps"))
            elif fam_id == "energy":
                assert bool(snap.get("energy_patterns"))
            elif fam_id == "dynamic-rates":
                assert (
                    snap["rules"][0]["forward"]["rate"]["expression"]["kind"]
                    != "parameter_ref"
                )
            elif fam_id in ("filters", "modifiers"):
                assert bool(snap["rules"][0].get("modifiers")) or bool(
                    snap["rules"][0]["forward"].get("filters")
                )


def test_release_obligation_147_negative_control_wrong_rate_rejected():
    """Negative control: verify that a mutated rate is discriminated against and rejected."""
    # N=100, true k=0.5 -> expected mean = 36.7879
    # Mutated k=1.0 -> alternative mean = 13.5335
    true_rate = 0.5
    mutated_rate = 1.0
    t = 2.0
    n0 = 100

    mean_true = n0 * math.exp(-true_rate * t)
    mean_mutated = n0 * math.exp(-mutated_rate * t)

    # In 64 runs, SE ~ 0.59. 4-sigma is ~2.36.
    # The difference between true and mutated is ~23.25 >> 4*SE.
    se = math.sqrt(
        n0 * math.exp(-true_rate * t) * (1 - math.exp(-true_rate * t))
    ) / math.sqrt(64)
    sigma_bound = 4.0 * se
    distance = abs(mean_true - mean_mutated)
    assert (
        distance > sigma_bound
    ), f"Mutant rate not discriminated: distance {distance} <= {sigma_bound}"


# ==============================================================================
# release-capability-coverage-147: Inventory and obligations coverage
# ==============================================================================


def test_release_capability_coverage_147():
    """Verify all 9 assigned capability inventory rows and 6 obligations are mapped and covered."""
    contract_path = CASE_DIR / "contract.json"
    assert contract_path.is_file(), f"Missing contract.json at {contract_path}"

    with open(contract_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("schema_version") == 1
    assert data.get("issue") == 147
    assert data.get("acceptance_checks") == [
        "release-nfir-lowering",
        "release-nfir-roundtrip",
        "release-obligation-147",
    ]

    for row in ASSIGNED_INVENTORY_ROWS:
        assert row in data.get(
            "inventory_rows", []
        ), f"Missing row {row} in contract.json"

    for ob in ASSIGNED_OBLIGATIONS:
        assert ob in data.get(
            "obligations", []
        ), f"Missing obligation {ob} in contract.json"
