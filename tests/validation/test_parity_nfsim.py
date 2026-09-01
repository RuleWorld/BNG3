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

import numpy as np
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
    diff = compare.compare_stochastic(
        native,
        test,
        min_ref_runs=n_runs,
        min_test_runs=n_runs,
    )
    assert diff.ok, f"NF vs native mismatch [{model_name}]: {diff.summary()}"


@pytest.mark.nf
@pytest.mark.parametrize("model_name", NF_MODELS)
def test_nf_ast_direct_matches_xml(model_name, api, work_dir, monkeypatch):
    """ast-direct construction must match the in-memory-XML construction."""
    t_end, n_steps, seed = 50.0, 50, 7

    monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
    monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
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


@pytest.mark.nf
@pytest.mark.slow
@pytest.mark.parametrize("model_name,t_end", [("motor", 0.2), ("tlbr", 2.0)])
def test_nf_fixed_seed_direct_matches_native_at_final_endpoint(
    model_name, t_end, api, work_dir
):
    """The direct API must retain native NFsim's final endpoint event semantics."""
    if not oracle_nfsim.nfsim_available():
        pytest.skip("native NFsim binary not found (set NFSIM_BIN)")

    # Source-derived from nfsim/test/motor and nfsim/test/tlbr.  Native
    # System::sim includes an event whose waiting time crosses the final output
    # boundary; this is intentionally a fixed-seed contract, not a tolerance
    # or ensemble substitute.
    xml_path = oracle_nfsim.write_model_xml(
        model_name, work_dir / "native-endpoint" / f"{model_name}.xml"
    )
    assert xml_path is not None
    native_path, stderr = oracle_nfsim.run_nfsim(
        xml_path,
        work_dir / "native-endpoint" / "run",
        t_end=t_end,
        n_steps=20,
        seed=1,
    )
    assert native_path is not None, stderr
    native_data, native_columns = compare.parse_gdat(native_path)
    assert native_data is not None

    direct = runner.run_api(
        model_name,
        method="nf",
        t_end=t_end,
        n_steps=20,
        seed=1,
    )

    assert direct.columns == native_columns
    assert direct.data.shape == native_data.shape
    assert np.allclose(direct.data[:, 0], native_data[:, 0], rtol=0.0, atol=1e-12)
    assert np.array_equal(direct.data[:, 1:], native_data[:, 1:])
