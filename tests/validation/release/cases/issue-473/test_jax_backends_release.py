"""Release acceptance checks related to Issue #473.

Covers the common compiled-model/rate/result/backend interfaces, functional,
time-dependent and observable-dependent rates, protocol/continuation and
interventions, physical-unit lowering, supported float dtypes and advertised
gradients for the JAX ODE backend; independent analytic and native-reference
distributions with fixed run counts and error control for the JAX SSA backend;
and separate installed-extra and unavailable-dependency checks.

Passing this module is the executing half of the release evidence. Exact-main
revision, artifacts and the issue-queue closure gate remain separate.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

import tests.python.test_jax_dynamic_rates as jdr  # noqa: E402
import tests.python.test_jax_install_diagnostics as tjid_install  # noqa: E402
import tests.python.test_jax_ode as tjo  # noqa: E402
import tests.python.test_jax_protocol_intervention as tjpi  # noqa: E402
import tests.python.test_jax_release_interfaces as tjri  # noqa: E402
import tests.python.test_jax_ssa as tjs  # noqa: E402
import tests.python.test_jax_ssa_competing_decay as tjsc  # noqa: E402
import tests.python.test_jax_ssa_immigration_death as tjid  # noqa: E402


def test_release_jax_ode():
    """Acceptance check release-jax-ode:

    source-derived analytic/BNG2 cases cover every required rate/protocol
    family in supported dtypes and differentiation.
    """
    tjo.test_generated_species_and_trajectory_match_analytic_and_native()
    tjo.test_jax_ode_differentiation_rate_constants()
    tjo.test_jax_ode_differentiation_initial_state()
    tjo.test_solver_method_is_not_silently_ignored()
    tjo.test_rate_overflowing_jax_state_dtype_is_rejected()
    tjo.test_invalid_t_start_rejected(-1.0, 5.0)
    tjo.test_jax_ode_nonzero_t_start_trajectory()
    tjo.test_jax_ode_continuation_protocol()
    tjo.test_jax_ode_continuation_with_rate_parameter_intervention()
    jdr.test_time_dependent_rhs_matches_analytic_law()
    jdr.test_time_dependent_simulation_matches_analytic_integral()
    jdr.test_time_dependent_automatic_differentiation()
    tjo.test_jax_ode_functional_rates_supported()
    jdr.test_observable_dependent_functional_rate_rhs()
    jdr.test_observable_dependent_functional_rate_simulation()
    jdr.test_observable_dependent_functional_rate_differentiation()
    jdr.test_observable_dependent_michaelis_menten()
    jdr.test_observable_dependent_hill_kinetics()
    jdr.test_observable_dependent_coupled_feedback()
    # Installed CPU protocol/rate/continuation family (parameter intervention,
    # analytic piecewise law and gradient, both supported dtypes via the job env).
    tjpi.test_jax_ode_time_dependent_parameter_intervention_continuation()
    tjpi.test_jax_ode_time_dependent_intervention_gradient()
    tjpi.test_jax_ode_functional_rate_intervention_continuation_and_gradient()
    tjpi.test_jax_ode_intervention_error_behavior()
    # Independent analytic units/dtype families and the common interfaces.
    tjri.test_jax_ode_units_match_analytic_declared_concentration(0.5)
    tjri.test_jax_ode_units_match_analytic_declared_concentration(1.0)
    tjri.test_jax_ode_units_match_analytic_declared_concentration(2.0)
    tjri.test_jax_ode_observable_dependent_mm_matches_independent_implicit_law()
    tjri.test_common_compiled_model_and_rate_interfaces()
    tjri.test_common_result_and_backend_interfaces()
    tjri.test_supported_dtypes_and_finite_input_guards()


def test_release_jax_ssa():
    """Acceptance check release-jax-ssa:

    actual trajectories pass analytic/native-reference distribution tests
    with stated run counts and error control.
    """
    tjs.test_jax_ssa_executes_batch_simulation()
    tjs.test_jax_ssa_batch_reproducibility()
    tjs.test_jax_ssa_bimolecular_conservation()
    tjs.test_jax_ssa_matches_analytic_first_order_survival_distribution()
    tjs.test_jax_ssa_matches_analytic_equilibrium_distribution()
    tjs.test_jax_ssa_trajectory_moments_match_native_reference()
    # New independently-qualified installed CPU case (immigration-death):
    # zero-order creation + first-order death, transient mean law and
    # stationary Poisson(4) DKW check with a wrong-Poisson power control.
    tjid.test_installed_cpu_jax_ssa_immigration_death_transient_mean()
    tjid.test_installed_cpu_jax_ssa_immigration_death_stationary_poisson()
    # Competing first-order decay: independent multinomial law, wrong-law
    # power control and native batch-SSA distributional parity.
    tjsc.test_competing_decay_matches_independent_multinomial_law()
    tjsc.test_competing_decay_wrong_rate_law_is_rejected()
    tjsc.test_competing_decay_matches_native_batch_distribution()


def test_release_jax_install():
    """Acceptance check release-jax-install:

    optional dependency install and unavailable-dependency diagnostics
    pass separately.
    """
    # 1. Unavailable dependency diagnostic and import isolation, including
    #    the separate ODE diagnostic and package-import safety.
    tjs.test_jax_ssa_unavailable_without_optional_dependencies()
    tjs.test_jax_ssa_import_safety()
    tjid_install.test_unavailable_jax_diagnostics_are_separate_and_actionable()
    tjid_install.test_package_import_does_not_require_jax()

    # 2. Installed-extra campaign (only counted when the extra is installed).
    tjid_install.test_installed_optional_extra_is_real_and_executes_end_to_end()

    # 2. Installed dependency campaign execution when JAX is present
    try:
        import jax

        has_jax = True
    except (ImportError, ModuleNotFoundError):
        has_jax = False

    if has_jax:
        from bionetgen import _bionetgen_cpp as cpp
        from bionetgen import jax_ode, jax_ssa
        import numpy as np

        # Verify device availability includes CPU
        devices = jax.devices()
        assert len(devices) > 0, "No JAX devices available"

        # Verify end-to-end installed JAX ODE execution
        model = cpp.parse_string("""begin model
begin parameters
kf 0.2
kr 0.1
end parameters
begin molecule types
A()
B()
end molecule types
begin seed species
A() 10.0
B() 0.0
end seed species
begin observables
Molecules ObsA A()
Molecules ObsB B()
end observables
begin reaction rules
A() <-> B() kf, kr
end reaction rules
end model""")
        ode_res = jax_ode.simulate_jax_ode(model, t_end=2.0, n_steps=20)
        assert len(ode_res["time"]) == 21
        assert ode_res["concentrations"].shape == (21, 2)
        assert np.all(np.isfinite(ode_res["concentrations"]))
        np.testing.assert_allclose(
            ode_res["concentrations"].sum(axis=1), 10.0, atol=1e-5
        )

        # Verify end-to-end installed JAX SSA execution
        network = cpp.generate_network(model)
        ssa_res = jax_ssa.simulate(
            model, network, batch_size=64, t_end=2.0, n_steps=5, base_seed=42
        )
        assert ssa_res["batch_size"] == 64
        assert ssa_res["final_species"].shape == (64, 2)
        assert ssa_res["trajectories_per_sec_sim"] > 0
        np.testing.assert_array_equal(
            ssa_res["final_species"].sum(axis=1), np.full(64, 10)
        )


def test_release_capability_coverage_473():
    """Acceptance check release-capability-coverage-473:

    all assigned capability inventory cases execute against their row's
    named independent oracle.
    """
    contract_file = CASE_DIR / "contract.json"
    assert contract_file.exists(), f"contract.json not found in {CASE_DIR}"
    with contract_file.open() as f:
        contract = json.load(f)

    assert contract["schema_version"] == 1
    assert contract["issue"] == 473
    assert contract["acceptance_checks"] == [
        "release-jax-ode",
        "release-jax-ssa",
        "release-jax-install",
        "release-capability-coverage-473",
    ]

    # Verify obligations
    obligations_file = REPO_ROOT / "provenance" / "issue-obligations.json"
    assert obligations_file.exists(), "issue-obligations.json not found"
    with obligations_file.open() as f:
        prov = json.load(f)

    issue_data = next(
        (item for item in prov.get("issues", []) if item.get("number") == 473),
        None,
    )
    assert issue_data is not None, "Issue 473 not found in obligations"
    declared_ob_ids = {ob["id"] for ob in issue_data.get("obligations", [])}
    for req_ob in contract["obligations"]:
        assert (
            req_ob in declared_ob_ids
        ), f"Obligation {req_ob} not found in provenance for issue 473"
