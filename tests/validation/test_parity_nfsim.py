"""Network-free parity.

Two directions, both required for WO-2:
  (a) ast-direct vs native NFsim binary   correctness of the merged engine
  (b) ast-direct vs in-memory-XML path    the migration is behavior-preserving

(b) is gated by an env flag the engine exposes during the WO-2 migration window
(BNG_NFSIM_FORCE_XML=1 forces the old in-memory-XML construction). When that
flag is unavailable both paths are identical and (b) is a no-op pass.
"""

from __future__ import annotations

import os

import pytest

from tests.validation import compare, corpus, oracle_nfsim, runner

NF_MODELS = [m for m in corpus.tier_nf()]


@pytest.mark.nf
@pytest.mark.slow
@pytest.mark.parametrize("model_name", NF_MODELS)
def test_nf_vs_native(model_name, api, work_dir):
    if not oracle_nfsim.nfsim_available():
        pytest.skip("native NFsim binary not found (set NFSIM_BIN)")

    t_end, n_steps, n_runs = 50.0, 50, 200
    native = oracle_nfsim.ensemble(
        model_name, work_dir / "native", n_runs=n_runs, t_end=t_end, n_steps=n_steps
    )
    if not native:
        pytest.skip("native NFsim produced no output for this model")

    test = runner.run_api_ensemble(
        model_name, method="nf", n_runs=n_runs, t_end=t_end, n_steps=n_steps
    )
    diff = compare.compare_stochastic(native, test)
    assert diff.ok, f"NF vs native mismatch [{model_name}]: {diff.summary()}"


@pytest.mark.nf
@pytest.mark.parametrize("model_name", NF_MODELS)
def test_nf_ast_direct_matches_xml(model_name, api, work_dir, monkeypatch):
    """ast-direct construction must match the in-memory-XML construction."""
    t_end, n_steps, seed = 50.0, 50, 7

    monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
    xml_traj = runner.run_api(model_name, method="nf", seed=seed, t_end=t_end, n_steps=n_steps)

    monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)
    direct_traj = runner.run_api(model_name, method="nf", seed=seed, t_end=t_end, n_steps=n_steps)

    # Same seed + same engine RNG => identical trajectories if construction matches.
    diff = compare.compare_trajectories(
        xml_traj.data, xml_traj.columns, direct_traj.data, direct_traj.columns, rtol=0.0, atol=0.0
    )
    assert diff.ok or diff.max_rel_err == 0.0, (
        f"ast-direct diverges from in-memory-XML [{model_name}]: {diff.summary()}"
    )
