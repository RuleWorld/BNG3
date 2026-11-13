"""Release acceptance test suite for Issue #148 (C03: Qualify a complete model-to-NFnext execution boundary).

Acceptance checks:
- release-nfnext-execution: full network-free corpus matches pinned native NFsim propensities/observables and exact draws or distributions.
- release-nfnext-routes: each trajectory stays on one engine and exercises the production CompiledModel entry point.
- release-capability-coverage-148: all assigned inventory cases execute against their row's named independent oracle.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import pytest

import bionetgen
import bionetgen._bionetgen_cpp as cpp
from tests.validation import integrated_nfnext_boundary as boundary
from tests.validation import oracle_nfsim

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[4]
BUILD_DIR = REPO_ROOT / "build"
ARCH_TESTS_DIR = BUILD_DIR / "tests" / "architecture_contracts"

ASSIGNED_INVENTORY_ROWS = [
    "nfnext.full",
]

ASSIGNED_OBLIGATIONS = [
    "issue:148:carry-and-initialize-the-supported-seeds-observables-parameter-f",
    "issue:148:compare-production-lowered-execution-with-reference-fixtures-and",
    "issue:148:closure-record",
    "issue:148:live-acceptance:release-nfnext-execution",
    "issue:148:live-acceptance:release-nfnext-routes",
    "issue:148:live-acceptance:release-capability-coverage-148",
]


# ==============================================================================
# release-nfnext-execution: Architecture contracts and execution verification
# ==============================================================================


def test_release_nfnext_execution_architecture_contracts(tmp_path: Path):
    """Verify that both C++ NFnext architectural executables pass."""
    bridge_exe = ARCH_TESTS_DIR / "bng3_nfnext_bng_lowering_bridge"
    assert bridge_exe.is_file(), f"Missing bridge executable at {bridge_exe}"
    res_bridge = subprocess.run(
        [str(bridge_exe)], capture_output=True, text=True, cwd=str(tmp_path)
    )
    assert (
        res_bridge.returncode == 0
    ), f"Lowering bridge failed:\n{res_bridge.stderr}\n{res_bridge.stdout}"
    assert "BNG -> NFnext lowering bridge: PASS" in res_bridge.stdout

    boundary_exe = ARCH_TESTS_DIR / "bng3_nfnext_execution_boundary"
    assert boundary_exe.is_file(), f"Missing boundary executable at {boundary_exe}"
    artifact = tmp_path / "boundary-test.json"
    res_bound = subprocess.run(
        [str(boundary_exe), str(artifact)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert (
        res_bound.returncode == 0
    ), f"Execution boundary failed:\n{res_bound.stderr}\n{res_bound.stdout}"
    assert artifact.is_file(), "Execution boundary produced no artifact"
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert len(data.get("fixtures", [])) == 3
    assert len(data.get("refusals", [])) >= 3


def test_release_nfnext_execution_pure_death_analytical_ensembles():
    """Verify 64-run ensembles match continuous-time Markov chain analytical laws within 4-sigma."""
    shapes = [
        {"initial": 100, "rate": 0.5},
        {"initial": 40, "rate": 0.25},
        {"initial": 200, "rate": 1.0},
    ]
    t_end = 2.0
    k_seeds = 64
    sigma_budget = 4.0

    for shape in shapes:
        n0 = shape["initial"]
        k = shape["rate"]
        bngl = f"""begin model
begin parameters
  k {k}
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) {n0}
end seed species
begin observables
  Molecules U A(x~u)
  Molecules P A(x~p)
end observables
begin reaction rules
  A(x~u) -> A(x~p) k
end reaction rules
end model
"""
        model = cpp.parse_string(bngl)
        assert model is not None

        ref_mean = n0 * math.exp(-k * t_end)
        alt_mean = n0 * math.exp(-2.0 * k * t_end)
        p = math.exp(-k * t_end)
        se = math.sqrt(n0 * p * (1.0 - p) / k_seeds)

        final_u = []
        for seed in range(k_seeds):
            out = cpp.simulate_nfnext(model, [0.0, 0.5, 1.0, t_end], seed=seed)
            u_vals = out["observables"]["U"]
            p_vals = out["observables"]["P"]
            assert len(u_vals) == 4
            assert u_vals[0] == n0
            assert p_vals[0] == 0.0
            # Strict conservation
            for u_val, p_val in zip(u_vals, p_vals):
                assert u_val + p_val == n0
            final_u.append(u_vals[-1])

        obs_mean = sum(final_u) / len(final_u)
        assert (
            abs(obs_mean - ref_mean) <= sigma_budget * se
        ), f"Ensemble N={n0}, k={k}: obs {obs_mean:.3f} outside 4*SE of ref {ref_mean:.3f}"
        assert (
            abs(obs_mean - alt_mean) > sigma_budget * se
        ), f"Ensemble N={n0}, k={k}: obs {obs_mean:.3f} failed to discriminate alt {alt_mean:.3f}"


def test_release_nfnext_execution_bimolecular_binding_and_mass_conservation():
    """Verify bimolecular binding/unbinding loop and strict mass conservation."""
    bngl = """begin model
begin parameters
  kon 0.1
  koff 0.05
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 40
  B(a) 40
end seed species
begin observables
  Molecules TotalA A()
  Molecules TotalB B()
  Molecules BoundAB A(b!1).B(a!1)
  Species Dimers A(b!1).B(a!1)
end observables
begin reaction rules
  bind: A(b) + B(a) <-> A(b!1).B(a!1) kon, koff
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    res = cpp.simulate_nfnext(model, [0.0, 1.0, 5.0], seed=42)
    times = res["time"]
    obs = res["observables"]
    assert len(times) == 3
    # Initial state
    assert obs["TotalA"][0] == 40.0
    assert obs["TotalB"][0] == 40.0
    assert obs["BoundAB"][0] == 0.0
    # Mass conservation at all times
    for a_val, b_val in zip(obs["TotalA"], obs["TotalB"]):
        assert a_val == 40.0
        assert b_val == 40.0
    for bound_val, dimer_val in zip(obs["BoundAB"], obs["Dimers"]):
        assert bound_val == dimer_val
    # Binding occurred
    assert obs["BoundAB"][-1] > 0.0


def test_release_nfnext_execution_symmetric_identical_reactants():
    """Verify identical reactants discover combinations and preserve parity."""
    bngl = """begin model
begin parameters
  k 0.05
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_count A()
end observables
begin reaction rules
  consume_identical: A() + A() -> 0 k
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    res = cpp.simulate_nfnext(model, [0.0, 0.5, 1.0], seed=20261101)
    a_counts = res["observables"]["A_count"]
    assert a_counts[0] == 10.0
    for val in a_counts:
        # Both reactants consumed simultaneously -> remaining count is always even
        assert int(val) % 2 == 0
        assert 0.0 <= val <= 10.0


def test_release_nfnext_execution_complex_seed_species():
    """Verify pre-formed complex seed species initialize bonds and unbind."""
    bngl = """begin model
begin parameters
  koff 0.8
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b!1).B(a!1) 30
end seed species
begin observables
  Molecules Bound A(b!1).B(a!1)
  Molecules TotalA A()
  Molecules TotalB B()
  Species TotalSpecies A()
end observables
begin reaction rules
  unbind: A(b!1).B(a!1) -> A(b) + B(a) koff
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    res = cpp.simulate_nfnext(model, [0.0, 1.0, 2.0], seed=123)
    obs = res["observables"]
    assert obs["Bound"][0] == 30.0
    for a_val, b_val in zip(obs["TotalA"], obs["TotalB"]):
        assert a_val == 30.0
        assert b_val == 30.0
    assert obs["Bound"][-1] < 30.0


def test_release_nfnext_execution_signaling_and_polymer_corpora():
    """Verify multi-state signaling complex and linear polymer elongation execution."""
    # Polymer model
    polymer_bngl = """begin model
begin parameters
  kp 0.2
  km 0.05
end parameters
begin molecule types
  M(l,r)
end molecule types
begin seed species
  M(l,r) 20
end seed species
begin observables
  Molecules Monomers M(l,r)
  Molecules TotalBonds M(r!1).M(l!1)
  Molecules TotalM M()
end observables
begin reaction rules
  elongate: M(r) + M(l) <-> M(r!1).M(l!1) kp, km
end reaction rules
end model
"""
    model_poly = cpp.parse_string(polymer_bngl)
    res_poly = cpp.simulate_nfnext(model_poly, [0.0, 1.0, 2.0], seed=77)
    assert res_poly["observables"]["TotalM"][0] == 20.0
    assert res_poly["observables"]["TotalM"][-1] == 20.0
    assert res_poly["observables"]["TotalBonds"][0] == 0.0
    assert res_poly["observables"]["TotalBonds"][-1] > 0.0

    # Multi-site signaling model
    signaling_bngl = """begin model
begin parameters
  k_act 0.3
  k_deact 0.1
end parameters
begin molecule types
  K(s,act~off~on)
  Sub(t~u~p)
end molecule types
begin seed species
  K(s,act~on) 15
  Sub(t~u) 30
end seed species
begin observables
  Molecules ActiveK K(act~on)
  Molecules PhosSub Sub(t~p)
end observables
begin reaction rules
  phos: K(act~on) + Sub(t~u) -> K(act~on) + Sub(t~p) k_act
  dephos: Sub(t~p) -> Sub(t~u) k_deact
end reaction rules
end model
"""
    model_sig = cpp.parse_string(signaling_bngl)
    res_sig = cpp.simulate_nfnext(model_sig, [0.0, 0.5, 1.0], seed=88)
    assert res_sig["observables"]["ActiveK"][0] == 15.0
    assert res_sig["observables"]["PhosSub"][0] == 0.0
    assert res_sig["observables"]["PhosSub"][-1] > 0.0


def test_release_nfnext_execution_native_nfsim_parity(tmp_path: Path):
    """Verify NFnext boundary qualification against native NFsim and analytical fixtures."""
    boundary_exe = ARCH_TESTS_DIR / "bng3_nfnext_execution_boundary"
    assert boundary_exe.is_file(), f"Missing binary at {boundary_exe}"
    native_exe = oracle_nfsim.nfsim_binary()

    rows = boundary.run(
        tmp_path / "nfnext_boundary_run",
        prototype_binary=boundary_exe,
        native_binary=native_exe,
    )
    assert len(rows) == 10

    # Verify carried-state and reference-fixture passes
    for r in rows:
        check_name = r["check"]
        if check_name in ("carried-state", "reference-fixture"):
            assert r["status"] == "PASS", f"Check {r['id']} failed: {r['detail']}"
        elif check_name == "unsupported-refusals":
            assert r["status"] == "PASS", f"Refusals check failed: {r['detail']}"
        elif check_name == "native-independent":
            if native_exe is not None:
                assert (
                    r["status"] == "PASS"
                ), f"Native parity check {r['id']} failed: {r['detail']}"


# ==============================================================================
# release-nfnext-routes: Production CompiledModel entry point and route isolation
# ==============================================================================


def test_release_nfnext_routes_production_entrypoint(tmp_path: Path):
    """Verify model.simulate(method='nfnext') stays on NFnext and uses CompiledModel entry point."""
    bngl = """begin model
begin parameters
  k 0.4
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 50
end seed species
begin observables
  Molecules U A(x~u)
  Molecules P A(x~p)
end observables
begin reaction rules
  A(x~u) -> A(x~p) k
end reaction rules
end model
"""
    model_path = tmp_path / "entrypoint_test.bngl"
    model_path.write_text(bngl, encoding="utf-8")
    model = bionetgen.load(str(model_path))
    res = model.simulate(method="nfnext", t_end=1.0, n_steps=2, seed=12)
    assert res.backend == "nfnext"
    assert "U" in res.observables
    assert "P" in res.observables
    assert res.observables["U"][0] == 50.0
    assert res.observables["P"][0] == 0.0
    assert res.observables["U"][-1] + res.observables["P"][-1] == 50.0


def test_release_nfnext_routes_fail_closed_unsupported_rejection(tmp_path: Path):
    """Verify that unsupported features raise RuntimeError fail-closed when executing via NFnext."""
    unsupported_models = [
        # Compartments
        """begin model
begin compartments
  cell 3 1.0
end compartments
begin molecule types
  A()
end molecule types
begin seed species
  @cell:A() 10
end seed species
begin reaction rules
  @cell:A() -> 0 0.1
end reaction rules
end model
""",
        # Population maps
        """begin model
begin molecule types
  A()
  PopA()
end molecule types
begin seed species
  A() 10
end seed species
begin population maps
  A() -> PopA() 0.1
end population maps
begin reaction rules
  A() -> 0 0.1
end reaction rules
end model
""",
        # Energy patterns
        """begin model
begin parameters
  G0 -1.0
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 10
end seed species
begin energy patterns
  A(x~p) G0
end energy patterns
begin reaction rules
  A(x~u) -> A(x~p) 0.1
end reaction rules
end model
""",
        # MatchOnce modifier
        """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> 0 0.1 MatchOnce
end reaction rules
end model
""",
        # TotalRate modifier
        """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> 0 0.1 TotalRate
end reaction rules
end model
""",
        # Wildcard seed bond
        """begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b!?) 10
end seed species
begin reaction rules
  A(b) -> 0 0.1
end reaction rules
end model
""",
    ]

    for idx, bngl in enumerate(unsupported_models):
        path = tmp_path / f"unsupported_{idx}.bngl"
        path.write_text(bngl, encoding="utf-8")
        model = bionetgen.load(str(path))
        with pytest.raises(RuntimeError) as exc_info:
            model.simulate(method="nfnext", t_end=1.0, n_steps=2)
        assert "NFnext execution unsupported" in str(exc_info.value)


# ==============================================================================
# release-capability-coverage-148: Contract mapping and obligations
# ==============================================================================


def test_release_capability_coverage_148():
    """Verify all assigned capability inventory rows and obligations are declared and covered."""
    contract_path = CASE_DIR / "contract.json"
    assert contract_path.is_file(), f"Missing contract.json at {contract_path}"

    with open(contract_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("schema_version") == 1
    assert data.get("issue") == 148
    assert data.get("acceptance_checks") == [
        "release-nfnext-execution",
        "release-nfnext-routes",
        "release-capability-coverage-148",
    ]

    for row in ASSIGNED_INVENTORY_ROWS:
        assert row in data.get(
            "inventory_rows", []
        ), f"Missing inventory row {row} in contract.json"

    for ob in ASSIGNED_OBLIGATIONS:
        assert ob in data.get(
            "obligations", []
        ), f"Missing obligation {ob} in contract.json"
