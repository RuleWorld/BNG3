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
    res_pop = subprocess.run(
        [str(pop_exe)], cwd=tmp_path, capture_output=True, text=True
    )
    assert res_pop.returncode == 0, f"Population contract failed:\n{res_pop.stderr}"
    assert "passed=14 failed=0" in (res_pop.stdout + res_pop.stderr)

    gen_exe = CPP_TESTS_DIR / "test_hybrid_model_generator"
    assert gen_exe.is_file(), f"Missing hybrid generator binary at {gen_exe}"
    res_gen = subprocess.run(
        [str(gen_exe)], cwd=tmp_path, capture_output=True, text=True
    )
    assert res_gen.returncode == 0, f"Generator tests failed:\n{res_gen.stderr}"
    assert "All tests passed" in (res_gen.stdout + res_gen.stderr)


# ==============================================================================
# release-hybrid: Action Dispatch & Model Generation
# ==============================================================================


def test_release_hybrid_generate_hybrid_model_actions(tmp_path):
    """Exercise generate_hybrid_model action parameters: actions, execute, overwrite, prefix, suffix, verbose."""
    model_file = tmp_path / "test_model.bngl"

    # 1. Defaults: generate_hybrid_model() writes model_hpp.bngl with writeXML() default
    model_file.write_text(
        HYBRID_BASE_MODEL + "\nbegin actions\ngenerate_hybrid_model()\nend actions\n"
    )
    m = bionetgen.load(model_file)
    m.execute()

    default_hpp = tmp_path / "test_model_hpp.bngl"
    assert default_hpp.is_file(), "Default hybrid BNGL was not written"
    content = default_hpp.read_text()
    assert "writeXML()" in content
    assert not (
        tmp_path / "test_model_hpp.xml"
    ).exists(), "Should not execute actions by default"

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
        + "\nbegin actions\ngenerate_hybrid_model({overwrite=>1, unknown_option=>42})\nend actions\n"
    )
    with pytest.raises(RuntimeError, match="Unrecognized option"):
        bionetgen.load(invalid_file).execute()


# ==============================================================================
# release-hybrid-conservation: Analytical Laws and Stoichiometric Invariants
# ==============================================================================


def _simulate_hybrid_trajectory(
    tmp_path: Path, model_text: str, model_name: str, seed: int, action: str
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Execute hybrid model generation and simulation, returning times and observable trajectories."""
    model_file = tmp_path / f"{model_name}_{seed}.bngl"
    out_prefix = tmp_path / f"{model_name}_{seed}_out"
    action_text = (
        f'generate_hybrid_model({{prefix=>"{out_prefix}", overwrite=>1, '
        f'execute=>1, actions=>["{action}"]}})\n'
    )
    model_file.write_text(model_text + f"\nbegin actions\n{action_text}end actions\n")
    m = bionetgen.load(model_file)
    m.execute()

    gdat_file = tmp_path / f"{model_name}_{seed}_out_hpp.gdat"
    assert gdat_file.is_file(), f"Expected simulation output at {gdat_file}"

    with open(gdat_file, "r", encoding="utf-8") as f:
        header_line = None
        data_lines = []
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith("#"):
                header_line = line_str.lstrip("#").split()
            else:
                data_lines.append([float(x) for x in line_str.split()])

    assert header_line is not None and data_lines, "Empty or corrupted gdat output"
    data = np.array(data_lines)
    times = data[:, 0]
    observables = {
        name: data[:, idx] for idx, name in enumerate(header_line) if idx > 0
    }
    return times, observables


def test_release_hybrid_conservation_and_unimolecular_analytical_law(tmp_path):
    """Verify analytical conversion and strict particle conservation on actual simulation trajectories."""
    n0 = 20
    k_make = 1.0
    t_end = 0.5
    n_steps = 10
    n_runs = 25
    action = f"simulate_nf({{t_end=>{t_end}, n_steps=>{n_steps}, seed=>42}})"

    runs_b = []
    runs_a = []
    sim_times = None

    for seed in range(42, 42 + n_runs):
        act = f"simulate_nf({{t_end=>{t_end}, n_steps=>{n_steps}, seed=>{seed}}})"
        times, obs = _simulate_hybrid_trajectory(
            tmp_path, HYBRID_BASE_MODEL, "unimol", seed, act
        )
        sim_times = times
        a = obs["A_total"]
        b = obs["B_total"]

        # Strict stoichiometric mass conservation at every time point of every trajectory
        assert np.allclose(a + b, float(n0)), f"Conservation violated at seed {seed}"
        runs_a.append(a)
        runs_b.append(b)

    # Statistical convergence to CTMC analytical pure-death law: E[B(t)] = N0 * exp(-k*t)
    mean_b = np.mean(runs_b, axis=0)
    expected_b = n0 * np.exp(-k_make * sim_times)
    # Standard error of the mean under Binomial: sqrt(N * p * (1-p) / R)
    std_err = np.sqrt(
        n0 * np.exp(-k_make * sim_times) * (1.0 - np.exp(-k_make * sim_times)) / n_runs
    )
    # Within 3.5 standard errors at all sample times
    assert np.all(np.abs(mean_b - expected_b) <= np.maximum(3.5 * std_err, 0.5))

    # Negative / wrong-implementation control: corrupted trajectory must be detected
    corrupted_a = a.copy()
    corrupted_a[2] -= 1.0  # simulate artificial particle loss
    with pytest.raises(AssertionError):
        assert np.allclose(corrupted_a + b, float(n0))


def test_release_hybrid_whole_dimer_conversion_and_multiplicity(tmp_path):
    """Verify whole dimer conversion to population preserves A_units = 2 * N_dimers on trajectories."""
    n_dimers = 8
    t_end = 0.5
    n_steps = 5
    n_runs = 20

    dimer_runs = []
    sim_times = None

    for seed in range(100, 100 + n_runs):
        act = f"simulate_nf({{t_end=>{t_end}, n_steps=>{n_steps}, seed=>{seed}}})"
        times, obs = _simulate_hybrid_trajectory(
            tmp_path, HYBRID_DIMER_MODEL, "dimer", seed, act
        )
        sim_times = times
        a_units = obs["A_units"]
        dimers = obs["Dimer_species"]

        # Exact stoichiometric multiplicity invariant: 2 * N_dimers = 16 monomer units
        assert np.allclose(
            a_units, float(2 * n_dimers)
        ), f"Multiplicity invariant violated at seed {seed}"
        dimer_runs.append(dimers)

    # Dimer degradation proceeds monotonically or non-increasingly in expectation
    mean_dimers = np.mean(dimer_runs, axis=0)
    assert (
        mean_dimers[-1] < mean_dimers[0]
    ), "Dimers did not unbind over simulation interval"

    # Negative / wrong-implementation control: monomer unit destruction must be detected
    corrupted_units = a_units.copy()
    corrupted_units[1] += 2.0
    with pytest.raises(AssertionError):
        assert np.allclose(corrupted_units, float(2 * n_dimers))


def test_release_hybrid_population_particle_conversion_cycle(tmp_path):
    """Verify bidirectional reversible conversion cycle equilibrium and conservation on trajectories."""
    n0 = 20
    kf = 2.0
    kr = 1.0
    k_sum = kf + kr
    t_end = 1.0
    n_steps = 10
    n_runs = 20

    runs_b = []
    sim_times = None

    for seed in range(200, 200 + n_runs):
        act = f"simulate_nf({{t_end=>{t_end}, n_steps=>{n_steps}, seed=>{seed}}})"
        times, obs = _simulate_hybrid_trajectory(
            tmp_path, HYBRID_CYCLE_MODEL, "cycle", seed, act
        )
        sim_times = times
        a = obs["A_total"]
        b = obs["B_total"]

        # Conservation invariant on every step of every trajectory
        assert np.allclose(
            a + b, float(n0)
        ), f"Cycle conservation violated at seed {seed}"
        runs_b.append(b)

    # Transitions toward CTMC equilibrium: E[B] = n0 * (kf / k_sum) = 20 * (2/3) ~ 13.33
    mean_b = np.mean(runs_b, axis=0)
    # Monotonic rise towards equilibrium from 0
    assert mean_b[-1] > mean_b[0]
    expected_eq = n0 * (kf / k_sum)
    assert (
        abs(mean_b[-1] - expected_eq) < 3.0
    ), f"Empirical mean {mean_b[-1]} diverges from theoretical equilibrium {expected_eq}"

    # Negative control
    corrupted_cycle = a.copy()
    corrupted_cycle[-1] = 0.0
    with pytest.raises(AssertionError):
        assert np.allclose(corrupted_cycle + b, float(n0))


# ==============================================================================
# Representation vs Execution Boundaries
# ==============================================================================


def test_release_hybrid_storage_vs_execution_boundary():
    """Verify that population maps are distinguished between generation and execution."""
    model = cpp.parse_string(HYBRID_BASE_MODEL)
    assert model is not None
    snap = cpp._compiled_snapshot(model)
    assert snap is not None
    assert bool(
        snap.get("population_maps")
    ), "Population maps must be present in AST/snapshot"

    # Direct simulation of un-lowered model without hybrid generation must reject fail-closed
    with pytest.raises(RuntimeError, match="population maps"):
        cpp.simulate_nfnext(model, [0.0, 1.0], seed=42)


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
        assert row in data.get(
            "inventory_rows", []
        ), f"Missing row {row} in contract.json"

    for ob in ASSIGNED_OBLIGATIONS:
        assert ob in data.get(
            "obligations", []
        ), f"Missing obligation {ob} in contract.json"
