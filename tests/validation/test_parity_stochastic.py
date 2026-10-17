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
from tests.validation.strict import require_oracle

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
    ref_runs, ref_src = oracle_perl.ensemble(
        model_name, min_runs=200, work_dir=work_dir
    )
    require_oracle(
        len(ref_runs) >= 200,
        f"no 200-member reference ensemble for {model_name}: {ref_src}",
    )

    ref_data, _ = ref_runs[0]
    test_runs = runner.run_api_ensemble(
        model_name,
        method="ssa",
        n_runs=200,
        t_end=float(ref_data[-1, 0]),
        n_steps=ref_data.shape[0] - 1,
    )
    oracle_perl.qualify_model_ensemble(model_name, test_runs, label="BNG3 ensemble")
    diff = compare.compare_stochastic(
        ref_runs,
        test_runs,
        min_ref_runs=200,
        min_test_runs=200,
        columns=compare.COLUMNS_EXACT,
    )
    assert diff.ok, f"SSA vs Perl ensemble mismatch [{model_name}]: {diff.summary()}"


def test_binomial_control_detects_a_biased_reference_mean():
    assert hasattr(
        compare, "qualify_binomial_marginal"
    ), "oracle needs an independent marginal control"
    runs = [
        (np.array([[0, 0], [0.2, 26 + (i < 90)]]), ["time", "ScT"]) for i in range(200)
    ]
    with pytest.raises(AssertionError, match="reference.*analytic binomial marginal"):
        compare.qualify_binomial_marginal(
            runs,
            "ScT",
            population=100,
            probability=lambda time: (2 / 3) * (1 - np.exp(-3 * time)),
            label="reference",
        )


def test_binomial_control_accepts_a_correct_ensemble_mean():
    runs = [(np.array([[0, 0], [1, 50]]), ["time", "count"]) for _ in range(200)]
    compare.qualify_binomial_marginal(
        runs,
        "count",
        population=100,
        probability=lambda time: np.where(time == 0, 0.0, 0.5),
        label="control",
    )


def test_biased_cached_reference_requires_requalification(monkeypatch, tmp_path):
    from tests.validation import oracle_perl

    monkeypatch.delenv("BNG3_LIVE_SSA_ENSEMBLES", raising=False)
    for seed in range(200):
        (tmp_path / f"seed_{seed:04d}.gdat").write_text(
            f"# time ScT\n0 0\n0.2 {26 + (seed < 90)}\n"
        )
    monkeypatch.setattr(oracle_perl, "golden_ensemble", lambda model: tmp_path)
    with pytest.raises(
        AssertionError, match="BNG2 golden ensemble.*analytic binomial marginal"
    ):
        oracle_perl.ensemble("michment", min_runs=200)
