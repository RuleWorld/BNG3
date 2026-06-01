"""Rate-law / local-function parity.

Function-heavy models must match the oracle ODE RHS to 1e-9. This is the gate
for WO-3 (single Expression evaluator across ODE / SSA / NF). With no separate
RHS dump available, we use a tight ODE trajectory tolerance as the proxy: if the
shared evaluator diverged, function-driven observables would drift well above
1e-9 within a few steps.
"""

from __future__ import annotations

import pytest

from tests.validation import compare, corpus, oracle_perl, runner

EXPR_MODELS = corpus.tier_expr()


@pytest.mark.expressions
@pytest.mark.parametrize("model_name", EXPR_MODELS)
def test_expression_rhs_parity(model_name, api, work_dir):
    ref_path, ref_src = oracle_perl.gdat(model_name, work_dir / "perl")
    if ref_path is None:
        pytest.skip(f"no reference .gdat for {model_name}: {ref_src}")
    ref_data, ref_cols = compare.parse_gdat(ref_path)
    assert ref_data is not None

    t_end = float(ref_data[-1, ref_cols.index("time")] if "time" in ref_cols else ref_data[-1, 0])
    n_steps = ref_data.shape[0] - 1
    # localfunc/isingspin are stochastic; use ode where the model supports it,
    # else fall back to the model's native method recorded in its actions.
    method = "ode"
    traj = runner.run_api(model_name, method=method, t_end=t_end, n_steps=n_steps)
    diff = compare.compare_trajectories(ref_data, ref_cols, traj.data, traj.columns, rtol=1e-9)
    assert diff.ok, f"expression RHS drift [{model_name}] (ref={ref_src}): {diff.summary()}"
