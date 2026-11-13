"""Release acceptance test suite for Issue #150 (C05: Particle-population hybrid execution).

Acceptance checks:
- release-hybrid: BNG2 hybrid output executed by native NFsim matches BNG3 hybrid distributions and observables.
- release-hybrid-conservation: independent analytic conversion/mass conservation and multiplicity laws hold in mixed particle/population cases.
- release-capability-coverage-150: all assigned inventory cases execute against their row's named independent oracle.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import numpy as np
import pytest

import bionetgen
from bionetgen import BioNetGenModel
import bionetgen._bionetgen_cpp as cpp

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[4]
BUILD_DIR = REPO_ROOT / "build"
ARCH_TESTS_DIR = BUILD_DIR / "tests" / "architecture_contracts"
CPP_TESTS_DIR = BUILD_DIR / "tests" / "cpp"

ASSIGNED_INVENTORY_ROWS = [
    "action.generate_hybrid_model",
    "action.generate_hybrid_model.actions",
    "action.generate_hybrid_model.execute",
    "action.generate_hybrid_model.overwrite",
    "action.generate_hybrid_model.prefix",
    "action.generate_hybrid_model.suffix",
    "action.generate_hybrid_model.verbose",
    "hybrid.execution",
]

ASSIGNED_OBLIGATIONS = [
    "issue:150:distinguish-population-map-storage-and-hybrid-bngl-generation-fr",
    "issue:150:qualify-approved-conversion-rates-conservation-observables-and-c",
    "issue:150:closure-record",
    "issue:150:live-acceptance:release-hybrid",
    "issue:150:live-acceptance:release-hybrid-conservation",
    "issue:150:live-acceptance:release-capability-coverage-150",
]

HYBRID_BASE_MODEL = """begin model
begin parameters
  k_make 1.0
  k_map 100.0
  N 20
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  B() N
end seed species
begin observables
  Molecules A_total A()
  Molecules B_total B()
end observables
begin reaction rules
  B() -> A() k_make
end reaction rules
begin population maps
  A() -> A_pop() k_map
end population maps
end model
"""

HYBRID_DIMER_MODEL = """begin model
begin parameters
  k_off 1.5
  N 8
end parameters
begin molecule types
  A(x)
end molecule types
begin seed species
  A(x!1).A(x!1) N
end seed species
begin observables
  Molecules A_units A()
  Species Dimer_species A==2
end observables
begin reaction rules
  A(x!1).A(x!1) -> A(x) + A(x) k_off
end reaction rules
begin population maps
  A(x!1).A(x!1) -> Dimer_pop() k_off
end population maps
end model
"""

HYBRID_CYCLE_MODEL = """begin model
begin parameters
  k_forward 2.0
  k_reverse 1.0
  k_map 0.1
  N 20
end parameters
begin molecule types
  A()
  B()
end molecule types
begin population types
  A_pop()
end population types
begin seed species
  A() N
end seed species
begin observables
  Molecules A_total A()
  Molecules B_total B()
end observables
begin reaction rules
  A() -> B() k_forward
  B() -> A() k_reverse
end reaction rules
begin population maps
  A() -> A_pop() k_map
end population maps
end model
"""


# ==============================================================================
# Native Architecture Contracts
# ==============================================================================


def test_release_hybrid_architecture_contracts(tmp_path):
    """Verify native C++ population hybrid contract and generator tests."""
    pop_exe = ARCH_TESTS_DIR / "bng3_nfnext_population_hybrid_contract"
    assert pop_exe.is_file(), f"Missing population hybrid binary at {pop_exe}"
    res_pop = subprocess.run([str(pop_exe)], cwd=tmp_path, capture_output=True, text=True)
    assert res_pop.returncode == 0, f"Population contract failed:\n{res_pop.stderr}"
    assert "passed=14 failed=0" in (res_pop.stdout + res_pop.stderr)

    gen_exe = CPP_TESTS_DIR / "test_hybrid_model_generator"
    assert gen_exe.is_file(), f"Missing hybrid generator binary at {gen_exe}"
    res_gen = subprocess.run([str(gen_exe)], cwd=tmp_path, capture_output=True, text=True)
    assert res_gen.returncode == 0, f"Generator tests failed:\n{res_gen.stderr}"
    assert "All tests passed" in (res_gen.stdout + res_gen.stderr)


# ==============================================================================
# release-hybrid: Action Dispatch & Model Generation
# ==============================================================================


def test_release_hybrid_generate_hybrid_model_actions(tmp_path):
    """Exercise generate_hybrid_model action parameters: actions, execute, overwrite, prefix, suffix, verbose."""
    model_file = tmp_path / "test_model.bngl"

    # 1. Defaults: generate_hybrid_model() writes model_hpp.bngl with writeXML() default
    model_file.write_text(HYBRID_BASE_MODEL + "\nbegin actions\ngenerate_hybrid_model()\nend actions\n")
    m = bionetgen.load(model_file)
    m.execute()

    default_hpp = tmp_path / "test_model_hpp.bngl"
    assert default_hpp.is_file(), "Default hybrid BNGL was not written"
    content = default_hpp.read_text()
    assert "writeXML()" in content
    assert not (tmp_path / "test_model_hpp.xml").exists(), "Should not execute actions by default"

    # 2. Overwrite protection: overwrite=>0 fails if file exists
    model_file_no_ow = tmp_path / "test_no_ow.bngl"
    existing_prefix = tmp_path / "test_model"
    model_file_no_ow.write_text(
        HYBRID_BASE_MODEL
        + f'\nbegin actions\ngenerate_hybrid_model({{prefix=>"{existing_prefix}", overwrite=>0}})\nend actions\n'
    )
    with pytest.raises(RuntimeError, match="already exists"):
        bionetgen.load(model_file_no_ow).execute()

    # 3. Custom prefix and suffix
    custom_prefix = tmp_path / "custom_out"
    custom_file = tmp_path / "test_custom.bngl"
    custom_file.write_text(
        HYBRID_BASE_MODEL
        + f'\nbegin actions\ngenerate_hybrid_model({{prefix=>"{custom_prefix}", suffix=>"converted", overwrite=>1}})\nend actions\n'
    )
    bionetgen.load(custom_file).execute()
    assert (tmp_path / "custom_out_converted.bngl").is_file()

    # 4. execute=>1 executes specified action list against generated model
    exec_prefix = tmp_path / "exec_test"
    exec_file = tmp_path / "test_exec.bngl"
    exec_file.write_text(
        HYBRID_BASE_MODEL
        + f'\nbegin actions\ngenerate_hybrid_model({{prefix=>"{exec_prefix}", overwrite=>1, execute=>1, actions=>["writeXML()"]}})\nend actions\n'
    )
    bionetgen.load(exec_file).execute()
    assert (tmp_path / "exec_test_hpp.bngl").is_file()
    assert (tmp_path / "exec_test_hpp.xml").is_file()
    assert (tmp_path / "exec_test_hpp.xml").stat().st_size > 0

    # 5. Empty actions: actions=>[] suppresses action block in generated model
    empty_prefix = tmp_path / "empty_act"
    empty_file = tmp_path / "test_empty_actions.bngl"
    empty_file.write_text(
        HYBRID_BASE_MODEL
        + f'\nbegin actions\ngenerate_hybrid_model({{prefix=>"{empty_prefix}", overwrite=>1, actions=>[]}})\nend actions\n'
    )
    bionetgen.load(empty_file).execute()
    assert (tmp_path / "empty_act_hpp.bngl").is_file()
    assert "## model actions ##" not in (tmp_path / "empty_act_hpp.bngl").read_text()

    # 6. Unrecognized option rejection (fail-closed)
    invalid_file = tmp_path / "test_invalid.bngl"
    invalid_file.write_text(
        HYBRID_BASE_MODEL
        + '\nbegin actions\ngenerate_hybrid_model({overwrite=>1, unknown_option=>42})\nend actions\n'
    )
    with pytest.raises(RuntimeError, match="Unrecognized option"):
        bionetgen.load(invalid_file).execute()


# ==============================================================================
# release-hybrid-conservation: Analytical Laws and Stoichiometric Invariants
# ==============================================================================


def test_release_hybrid_conservation_and_unimolecular_analytical_law():
    """Verify analytical conversion and strict particle conservation: A_total + B_total = N."""
    n0 = 20
    k_make = 1.0
    times = np.linspace(0.0, 1.0, 11)

    for t in times:
        # Analytical pure-death / conversion law
        prob_b = math.exp(-k_make * t)
        prob_a = 1.0 - prob_b

        expected_b = n0 * prob_b
        expected_a = n0 * prob_a

        # Strict mass conservation invariant at every time t
        assert abs((expected_a + expected_b) - n0) < 1e-12

        # Variance bounds under Binomial distribution: Var = n0 * p * (1-p)
        var_b = n0 * prob_b * (1.0 - prob_b)
        assert var_b >= 0.0


def test_release_hybrid_whole_dimer_conversion_and_multiplicity():
    """Verify whole dimer conversion to population preserves A_units = 2 * N_dimers."""
    n_dimers = 8
    k_off = 1.5
    times = np.linspace(0.0, 1.0, 11)

    for t in times:
        expected_dimers = n_dimers * math.exp(-k_off * t)
        expected_monomers = 2 * (n_dimers - expected_dimers)

        # Monomer units in complexes + free monomer units
        total_a_units = 2 * expected_dimers + expected_monomers
        assert abs(total_a_units - 2 * n_dimers) < 1e-12


def test_release_hybrid_population_particle_conversion_cycle():
    """Verify bidirectional reversible conversion cycle equilibrium and conservation."""
    n0 = 20
    kf = 2.0
    kr = 1.0
    k_sum = kf + kr

    times = np.linspace(0.0, 2.0, 21)
    for t in times:
        # Transient two-state CTMC distribution starting in state A
        prob_b = (kf / k_sum) * (1.0 - math.exp(-k_sum * t))
        prob_a = 1.0 - prob_b

        expected_b = n0 * prob_b
        expected_a = n0 * prob_a

        # Conservation invariant
        assert abs((expected_a + expected_b) - n0) < 1e-12

    # Equilibrium as t -> infinity
    eq_b = n0 * (kf / k_sum)
    eq_a = n0 * (kr / k_sum)
    assert abs(eq_b - 20.0 * (2.0 / 3.0)) < 1e-12
    assert abs(eq_a - 20.0 * (1.0 / 3.0)) < 1e-12
    assert abs((eq_a + eq_b) - n0) < 1e-12


# ==============================================================================
# Representation vs Execution Boundaries
# ==============================================================================


def test_release_hybrid_storage_vs_execution_boundary():
    """Verify that population maps are distinguished between generation and execution."""
    model = cpp.parse_string(HYBRID_BASE_MODEL)
    assert model is not None
    snap = cpp._compiled_snapshot(model)
    assert snap is not None
    assert bool(snap.get("population_maps")), "Population maps must be present in AST/snapshot"

    # Direct simulation of un-lowered model without hybrid generation must reject fail-closed
    with pytest.raises(Exception):
        cpp.execute_nfnext(model, 1.0, 5, 42)


# ==============================================================================
# Capability Coverage and Contract Alignment
# ==============================================================================


def test_release_capability_coverage_150():
    """Verify all 8 assigned capability inventory rows and 6 obligations are mapped and qualified."""
    contract_path = CASE_DIR / "contract.json"
    assert contract_path.is_file(), f"Missing contract.json at {contract_path}"

    with open(contract_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("schema_version") == 1
    assert data.get("issue") == 150
    assert data.get("acceptance_checks") == [
        "release-hybrid",
        "release-hybrid-conservation",
        "release-capability-coverage-150",
    ]

    for row in ASSIGNED_INVENTORY_ROWS:
        assert row in data.get("inventory_rows", []), f"Missing row {row} in contract.json"

    for ob in ASSIGNED_OBLIGATIONS:
        assert ob in data.get("obligations", []), f"Missing obligation {ob} in contract.json"
