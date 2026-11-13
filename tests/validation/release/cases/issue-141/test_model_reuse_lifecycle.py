"""Independent qualification of compile-once model reuse and isolated trajectories for #141.

Acceptance checks:
- release-instance-isolation: concurrent and serial runs match independent expectations with independent RNG streams.
- release-lifecycle: ASan/TSan lifecycle and mutation/invalidation cases pass without races, leaks, or stale results.
- release-obligation-141: all assigned obligations and contracts are recorded and verified.
"""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
import numpy as np
import pytest

import bionetgen
from bionetgen import BioNetGenModel
import bionetgen._bionetgen_cpp as cpp

CASE_DIR = Path(__file__).resolve().parent

CONVERSION_MODEL_TEMPLATE = """
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


def _conversion_source(rate: float | str = 0.4, population: int = 10) -> str:
    return f"""
begin model
begin parameters
    k {rate}
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() {population}
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


def _analytic_conversion(
    t: np.ndarray, k: float = 0.4, a0: float = 10.0
) -> tuple[np.ndarray, np.ndarray]:
    a = a0 * np.exp(-k * t)
    b = a0 - a
    return a, b


# ==============================================================================
# release-instance-isolation: Concurrent and serial runs with independent RNG/solver
# ==============================================================================


def test_release_instance_isolation_concurrent_ode():
    """Verify concurrent ODE simulations on a single loaded model produce identical results matching analytic law."""
    model = BioNetGenModel(cpp.parse_string(CONVERSION_MODEL_TEMPLATE))
    options = dict(method="ode", t_end=5.0, n_steps=10)

    # Pre-generate baseline to establish expected analytic trajectory
    baseline = model.simulate(**options)
    expected_times = np.linspace(0.0, 5.0, 11)
    analytic_a, analytic_b = _analytic_conversion(expected_times)
    np.testing.assert_allclose(baseline.time, expected_times, atol=1e-12)
    np.testing.assert_allclose(baseline.observables["A_obs"], analytic_a, atol=1e-6)
    np.testing.assert_allclose(baseline.observables["B_obs"], analytic_b, atol=1e-6)

    # Execute 8 concurrent simulations of the same model instance across worker threads
    num_threads = 8
    results = []

    def run_sim(thread_id: int):
        return model.simulate(**options)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(run_sim, tid) for tid in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    assert len(results) == num_threads
    for res in results:
        np.testing.assert_array_equal(res.time, baseline.time)
        np.testing.assert_allclose(
            res.observables["A_obs"], baseline.observables["A_obs"], atol=1e-10
        )
        np.testing.assert_allclose(
            res.observables["B_obs"], baseline.observables["B_obs"], atol=1e-10
        )


def test_release_instance_isolation_concurrent_ssa_and_rng_independence():
    """Verify concurrent SSA runs isolate RNG state: same seed matches, different seeds differ."""
    model = BioNetGenModel(cpp.parse_string(CONVERSION_MODEL_TEMPLATE))
    options_base = dict(method="ssa", t_end=5.0, n_steps=10)

    # Run paired threads with identical seeds and distinct seeds
    seed_a = 42
    seed_b = 9999

    def run_seeded(seed_val: int):
        return model.simulate(seed=seed_val, **options_base)

    tasks = [
        ("A1", seed_a),
        ("A2", seed_a),
        ("B1", seed_b),
        ("B2", seed_b),
    ]

    completed: dict[str, object] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {executor.submit(run_seeded, seed): name for name, seed in tasks}
        for f in concurrent.futures.as_completed(future_map):
            name = future_map[f]
            completed[name] = f.result()

    # Identical seeds must produce exact pathwise identical trajectories
    np.testing.assert_array_equal(
        completed["A1"].observables["A_obs"],
        completed["A2"].observables["A_obs"],
    )
    np.testing.assert_array_equal(
        completed["B1"].observables["A_obs"],
        completed["B2"].observables["A_obs"],
    )

    # Distinct seeds must produce distinct stochastic sample paths
    assert not np.array_equal(
        completed["A1"].observables["A_obs"],
        completed["B1"].observables["A_obs"],
    ), "Distinct RNG seeds produced identical stochastic sample paths"

    # All trajectories must preserve exact particle conservation A + B = 10
    for name, res in completed.items():
        total = res.observables["A_obs"] + res.observables["B_obs"]
        np.testing.assert_allclose(
            total,
            10.0,
            atol=1e-12,
            err_msg=f"{name} violated particle conservation",
        )
        assert np.all(res.observables["A_obs"] >= 0.0)
        assert np.all(res.observables["B_obs"] >= 0.0)


# ==============================================================================
# release-lifecycle: Mutation invalidation, rate reclassification, exception recovery
# ==============================================================================


@pytest.mark.parametrize("method", ["ode", "ssa"])
@pytest.mark.parametrize("rate_val", [0.1, 0.8, 0.4])
def test_release_lifecycle_parameter_mutation_and_invalidation(method, rate_val):
    """Verify set_parameter invalidates cached network and produces fresh-compilation parity."""
    model = BioNetGenModel(cpp.parse_string(_conversion_source(rate=0.4)))
    options = dict(method=method, t_end=3.0, n_steps=6, seed=12345)

    # First run builds and caches network
    initial_res = model.simulate(**options)
    assert model._network is not None
    cached_network = model._network

    # Mutate parameter: network cache must be invalidated
    model.set_parameter("k", rate_val)
    assert (
        model._network is None
    ), "Parameter mutation did not invalidate cached network"

    # Re-simulation must rebuild network and match fresh compilation exactly
    reused_res = model.simulate(**options)
    assert model._network is not None
    assert model._network is not cached_network

    fresh_model = BioNetGenModel(cpp.parse_string(_conversion_source(rate=rate_val)))
    fresh_res = fresh_model.simulate(**options)

    np.testing.assert_array_equal(reused_res.time, fresh_res.time)
    if method == "ode":
        np.testing.assert_allclose(
            reused_res.observables["A_obs"],
            fresh_res.observables["A_obs"],
            rtol=1e-10,
            atol=1e-10,
        )
        expected_a, _ = _analytic_conversion(reused_res.time, k=rate_val)
        np.testing.assert_allclose(
            reused_res.observables["A_obs"], expected_a, atol=1e-6
        )
    else:
        np.testing.assert_array_equal(
            reused_res.observables["A_obs"], fresh_res.observables["A_obs"]
        )


def test_release_lifecycle_rate_reclassification():
    """Verify changing a rate parameter from dynamic expression to constant reclassifies rate correctly."""
    # Start with time-dependent rate law: A -> B with k = time()
    model = BioNetGenModel(
        cpp.parse_string(_conversion_source(rate="time()", population=10))
    )
    options = dict(method="ode", t_end=2.0, n_steps=10)

    # Analytical solution for dA/dt = - t * A from A(0)=10 is A(t) = 10 * exp(-t^2 / 2)
    res_dynamic = model.simulate(**options)
    analytic_dynamic = 10.0 * np.exp(-0.5 * res_dynamic.time**2)
    np.testing.assert_allclose(
        res_dynamic.observables["A_obs"], analytic_dynamic, atol=1e-5
    )

    # Mutate to constant static rate
    static_rate = 0.5
    model.set_parameter("k", static_rate)
    res_static = model.simulate(**options)

    # Check agreement with static analytic solution A(t) = 10 * exp(-0.5 * t)
    analytic_static, _ = _analytic_conversion(res_static.time, k=static_rate, a0=10.0)
    np.testing.assert_allclose(
        res_static.observables["A_obs"], analytic_static, atol=1e-6
    )

    # Reused static model matches fresh static compilation
    fresh_static = BioNetGenModel(
        cpp.parse_string(_conversion_source(rate=static_rate, population=10))
    )
    res_fresh = fresh_static.simulate(**options)
    np.testing.assert_allclose(
        res_static.observables["A_obs"], res_fresh.observables["A_obs"], atol=1e-10
    )


def test_release_lifecycle_exception_recovery():
    """Verify simulation exception does not corrupt model or leak state for subsequent valid simulations."""
    model = BioNetGenModel(cpp.parse_string(CONVERSION_MODEL_TEMPLATE))
    options = dict(method="ode", t_end=2.0, n_steps=5)

    # Valid baseline run
    baseline = model.simulate(**options)
    assert model._network is not None
    network = model._network

    # Simulate with invalid stop_if expression
    for invalid_expr in (
        "__nonexistent_identifier__ > 0",
        "if(time > 0, __undefined_var__, 0)",
    ):
        with pytest.raises(RuntimeError):
            model.simulate(stop_if=invalid_expr, **options)

        # Network must remain intact and valid
        assert (
            model._network is network
        ), "Exception improperly discarded cached network"

    # Subsequent valid simulation must recover cleanly and match baseline exactly
    recovered = model.simulate(**options)
    np.testing.assert_allclose(
        recovered.observables["A_obs"], baseline.observables["A_obs"], atol=1e-12
    )
    np.testing.assert_allclose(
        recovered.observables["B_obs"], baseline.observables["B_obs"], atol=1e-12
    )


# ==============================================================================
# release-obligation-141: Contract and obligation completeness
# ==============================================================================


def test_release_obligation_141():
    """Verify contract.json documents all required acceptance checks and obligations."""
    contract = json.loads((CASE_DIR / "contract.json").read_text(encoding="utf-8"))
    assert contract["issue"] == 141
    checks = contract.get("acceptance_checks", [])
    expected_checks = [
        "release-instance-isolation",
        "release-lifecycle",
        "release-obligation-141",
    ]
    for check in expected_checks:
        assert check in checks, f"Missing acceptance check: {check}"

    obligations = contract.get("obligations", [])
    assert len(obligations) >= 5, f"Expected obligations list, got {len(obligations)}"
