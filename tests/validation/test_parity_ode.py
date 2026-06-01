"""ODE trajectory parity: API simulate('ode') vs Perl/golden .gdat, rtol 1e-6."""

from __future__ import annotations

import pytest

from tests.validation import compare, corpus, oracle_perl, runner

# Deterministic ODE models suitable for tight numeric comparison.
ODE_MODELS = [
    "Motivating_example",
    "CaOscillate_Func",
    "Repressilator",
    "egfr_net",
    "gene_expr",
    "michment",
]
ODE_MODELS = [m for m in ODE_MODELS if corpus.resolve(m) is not None]


@pytest.mark.smoke
@pytest.mark.parametrize("model_name", ODE_MODELS)
def test_ode_parity(model_name, api, work_dir):
    ref_path, ref_src = oracle_perl.gdat(model_name, work_dir / "perl")
    if ref_path is None:
        pytest.skip(f"no reference .gdat for {model_name}: {ref_src}")

    ref_data, ref_cols = compare.parse_gdat(ref_path)
    assert ref_data is not None, f"could not parse reference .gdat ({ref_src})"

    # Match the reference time span/steps so grids align.
    t_end = float(ref_data[-1, ref_cols.index("time")] if "time" in ref_cols else ref_data[-1, 0])
    n_steps = ref_data.shape[0] - 1
    traj = runner.run_api(model_name, method="ode", t_end=t_end, n_steps=n_steps)

    diff = compare.compare_trajectories(
        ref_data, ref_cols, traj.data, traj.columns, rtol=1e-6
    )
    assert diff.ok, f"ODE mismatch [{model_name}] (ref={ref_src}): {diff.summary()}"
