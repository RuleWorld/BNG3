"""Rate-law / local-function network parity.

The direct expression-vector/RHS gate remains open. This check compares the
action-aware BNG3 network and emitted rate laws with the independent BNG2
network for deterministic function-heavy fixtures.
"""

from __future__ import annotations

import pytest

from tests.validation import compare, corpus, oracle_perl, runner

# The Ising fixtures are SSA/NF models and are covered by the stochastic/NF
# gates; they are not deterministic network-rate fixtures.
EXPR_MODELS = [
    m for m in ("localfunc", "CaOscillate_Func", "michment") if corpus.resolve(m)
]


@pytest.mark.expressions
@pytest.mark.parametrize("model_name", EXPR_MODELS)
def test_expression_rate_parity(model_name, bng_cpp, work_dir):
    ref_path, ref_src = oracle_perl.net(model_name, work_dir / "perl")
    if ref_path is None:
        pytest.skip(f"no reference .net for {model_name}: {ref_src}")
    test_path, _, err = runner.run_cli(bng_cpp, model_name, work_dir / "cpp")
    assert test_path is not None, f"engine produced no network: {err}"
    ref_net = compare.parse_net(ref_path)
    test_net = compare.parse_net(test_path)
    assert ref_net is not None, f"could not parse reference network ({ref_src})"
    assert test_net is not None, "could not parse engine network"
    diff = compare.compare_net(ref_net, test_net)
    assert (
        diff.ok
    ), f"expression rate drift [{model_name}] (ref={ref_src}): {diff.summary()}"
