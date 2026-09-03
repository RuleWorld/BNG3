"""ODE trajectory parity: action-aware BNG3 CLI vs Perl/golden ``.gdat``."""

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
def test_ode_parity(model_name, bng_cpp, work_dir):
    ref_path, ref_src = oracle_perl.gdat(model_name, work_dir / "perl")
    if ref_path is None:
        pytest.skip(f"no reference .gdat for {model_name}: {ref_src}")

    ref_data, ref_cols = compare.parse_gdat(ref_path)
    assert ref_data is not None, f"could not parse reference .gdat ({ref_src})"

    # The BNG2 reference is produced by executing the model's action block.
    # Use the action-aware CLI path so setup actions (for example
    # setConcentration, sparse CVODE, and multi-phase continuation) are not
    # silently discarded by the direct API path.
    _, test_path, err = runner.run_cli(bng_cpp, model_name, work_dir / "cpp")
    assert test_path is not None, f"engine produced no trajectory: {err}"
    test_data, test_cols = compare.parse_gdat(test_path)
    assert test_data is not None, "could not parse engine .gdat"

    diff = compare.compare_trajectories(
        ref_data, ref_cols, test_data, test_cols, rtol=1e-6
    )
    assert diff.ok, f"ODE mismatch [{model_name}] (ref={ref_src}): {diff.summary()}"
