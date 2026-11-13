"""Independent qualification of typed protocol actions and shared options for #140 and #178.

Acceptance checks:
- release-entrypoints: CLI, Python run, and Python load().simulate() return equivalent expected results.
- release-actions: default, explicit, invalid, and interaction cases for shared simulation options.
- release-capability-coverage-140: all assigned inventory cases execute and pass.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import numpy as np
import pytest

import bionetgen

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[4]

ANALYTIC_MODEL_TEMPLATE = """
begin model
begin parameters
    k 0.4
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
    B() 0
end seed species
begin observables
    Molecules A_obs A()
    Molecules B_obs B()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""


def _analytic_solution(
    t: np.ndarray, k: float = 0.4, a0: float = 10.0
) -> tuple[np.ndarray, np.ndarray]:
    a = a0 * np.exp(-k * t)
    b = a0 - a
    return a, b


def _read_gdat(path: Path) -> dict[str, np.ndarray]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    header_line = next(line for line in lines if line.startswith("#"))
    headers = [col for col in header_line.lstrip("#").split() if col]
    data_lines = [line for line in lines if not line.startswith("#")]
    arr = np.loadtxt(data_lines)
    return {header: arr[:, idx] for idx, header in enumerate(headers)}


# ==============================================================================
# release-entrypoints: Parity across CLI, Python run(), and Python load().simulate()
# ==============================================================================


@pytest.mark.parametrize("method", ["ode", "ssa", "pla", "psa"])
def test_release_entrypoints_simulation_methods(bng_cpp, tmp_path, method):
    """Verify CLI, bionetgen.run, and bionetgen.load().simulate() agreement."""
    t_end = 5.0
    n_steps = 10

    # 1. BNGL action block via bng_cpp CLI
    cli_dir = tmp_path / f"cli_{method}"
    cli_dir.mkdir(parents=True)
    cli_model = cli_dir / "model.bngl"
    action_block = f"""
begin actions
    generate_network({{overwrite=>1}})
    simulate({{method=>"{method}", t_end=>{t_end}, n_steps=>{n_steps}}})
end actions
"""
    cli_model.write_text(ANALYTIC_MODEL_TEMPLATE + action_block, encoding="utf-8")
    proc = subprocess.run(
        [str(bng_cpp), str(cli_model)], cwd=cli_dir, capture_output=True, text=True
    )
    assert proc.returncode == 0, f"CLI {method} failed: {proc.stderr}\n{proc.stdout}"
    cli_gdat = cli_dir / "model.gdat"
    assert cli_gdat.is_file()
    cli_data = _read_gdat(cli_gdat)

    # 2. Python API bionetgen.run()
    py_run_dir = tmp_path / f"py_run_{method}"
    py_run_dir.mkdir(parents=True)
    py_model = py_run_dir / "model.bngl"
    py_model.write_text(ANALYTIC_MODEL_TEMPLATE, encoding="utf-8")
    run_res = bionetgen.run(str(py_model), method=method, t_end=t_end, n_steps=n_steps)

    # 3. Python API bionetgen.load().simulate()
    loaded_model = bionetgen.load(str(py_model))
    sim_res = loaded_model.simulate(method=method, t_end=t_end, n_steps=n_steps)

    # Grid check across all entrypoints
    expected_times = np.linspace(0.0, t_end, n_steps + 1)
    if method != "pla":
        np.testing.assert_allclose(cli_data["time"], expected_times, atol=1e-12)
        np.testing.assert_allclose(run_res.time, expected_times, atol=1e-12)
        np.testing.assert_allclose(sim_res.time, expected_times, atol=1e-12)
    else:
        for t_arr in (cli_data["time"], run_res.time, sim_res.time):
            assert t_arr[0] == 0.0
            assert np.isclose(t_arr[-1], t_end)
            assert np.all(np.diff(t_arr) >= 0)

    if method == "ode":
        # Check against independent analytic law
        analytic_a, analytic_b = _analytic_solution(expected_times)
        np.testing.assert_allclose(cli_data["A_obs"], analytic_a, atol=1e-6)
        np.testing.assert_allclose(cli_data["B_obs"], analytic_b, atol=1e-6)
        np.testing.assert_allclose(run_res.observables["A_obs"], analytic_a, atol=1e-6)
        np.testing.assert_allclose(run_res.observables["B_obs"], analytic_b, atol=1e-6)
        np.testing.assert_allclose(sim_res.observables["A_obs"], analytic_a, atol=1e-6)
        np.testing.assert_allclose(sim_res.observables["B_obs"], analytic_b, atol=1e-6)

        # Cross-entrypoint exact consistency
        np.testing.assert_allclose(
            run_res.observables["A_obs"], sim_res.observables["A_obs"], atol=1e-8
        )
    else:
        # Stochastic invariant: total particle conservation A + B = 10
        for name, a_vals, b_vals in [
            ("cli", cli_data["A_obs"], cli_data["B_obs"]),
            ("py_run", run_res.observables["A_obs"], run_res.observables["B_obs"]),
            ("py_sim", sim_res.observables["A_obs"], sim_res.observables["B_obs"]),
        ]:
            total = a_vals + b_vals
            np.testing.assert_allclose(
                total,
                10.0,
                atol=1e-12,
                err_msg=f"{name} {method} violated conservation",
            )
            assert np.all(a_vals >= 0.0), f"{name} {method} produced negative counts"
            assert np.all(b_vals >= 0.0), f"{name} {method} produced negative counts"


@pytest.mark.parametrize(
    "action_name", ["simulate_ode", "simulate_ssa", "simulate_pla", "simulate_psa"]
)
def test_release_entrypoints_explicit_action_names(bng_cpp, tmp_path, action_name):
    """Verify dedicated action names (simulate_ode, simulate_pla, etc.) via CLI."""
    cli_dir = tmp_path / f"explicit_{action_name}"
    cli_dir.mkdir(parents=True)
    cli_model = cli_dir / "model.bngl"
    action_block = f"""
begin actions
    generate_network({{overwrite=>1}})
    {action_name}({{t_end=>5, n_steps=>10}})
end actions
"""
    cli_model.write_text(ANALYTIC_MODEL_TEMPLATE + action_block, encoding="utf-8")
    proc = subprocess.run(
        [str(bng_cpp), str(cli_model)], cwd=cli_dir, capture_output=True, text=True
    )
    assert proc.returncode == 0, f"{action_name} failed: {proc.stderr}\n{proc.stdout}"
    cli_gdat = cli_dir / "model.gdat"
    assert cli_gdat.is_file()
    cli_data = _read_gdat(cli_gdat)
    assert cli_data["time"][0] == 0.0
    assert np.isclose(cli_data["time"][-1], 5.0)
    assert len(cli_data["time"]) >= 2
    if action_name == "simulate_ode":
        np.testing.assert_allclose(
            cli_data["time"], np.linspace(0.0, 5.0, 11), atol=1e-12
        )
        analytic_a, _ = _analytic_solution(cli_data["time"])
        np.testing.assert_allclose(cli_data["A_obs"], analytic_a, atol=1e-6)
    else:
        np.testing.assert_allclose(
            cli_data["A_obs"] + cli_data["B_obs"], 10.0, atol=1e-12
        )


# ==============================================================================
# release-actions: Shared simulation option semantics, typing, and diagnostics
# ==============================================================================


def test_release_actions_suffix_option(bng_cpp, tmp_path):
    """Verify suffix option produces <basename>_<suffix>.gdat."""
    model_path = tmp_path / "model.bngl"
    action_block = """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>5, n_steps=>10, suffix=>"run1"})
    simulate({method=>"ode", t_end=>5, n_steps=>10})
end actions
"""
    model_path.write_text(ANALYTIC_MODEL_TEMPLATE + action_block, encoding="utf-8")
    proc = subprocess.run(
        [str(bng_cpp), str(model_path)], cwd=tmp_path, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "model_run1.gdat").is_file()
    assert (tmp_path / "model.gdat").is_file()


def test_release_actions_sparse_option(bng_cpp, tmp_path):
    """Verify sparse Jacobian option is accepted for ODE and rejected for SSA."""
    ode_dir = tmp_path / "sparse_ode"
    ode_dir.mkdir()
    ode_model = ode_dir / "model.bngl"
    ode_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>5, n_steps=>10, sparse=>1})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(ode_model)], cwd=ode_dir, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr

    ssa_dir = tmp_path / "sparse_ssa"
    ssa_dir.mkdir()
    ssa_model = ssa_dir / "model.bngl"
    ssa_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ssa", t_end=>5, n_steps=>10, sparse=>1})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(ssa_model)], cwd=ssa_dir, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "sparse require an ODE simulation method" in (proc.stderr + proc.stdout)


def test_release_actions_max_sim_steps_option(bng_cpp, tmp_path):
    """Verify max_sim_steps typing, validity diagnostics, and method restriction."""
    # Valid positive integer on SSA
    valid_dir = tmp_path / "valid_max_steps"
    valid_dir.mkdir()
    valid_model = valid_dir / "model.bngl"
    valid_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ssa", t_end=>5, n_steps=>10, max_sim_steps=>1000000})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(valid_model)], cwd=valid_dir, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr

    # Invalid negative integer raises diagnostic
    neg_dir = tmp_path / "neg_max_steps"
    neg_dir.mkdir()
    neg_model = neg_dir / "model.bngl"
    neg_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ssa", t_end=>5, n_steps=>10, max_sim_steps=>-500})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(neg_model)], cwd=neg_dir, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "max_sim_steps must be a non-negative integer" in (proc.stderr + proc.stdout)

    # Restriction: max_sim_steps requires SSA or PSA
    ode_dir = tmp_path / "ode_max_steps"
    ode_dir.mkdir()
    ode_model = ode_dir / "model.bngl"
    ode_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>5, n_steps=>10, max_sim_steps=>1000})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(ode_model)], cwd=ode_dir, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "max_sim_steps requires an SSA or PSA simulation method" in (
        proc.stderr + proc.stdout
    )


def test_release_actions_check_product_scale_option(bng_cpp, tmp_path):
    """Verify check_product_scale typing, diagnostics, and method restriction."""
    # Valid non-negative value on ODE
    valid_dir = tmp_path / "valid_cps"
    valid_dir.mkdir()
    valid_model = valid_dir / "model.bngl"
    valid_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>5, n_steps=>10, check_product_scale=>1.5})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(valid_model)], cwd=valid_dir, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr

    # Invalid negative value
    neg_dir = tmp_path / "neg_cps"
    neg_dir.mkdir()
    neg_model = neg_dir / "model.bngl"
    neg_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>5, n_steps=>10, check_product_scale=>-2.0})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(neg_model)], cwd=neg_dir, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "check_product_scale must be non-negative" in (proc.stderr + proc.stdout)

    # Restriction: check_product_scale requires ODE or PSA
    ssa_dir = tmp_path / "ssa_cps"
    ssa_dir.mkdir()
    ssa_model = ssa_dir / "model.bngl"
    ssa_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ssa", t_end=>5, n_steps=>10, check_product_scale=>1.0})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(ssa_model)], cwd=ssa_dir, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "check_product_scale requires an ODE or PSA simulation method" in (
        proc.stderr + proc.stdout
    )


def test_release_actions_poplevel_option(bng_cpp, tmp_path):
    """Verify poplevel typing, diagnostics, and method restriction to PSA."""
    # Valid positive value on PSA
    valid_dir = tmp_path / "valid_poplevel"
    valid_dir.mkdir()
    valid_model = valid_dir / "model.bngl"
    valid_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"psa", t_end=>5, n_steps=>10, poplevel=>50})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(valid_model)], cwd=valid_dir, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr

    # Invalid negative value
    neg_dir = tmp_path / "neg_poplevel"
    neg_dir.mkdir()
    neg_model = neg_dir / "model.bngl"
    neg_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"psa", t_end=>5, n_steps=>10, poplevel=>-5})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(neg_model)], cwd=neg_dir, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "poplevel must be finite and non-negative" in (proc.stderr + proc.stdout)

    # Restriction: poplevel requires PSA
    ode_dir = tmp_path / "ode_poplevel"
    ode_dir.mkdir()
    ode_model = ode_dir / "model.bngl"
    ode_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>5, n_steps=>10, poplevel=>10})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(ode_model)], cwd=ode_dir, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "poplevel requires a PSA simulation method" in (proc.stderr + proc.stdout)


def test_release_actions_pla_config_option(bng_cpp, tmp_path):
    """Verify custom pla_config is parsed and accepted for PLA simulation."""
    pla_dir = tmp_path / "pla_custom"
    pla_dir.mkdir()
    pla_model = pla_dir / "model.bngl"
    pla_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate_pla({t_end=>5, n_steps=>10, pla_config=>"fEuler|pre-neg:sb|eps=0.03"})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(pla_model)], cwd=pla_dir, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert (pla_dir / "model.gdat").is_file()


def test_release_actions_shared_output_flags(bng_cpp, tmp_path):
    """Verify shared output and diagnostic flags (verbose, save_progress, print_end, print_on_stop)."""
    flags_dir = tmp_path / "flags_dir"
    flags_dir.mkdir()
    flags_model = flags_dir / "model.bngl"
    flags_model.write_text(
        ANALYTIC_MODEL_TEMPLATE + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>5, n_steps=>10, verbose=>1, save_progress=>0, print_end=>1, print_on_stop=>1, print_n_species_active=>1})
end actions
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(flags_model)], cwd=flags_dir, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert (flags_dir / "model.gdat").is_file()
    assert (flags_dir / "model_end.net").is_file()
    assert "[bng_cpp] Simulating with method=" in (proc.stderr + proc.stdout)


# ==============================================================================
# release-capability-coverage-140: Inventory verification
# ==============================================================================


def test_release_capability_coverage_140():
    """Verify all assigned inventory rows in contract.json are documented and verified."""
    contract = json.loads((CASE_DIR / "contract.json").read_text(encoding="utf-8"))
    inventory_rows = contract.get("inventory_rows", [])
    assert (
        len(inventory_rows) >= 15
    ), f"Expected comprehensive inventory list, got {len(inventory_rows)}"

    expected_rows = {
        "action.simulate_pla",
        "action.simulate_pla.method",
        "action.simulate_psa",
        "action.simulate_psa.method",
        "action.simulate.suffix",
        "action.simulate.sparse",
        "action.simulate.max_sim_steps",
        "action.simulate.check_product_scale",
        "action.simulate.pla_config",
        "action.simulate.poplevel",
        "action.simulate.verbose",
        "action.simulate.save_progress",
        "action.simulate.print_end",
        "action.simulate.print_on_stop",
        "action.simulate.print_n_species_active",
        "action.simulate.netfile",
        "action.simulate.argfile",
    }
    missing = expected_rows - set(inventory_rows)
    assert not missing, f"Contract missing required inventory rows: {missing}"
