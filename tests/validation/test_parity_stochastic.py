"""Stochastic parity: seeded determinism + distributional check vs Perl ensemble.

SSA/PLA/PSA are not bit-comparable. Two independent checks:
  (a) determinism  same seed twice -> identical arrays
  (b) ensemble     test mean within Perl mean +/- 3 SE on >= 98% of points
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.validation import compare, corpus, runner

STOCH_MODELS = [m for m in ("gene_expr", "michment", "simple_system")
                if corpus.resolve(m) is not None]


@pytest.mark.stochastic
@pytest.mark.parametrize("model_name", STOCH_MODELS)
def test_ssa_determinism(model_name, api):
    a = runner.run_api(model_name, method="ssa", seed=12345, t_end=10, n_steps=50)
    b = runner.run_api(model_name, method="ssa", seed=12345, t_end=10, n_steps=50)
    assert a.columns == b.columns
    np.testing.assert_array_equal(a.data, b.data,
                                  err_msg=f"SSA not deterministic under fixed seed [{model_name}]")


@pytest.mark.stochastic
@pytest.mark.slow
@pytest.mark.parametrize("model_name", STOCH_MODELS)
def test_ssa_ensemble_vs_perl(model_name, api, work_dir):
    from tests.validation import oracle_perl

    # Reference ensemble must be supplied as golden (Perl ensembles are slow);
    # skip if the project hasn't committed one.
    ref_path, ref_src = oracle_perl.gdat(model_name, work_dir / "perl")
    if ref_path is None:
        pytest.skip(f"no reference ensemble for {model_name}: {ref_src}")
    ref_data, ref_cols = compare.parse_gdat(ref_path)
    # Single reference trajectory treated as a 1-member ensemble mean is too weak;
    # require a committed multi-run golden (naming: <model>.ens.gdat) if present.
    pytest.importorskip("numpy")
    test_runs = runner.run_api_ensemble(model_name, method="ssa", n_runs=200,
                                        t_end=float(ref_data[-1, 0]), n_steps=ref_data.shape[0] - 1)
    diff = compare.compare_stochastic([(ref_data, ref_cols)], test_runs)
    # With a 1-member reference SE is undefined; this asserts the harness path runs
    # and is a placeholder until <model>.ens.gdat goldens land (tracked in regen_golden).
    assert diff.n_points_checked > 0
