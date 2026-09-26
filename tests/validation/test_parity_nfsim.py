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
from tests.validation.strict import require_oracle

NF_MODELS = [m for m in corpus.tier_nf()]


@pytest.mark.nf
@pytest.mark.slow
@pytest.mark.parametrize("model_name", NF_MODELS)
def test_nf_vs_native(model_name, api, work_dir):
    require_oracle(
        oracle_nfsim.nfsim_available(),
        "native NFsim binary not found (set NFSIM_BIN)",
    )

    t_end, n_steps, n_runs = 50.0, 50, 200
    native = oracle_nfsim.ensemble(
        model_name, work_dir / "native", n_runs=n_runs, t_end=t_end, n_steps=n_steps
    )
    require_oracle(bool(native), "native NFsim produced no output for this model")

    test = runner.run_api_ensemble(
        model_name,
        method="nf",
        n_runs=n_runs,
        t_end=t_end,
        n_steps=n_steps,
        expected_construction_path="direct",
    )
    diff = compare.compare_stochastic(
        native,
        test,
        min_ref_runs=n_runs,
        min_test_runs=n_runs,
    )
    assert diff.ok, f"NF vs native mismatch [{model_name}]: {diff.summary()}"


def test_nf_fixed_seed_direct_matches_native_at_final_endpoint(api, work_dir):
    """Pin one seed and compare direct BNG3 construction with native NFsim."""
    model_name = "simple_system"
    t_end, n_steps, seed = 50.0, 50, 7
    xml_path = oracle_nfsim.write_model_xml(
        model_name, work_dir / "native" / f"{model_name}.xml"
    )
    require_oracle(xml_path is not None, "BNG3 did not emit native-oracle BNG-XML")
    assert xml_path is not None

    native_path, native_error = oracle_nfsim.run_nfsim(
        xml_path,
        work_dir / "native",
        t_end=t_end,
        n_steps=n_steps,
        seed=seed,
    )
    require_oracle(
        native_path is not None,
        f"native NFsim produced no fixed-seed output: {native_error}",
    )
    assert native_path is not None
    native_data, native_columns = compare.parse_gdat(native_path)
    require_oracle(
        native_data is not None and native_columns is not None,
        "native NFsim fixed-seed output could not be parsed",
    )
    assert native_data is not None and native_columns is not None

    direct = runner.run_api(
        model_name,
        method="nf",
        seed=seed,
        t_end=t_end,
        n_steps=n_steps,
    )
    assert direct.construction_path == "direct"
    diff = compare.compare_trajectories(
        native_data,
        native_columns,
        direct.data,
        direct.columns,
        rtol=0.0,
        atol=0.0,
    )
    assert (
        diff.ok or diff.max_rel_err == 0.0
    ), f"fixed-seed direct/native NFsim mismatch: {diff.summary()}"


@pytest.mark.nf
@pytest.mark.parametrize("model_name", NF_MODELS)
def test_nf_ast_direct_matches_xml(model_name, api, work_dir, monkeypatch):
    """ast-direct construction must match the in-memory-XML construction."""
    t_end, n_steps, seed = 50.0, 50, 7

    monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
    monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
    xml_traj = runner.run_api(
        model_name, method="nf", seed=seed, t_end=t_end, n_steps=n_steps
    )

    monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)
    # The direct leg must not be allowed to fall back to XML.  Otherwise this
    # shadow test can degenerate into XML-vs-XML and report a false green when
    # direct construction regresses.
    monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)
    direct_traj = runner.run_api(
        model_name, method="nf", seed=seed, t_end=t_end, n_steps=n_steps
    )

    assert xml_traj.construction_path == "in-memory-xml"
    assert direct_traj.construction_path == "direct"

    # Same seed + same engine RNG => identical trajectories if construction matches.
    diff = compare.compare_trajectories(
        xml_traj.data,
        xml_traj.columns,
        direct_traj.data,
        direct_traj.columns,
        rtol=0.0,
        atol=0.0,
    )
    assert (
        diff.ok or diff.max_rel_err == 0.0
    ), f"ast-direct diverges from in-memory-XML [{model_name}]: {diff.summary()}"
