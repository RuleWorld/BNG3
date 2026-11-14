"""Bounded checks related to Issue #473.

Existing JAX CPU mass-action/time-dependent ODE, gradients and first-order SSA-law tests are retained.

jax_ode.py explicitly refuses observable-dependent functional rates (including an existing refusal regression). The new wrapper does not complete all protocol/continuation/rate families, and its install check tests unavailable/import behavior rather than an installed-extra campaign. No semantic implementation changed in #663.
Passing this module does not satisfy the complete live release contract or
authorize issue closure. Existing test IDs are retained for historical evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

import tests.python.test_jax_dynamic_rates as jdr  # noqa: E402
import tests.python.test_jax_ode as tjo  # noqa: E402
import tests.python.test_jax_ssa as tjs  # noqa: E402


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
    jdr.test_time_dependent_rhs_matches_analytic_law()
    jdr.test_time_dependent_simulation_matches_analytic_integral()
    jdr.test_time_dependent_automatic_differentiation()
    tjo.test_jax_ode_functional_rates_supported()
    jdr.test_observable_dependent_functional_rate_rhs()
    jdr.test_observable_dependent_functional_rate_simulation()
    jdr.test_observable_dependent_functional_rate_differentiation()


def test_release_jax_ssa():
    """Acceptance check release-jax-ssa:

    actual trajectories pass analytic/native-reference distribution tests
    with stated run counts and error control.
    """
    tjs.test_jax_ssa_executes_batch_simulation()
    tjs.test_jax_ssa_batch_reproducibility()
    tjs.test_jax_ssa_bimolecular_conservation()
    tjs.test_jax_ssa_matches_analytic_first_order_survival_distribution()


def test_release_jax_install():
    """Acceptance check release-jax-install:

    optional dependency install and unavailable-dependency diagnostics
    pass separately.
    """
    tjs.test_jax_ssa_unavailable_without_optional_dependencies()
    tjs.test_jax_ssa_import_safety()


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
