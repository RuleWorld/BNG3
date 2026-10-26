"""Focused SSA direct-vs-CPU-batch parity for SSTS stochastic/00003.

The source XML is the official stochastic/00003 payload with SHA-256
``c58a50dd86f981150b533dd9af25c38f9ef3aeeedad2f679400e022add77f50e``. The
BNGL rules below were reduced from the exact translation artifact
``8e44075492ae22f97dec4a3388a0d3f8559e0a6ae512bb33d6196c5d9ad1d462`` from
locked official run 40314965237 (BNG3 revision
``0f004fecd318abb5b21829d869765a07cb6684cf``). The independent exact-law
diagnostic for that same XML/report is recorded separately; this test checks
paired terminal-count consistency, not the official DSMTS acceptance result.

The direct API accepts signed 32-bit seeds; trajectories whose batch-derived
seed exceeds INT32_MAX cannot be passed to that API unchanged. The fixed
qualification uses base seed 3,000,000, 4,096 batch trajectories, and compares
the first 64 trajectories whose engine seed is positive and representable by
the direct API, over duration 5 with five output steps. The CPU batch and direct
API both construct the same OdeIntegrator over the same generated network;
the batch supplies the derived seed directly to that integrator.
"""

from __future__ import annotations

import numpy as np

from _extdep import require_extension
from scripts.ci.diagnose_ssts_stochastic_00003 import _source_moments

_cpp = require_extension()

BASE_SEED = 3_000_000
DIRECT_TRAJECTORIES = 64
BATCH_SIZE = 4096
T_END = 5.0
N_STEPS = 5

MODEL = """begin model
begin parameters
    Lambda 1
    Mu 1.1
end parameters
begin compartments
    Cell 3 1
end compartments
begin molecule types
    M_X()
end molecule types
begin seed species
    @Cell:M_X() 100
end seed species
begin observables
    Species X_amt @Cell:M_X()
    Species X @Cell:M_X()
end observables
begin reaction rules
    Birth: @Cell:M_X() -> @Cell:M_X() + @Cell:M_X() 1
    Death: @Cell:M_X() -> 0 1.1
end reaction rules
end model
"""


def _batch_engine_seed(base_seed: int, trajectory: int) -> int:
    """Mirror BatchSsa.hpp's SplitMix64 derivation and 32-bit seed narrowing."""
    mask = (1 << 64) - 1
    z = (base_seed + 0x9E3779B97F4A7C15 * (trajectory + 1)) & mask
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & mask
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & mask
    seed = (z ^ (z >> 31)) & 0xFFFFFFFF
    return seed or 1


def _source_law_endpoint_moments(time: float) -> tuple[float, float, float]:
    """Use the independent source-law oracle's exact first/fourth moments."""
    law = _source_moments(time)
    variance = law["variance"]
    fourth_central = variance**2 * (law["excess_kurtosis"] + 3.0)
    return law["mean"], variance, fourth_central


def test_ssts_00003_cpu_batch_terminal_counts_match_direct_ssa(tmp_path):
    """Same OdeIntegrator/model/network/seed yields identical terminal counts."""
    path = tmp_path / "stochastic-00003.bngl"
    path.write_text(MODEL)
    model = _cpp.parse_file(str(path))
    network = _cpp.generate_network(model)
    batch = _cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=BATCH_SIZE,
        t_start=0.0,
        t_end=T_END,
        n_steps=N_STEPS,
        threads=1,
        base_seed=BASE_SEED,
    )

    compared = 0
    batch_species = np.asarray(batch["final_species"], dtype=np.int64)
    # Guard the independent source-law moments at t=0 and their initial
    # variance slope before using them as the test reference.
    assert np.isclose(
        _source_law_endpoint_moments(1e-5)[1] / 1e-5,
        210.0,
        rtol=2e-5,
    )

    # One endpoint statistic avoids treating correlated output times as iid.
    # Chebyshev bounds each exact-moment-standardized statistic's two-sided
    # tail by 1/100 at this 10-SE threshold. Bonferroni bounds the joint
    # mean/variance false-alarm probability by 2%, without assuming those two
    # statistics are independent.
    endpoints = batch_species[:, 0].astype(np.float64)
    expected_mean, expected_variance, fourth_central = _source_law_endpoint_moments(T_END)
    mean_se = np.sqrt(expected_variance / BATCH_SIZE)
    sample_variance = endpoints.var(ddof=1)
    variance_se = np.sqrt(
        (fourth_central - ((BATCH_SIZE - 3) / (BATCH_SIZE - 1)) * expected_variance**2)
        / BATCH_SIZE
    )
    assert all(
        np.isfinite(value)
        for value in (expected_mean, expected_variance, fourth_central, mean_se, variance_se)
    )
    assert mean_se > 0.0 and variance_se > 0.0
    assert abs((endpoints.mean() - expected_mean) / mean_se) <= 10.0
    assert abs((sample_variance - expected_variance) / variance_se) <= 10.0
    for trajectory in range(BATCH_SIZE):
        seed = _batch_engine_seed(BASE_SEED, trajectory)
        if seed > 0x7FFFFFFF:
            continue  # direct binding takes a signed C++ int seed
        direct = _cpp.simulate_ssa(
            model,
            network,
            t_start=0.0,
            t_end=T_END,
            n_steps=N_STEPS,
            seed=seed,
        )
        direct_trace = np.asarray(direct["concentrations"])
        assert np.array_equal(direct_trace[0].astype(np.int64), np.array([100]))
        direct_final = direct_trace[-1].astype(np.int64)
        assert np.array_equal(batch_species[trajectory], direct_final), (
            f"terminal species mismatch for trajectory={trajectory}, seed={seed}"
        )
        compared += 1
        if compared == DIRECT_TRAJECTORIES:
            break

    assert compared == DIRECT_TRAJECTORIES
