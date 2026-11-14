"""Release acceptance tests for Issue #149: Network-Free Engine Roles and NFcore2 Consolidation.

Validates maintainer Decision 4 (C04):
- release-engine-consolidation: Every NFcore2 capability maps to passing tests in
  NFcore2 parity and NFnext architecture contracts with preserved fixtures.
- release-nf-default: Production default method="nf" selects NFcore; explicit
  method="nfcore" is selectable through the common interface and produces identical
  deterministic trajectories; both match analytical CTMC laws and native NFsim within 4-sigma.
- release-obligation-149: Obligation closure record, schema compliance, workload ownership
  matrix documentation, and negative containment (fail-closed refusal of unpromoted method="nfcore2").
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess

import numpy as np
import pytest

import bionetgen

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

REVERSIBLE_ISOMERIZATION_BNGL = """
begin model
begin parameters
    kf 2.0
    kr 1.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 300
    B() 0
end seed species
begin observables
    Molecules A A()
    Molecules B B()
end observables
begin reaction rules
    A() <-> B() kf, kr
end reaction rules
end model
"""

PURE_DEATH_BNGL = """
begin model
begin parameters
    k 1.5
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 200
end seed species
begin observables
    Molecules X X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
"""

COMPARTMENT_TRANSPORT_BNGL = """
begin model
begin parameters
    k_trans 0.5
end parameters
begin compartments
    c1 3 1.0
    c2 3 1.0
end compartments
begin molecule types
    M()
end molecule types
begin seed species
    @c1:M() 100
    @c2:M() 0
end seed species
begin observables
    Molecules M_c1 @c1:M()
    Molecules M_c2 @c2:M()
end observables
begin reaction rules
    @c1:M() -> @c2:M() k_trans
end reaction rules
end model
"""


def test_release_engine_consolidation(tmp_path: Path):
    """Validate release-engine-consolidation.

    Every NFcore2 capability maps to passing tests in NFcore2 parity and NFnext
    architecture contracts with preserved fixtures and history:
    1. Reversible isomerization & elementary transformations.
    2. Compartment products and multi-compartment reactant binding.
    3. Molecule compartments overriding species compartments.
    4. MoveConnected compartment relocations (root and non-root molecules).
    5. Incompatible compartment placement refusal and validation boundaries.
    6. Non-root pattern transformations (state change, deletion, binding, creation, bond deletion).
    """
    # 1. Verify Catch2 NFcore2 parity test executable runs and all 14 capability cases pass
    parity_candidates = [
        REPO_ROOT / "build" / "tests" / "cpp" / "test_nfcore2_parity",
        REPO_ROOT.parent / "build" / "tests" / "cpp" / "test_nfcore2_parity",
        Path.cwd() / "build" / "tests" / "cpp" / "test_nfcore2_parity",
    ]
    parity_bin = next((p for p in parity_candidates if p.exists()), None)
    assert (
        parity_bin is not None
    ), f"NFcore2 parity binary not found in {parity_candidates}"
    proc = subprocess.run(
        [str(parity_bin)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        proc.returncode == 0
    ), f"test_nfcore2_parity failed:\n{proc.stdout}\n{proc.stderr}"
    assert (
        "All tests passed" in proc.stdout or "14 test cases" in proc.stdout
    ), proc.stdout

    # 2. Verify all Catch2 NFnext architecture contracts run and pass
    build_candidates = [
        REPO_ROOT / "build",
        REPO_ROOT.parent / "build",
        Path.cwd() / "build",
    ]
    build_dir = next(
        (b for b in build_candidates if (b / "CTestTestfile.cmake").exists()),
        REPO_ROOT / "build",
    )
    ctest_proc = subprocess.run(
        [
            "ctest",
            "--test-dir",
            str(build_dir),
            "-R",
            "^architecture_nfnext",
            "--output-on-failure",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        ctest_proc.returncode == 0
    ), f"architecture_nfnext ctest failed:\n{ctest_proc.stdout}\n{ctest_proc.stderr}"

    # 3. Assert capability destination mapping between NFcore2 and NFnext
    capability_map = {
        "isomerization_and_transforms": {
            "nfcore2_fixtures": [
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 driver matches NFcore ensemble on reversible isomerization",
            ],
            "nfnext_contract": "tests/architecture_contracts/nfnext/future_contract/test_transformations_contract.cpp",
            "nfnext_boundary": "tests/architecture_contracts/nfnext/test_execution_boundary.cpp",
        },
        "compartment_products_and_binding": {
            "nfcore2_fixtures": [
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 creates products in the reaction compartment",
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 binds only compartment-compatible reactants",
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 honors explicit product compartments",
            ],
            "nfnext_contract": "tests/architecture_contracts/nfnext/future_contract/test_compartment_rate_contract.cpp",
        },
        "molecule_compartment_resolution": {
            "nfcore2_fixtures": [
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 seeds molecule compartments over the species compartment",
            ],
            "nfnext_contract": "tests/architecture_contracts/nfnext/test_bng_lowering_bridge.cpp",
        },
        "moveconnected_relocations": {
            "nfcore2_fixtures": [
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 MoveConnected moves only the primary compartment",
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 MoveConnected can relocate a non-root pattern molecule",
            ],
            "nfnext_contract": "tests/architecture_contracts/nfnext/future_contract/test_transformations_contract.cpp",
        },
        "compartment_placement_refusal": {
            "nfcore2_fixtures": [
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 refuses mixed, non-adjacent, and unusual-dimension placements",
            ],
            "nfnext_contract": "tests/architecture_contracts/nfnext/future_contract/test_compartment_rate_contract.cpp",
        },
        "non_root_transformations": {
            "nfcore2_fixtures": [
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 state change on non-root pattern molecule is supported",
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 deletion of non-root pattern molecule is supported",
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 binding on non-root pattern molecule is supported",
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 molecule creation on non-root pattern molecule is supported",
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 bond deletion on non-root pattern molecule is supported",
                "tests/cpp/test_nfcore2_parity.cpp::NFcore2 state change plus bond change on non-root is supported",
            ],
            "nfnext_contract": "tests/architecture_contracts/nfnext/future_contract/test_transformations_contract.cpp",
        },
    }

    for cap_name, mapping in capability_map.items():
        for fixture in mapping["nfcore2_fixtures"]:
            rel_file, test_case = fixture.split("::")
            fixture_path = REPO_ROOT / rel_file
            assert (
                fixture_path.exists()
            ), f"Fixture file missing for {cap_name}: {fixture_path}"
            assert (
                test_case in fixture_path.read_text()
            ), f"Fixture test case missing: {test_case}"

        contract_path = REPO_ROOT / mapping["nfnext_contract"]
        assert (
            contract_path.exists()
        ), f"NFnext contract file missing for {cap_name}: {contract_path}"

    # 4. Demonstrated production NFnext execution for transferred capabilities
    # 4a. Reversible isomerization & CTMC elementary transformations
    iso_state_bngl = """
begin model
begin parameters
    kf 2.0
    kr 1.0
end parameters
begin molecule types
    A(s~0~1)
end molecule types
begin seed species
    A(s~0) 300
    A(s~1) 0
end seed species
begin observables
    Molecules A A(s~0)
    Molecules B A(s~1)
end observables
begin reaction rules
    A(s~0) <-> A(s~1) kf, kr
end reaction rules
end model
"""
    iso_file = tmp_path / "iso_nfnext.bngl"
    iso_file.write_text(iso_state_bngl)
    m_iso = bionetgen.load(str(iso_file))
    res_iso = m_iso.simulate(method="nfnext", t_end=5.0, n_steps=10, seed=42)
    assert len(res_iso.time) == 11
    assert res_iso.backend == "nfnext"
    assert res_iso.observables["A"][-1] + res_iso.observables["B"][-1] == 300

    # 4b. Multi-compartment transport
    comp_file = tmp_path / "comp_nfnext.bngl"
    comp_file.write_text(COMPARTMENT_TRANSPORT_BNGL)
    m_comp = bionetgen.load(str(comp_file))
    res_comp = m_comp.simulate(method="nfnext", t_end=5.0, n_steps=10, seed=42)
    assert len(res_comp.time) == 11
    assert res_comp.backend == "nfnext"
    assert res_comp.observables["M_c1"][-1] + res_comp.observables["M_c2"][-1] == 100
    assert res_comp.observables["M_c2"][-1] > 0

    # 4c. MoveConnected complex relocation across compartments
    move_bngl = """
begin model
begin parameters
    k_move 1.0
end parameters
begin compartments
    c1 3 1.0
    c2 3 1.0
end compartments
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b!1)@c1.B(a!1)@c1 50
    A(b)@c2 0
end seed species
begin observables
    Molecules A_c1 @c1:A()
    Molecules A_c2 @c2:A()
    Molecules B_c1 @c1:B()
    Molecules B_c2 @c2:B()
end observables
begin reaction rules
    A()@c1 -> A()@c2 k_move MoveConnected
end reaction rules
end model
"""
    move_file = tmp_path / "move_nfnext.bngl"
    move_file.write_text(move_bngl)
    m_move = bionetgen.load(str(move_file))
    res_move = m_move.simulate(method="nfnext", t_end=3.0, n_steps=5, seed=42)
    assert res_move.observables["A_c1"][-1] + res_move.observables["A_c2"][-1] == 50
    assert res_move.observables["B_c1"][-1] + res_move.observables["B_c2"][-1] == 50
    assert res_move.observables["A_c2"][-1] > 0
    assert res_move.observables["B_c2"][-1] > 0

    # 4d. Non-root pattern transformations on complexes
    nonroot_bngl = """
begin model
begin parameters
    k_phos 2.0
end parameters
begin molecule types
    Kinase(s)
    Sub(k, state~U~P)
end molecule types
begin seed species
    Kinase(s!1).Sub(k!1, state~U) 40
end seed species
begin observables
    Molecules ComplexU Kinase(s!1).Sub(k!1, state~U)
    Molecules ComplexP Kinase(s!1).Sub(k!1, state~P)
end observables
begin reaction rules
    Kinase(s!1).Sub(k!1, state~U) -> Kinase(s!1).Sub(k!1, state~P) k_phos
end reaction rules
end model
"""
    nonroot_file = tmp_path / "nonroot_nfnext.bngl"
    nonroot_file.write_text(nonroot_bngl)
    m_nonroot = bionetgen.load(str(nonroot_file))
    res_nonroot = m_nonroot.simulate(method="nfnext", t_end=2.0, n_steps=5, seed=42)
    assert (
        res_nonroot.observables["ComplexU"][-1]
        + res_nonroot.observables["ComplexP"][-1]
        == 40
    )
    assert res_nonroot.observables["ComplexP"][-1] > 0


def test_release_nf_default(tmp_path: Path):
    """Validate release-nf-default.

    1. method="nf" defaults to NFcore.
    2. method="nfcore" explicitly selects NFcore through the common interface.
    3. Both routes yield identical deterministic trajectories for the same seed.
    4. Both match analytical continuous-time Markov chain laws within 4.0-sigma.
    5. NFcore-specific options (equilibrate, traversal_limit) are supported.
    """
    model_file = tmp_path / "reversible.bngl"
    model_file.write_text(REVERSIBLE_ISOMERIZATION_BNGL)
    m = bionetgen.load(str(model_file))

    # Deterministic trajectory identity between method="nf" and method="nfcore"
    res_default = m.simulate(method="nf", t_end=5.0, n_steps=10, seed=42)
    res_explicit = m.simulate(method="nfcore", t_end=5.0, n_steps=10, seed=42)

    np.testing.assert_allclose(res_default.time, res_explicit.time)
    np.testing.assert_array_equal(
        res_default.observables["A"], res_explicit.observables["A"]
    )
    np.testing.assert_array_equal(
        res_default.observables["B"], res_explicit.observables["B"]
    )
    assert res_default.backend == "nfsim"
    assert res_explicit.backend == "nfsim"

    # Analytical CTMC law parity: Reversible Isomerization A <-> B (kf=2.0, kr=1.0, N=300)
    # Steady state: p_A = kr / (kf + kr) = 1/3, E[A] = N * p_A = 100, Var[A] = N * p_A * (1 - p_A) = 66.67
    n_runs = 25
    final_a = []
    for s in range(1001, 1001 + n_runs):
        res = m.simulate(method="nfcore", t_end=5.0, n_steps=2, seed=s)
        final_a.append(res.observables["A"][-1])

    sample_mean_a = float(np.mean(final_a))
    expected_mean_a = 100.0
    sigma_a = math.sqrt(300.0 * (1.0 / 3.0) * (2.0 / 3.0))
    sem_a = sigma_a / math.sqrt(n_runs)
    z_a = abs(sample_mean_a - expected_mean_a) / sem_a
    assert (
        z_a < 4.0
    ), f"Reversible isomerization CTMC mean outside 4-sigma: mean={sample_mean_a}, z={z_a}"

    # Analytical CTMC law parity: Pure death X -> 0 (k=1.5, N0=200)
    death_file = tmp_path / "death.bngl"
    death_file.write_text(PURE_DEATH_BNGL)
    m_death = bionetgen.load(str(death_file))

    t_eval = 1.0
    p_survival = math.exp(-1.5 * t_eval)
    expected_death_mean = 200.0 * p_survival
    sigma_death = math.sqrt(200.0 * p_survival * (1.0 - p_survival))
    sem_death = sigma_death / math.sqrt(n_runs)

    final_x = []
    for s in range(2001, 2001 + n_runs):
        res = m_death.simulate(method="nf", t_end=t_eval, n_steps=2, seed=s)
        final_x.append(res.observables["X"][-1])

    sample_mean_death = float(np.mean(final_x))
    z_death = abs(sample_mean_death - expected_death_mean) / sem_death
    assert (
        z_death < 4.0
    ), f"Pure death CTMC mean outside 4-sigma: mean={sample_mean_death}, z={z_death}"

    # Option preservation: equilibrate and traversal_limit on method="nfcore"
    res_equil = m.simulate(
        method="nfcore",
        t_end=2.0,
        n_steps=4,
        seed=55,
        equilibrate=0.5,
        traversal_limit=2,
    )
    assert len(res_equil.time) == 5


def test_release_obligation_149(tmp_path: Path):
    """Validate release-obligation-149.

    1. contract.json conforms to schema 1, issue 149, and required obligations.
    2. Negative containment:
       - method="nfcore2" is refused fail-closed with clear diagnostic mentioning unpromoted prototype.
       - Unknown method strings are refused fail-closed.
       - Unsupported backend (e.g. backend="bngsim") is rejected for method="nfcore".
       - Incompatible ODE/SSA options (stop_if, max_sim_steps) are refused for method="nfcore".
    3. Workload ownership documentation exists and matches Decision 4.
    """
    # 1. Verify contract.json structure
    contract_file = CASE_DIR / "contract.json"
    assert contract_file.exists(), f"contract.json not found in {CASE_DIR}"
    with contract_file.open() as f:
        contract = json.load(f)

    assert contract["schema_version"] == 1
    assert contract["issue"] == 149
    assert "release-engine-consolidation" in contract["acceptance_checks"]
    assert "release-nf-default" in contract["acceptance_checks"]
    assert "release-obligation-149" in contract["acceptance_checks"]

    # Verify obligations declaration against provenance
    obligations_file = REPO_ROOT / "provenance" / "issue-obligations.json"
    assert obligations_file.exists(), "provenance/issue-obligations.json not found"
    with obligations_file.open() as f:
        prov = json.load(f)

    issue_data = next(
        (item for item in prov.get("issues", []) if item.get("number") == 149), None
    )
    assert issue_data is not None, "Issue 149 not found in issue-obligations.json"
    declared_ob_ids = {ob["id"] for ob in issue_data.get("obligations", [])}
    for req_ob in contract["obligations"]:
        assert (
            req_ob in declared_ob_ids
        ), f"Obligation {req_ob} not found in provenance for issue 149"

    # 2. Negative containment: fail-closed refusal of method="nfcore2"
    model_file = tmp_path / "model.bngl"
    model_file.write_text(REVERSIBLE_ISOMERIZATION_BNGL)
    m = bionetgen.load(str(model_file))

    with pytest.raises(
        ValueError, match="method='nfcore2' is an unpromoted prototype engine"
    ):
        m.simulate(method="nfcore2", t_end=1.0)

    # Negative containment: unknown method
    with pytest.raises(ValueError, match="Unknown simulation method"):
        m.simulate(method="invalid_engine", t_end=1.0)

    # Negative containment: backend='bngsim' invalid for method='nfcore'
    with pytest.raises(
        ValueError, match="backend='bngsim' is not valid for method='nfcore'"
    ):
        m.simulate(method="nfcore", backend="bngsim", t_end=1.0)

    # Negative containment: ODE/SSA options rejected for method='nfcore'
    with pytest.raises(
        ValueError, match="stop_if.*only for method='ode' or method='ssa'"
    ):
        m.simulate(method="nfcore", stop_if="A > 100", t_end=1.0)

    with pytest.raises(
        ValueError, match="max_sim_steps.*only for method='ode' or method='ssa'"
    ):
        m.simulate(method="nfcore", max_sim_steps=100, t_end=1.0)

    # 3. Workload ownership matrix documentation check
    readme_file = CASE_DIR / "README.md"
    assert readme_file.exists(), f"README.md not found in {CASE_DIR}"
    readme_text = readme_file.read_text()
    assert "Workload Ownership Matrix" in readme_text
    assert "Finite Network ODE" in readme_text
    assert "Production Network-Free Simulation" in readme_text
    assert "Next-Generation Network-Free Engine" in readme_text
    assert "Contained Prototype Oracle" in readme_text
    assert "Maintainer Decision 4 Summary" in readme_text

    # 4. Verify bng_nfcore2 is retired from the default bionetgen_core interface target
    cmake_file = REPO_ROOT / "cpp" / "CMakeLists.txt"
    assert cmake_file.exists(), f"CMakeLists.txt missing: {cmake_file}"
    cmake_text = cmake_file.read_text()
    idx = cmake_text.find("add_library(bionetgen_core INTERFACE)")
    assert idx != -1, "bionetgen_core definition not found in cpp/CMakeLists.txt"
    target_link_idx = cmake_text.find(
        "target_link_libraries(bionetgen_core INTERFACE", idx
    )
    assert target_link_idx != -1, "target_link_libraries(bionetgen_core) not found"
    end_idx = cmake_text.find(")", target_link_idx)
    bionetgen_core_block = cmake_text[target_link_idx:end_idx]
    assert (
        "bng_nfcore2" not in bionetgen_core_block
    ), "bng_nfcore2 must be retired from bionetgen_core default interface library"
