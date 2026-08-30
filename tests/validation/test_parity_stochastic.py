"""Stochastic parity: seeded determinism + distributional check vs Perl ensemble.

SSA/PLA/PSA are not bit-comparable. Two independent checks:
  (a) determinism  same seed twice -> identical arrays
  (b) ensemble     means agree within 3 pooled SE on >= 98% of points;
                   both sides must have at least 200 fixed-seed members
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.validation import compare, corpus, runner

STOCH_MODELS = [
    m
    for m in ("gene_expr", "michment", "simple_system")
    if corpus.resolve(m) is not None
]


@pytest.mark.stochastic
@pytest.mark.parametrize("model_name", STOCH_MODELS)
def test_ssa_determinism(model_name, api):
    a = runner.run_api(model_name, method="ssa", seed=12345, t_end=10, n_steps=50)
    b = runner.run_api(model_name, method="ssa", seed=12345, t_end=10, n_steps=50)
    assert a.columns == b.columns
    np.testing.assert_array_equal(
        a.data, b.data, err_msg=f"SSA not deterministic under fixed seed [{model_name}]"
    )


@pytest.mark.stochastic
@pytest.mark.slow
@pytest.mark.parametrize("model_name", STOCH_MODELS)
def test_ssa_ensemble_vs_perl(model_name, api, work_dir):
    from tests.validation import oracle_perl

    # A single .gdat is not an ensemble and must never be promoted to one.
    ref_runs, ref_src = oracle_perl.ensemble(model_name, min_runs=200)
    if len(ref_runs) < 200:
        pytest.skip(f"no 200-member reference ensemble for {model_name}: {ref_src}")

    ref_data, _ = ref_runs[0]
    test_runs = runner.run_api_ensemble(
        model_name,
        method="ssa",
        n_runs=200,
        t_end=float(ref_data[-1, 0]),
        n_steps=ref_data.shape[0] - 1,
    )
    diff = compare.compare_stochastic(
        ref_runs,
        test_runs,
        min_ref_runs=200,
        min_test_runs=200,
    )
    assert diff.ok, f"SSA vs Perl ensemble mismatch [{model_name}]: {diff.summary()}"
