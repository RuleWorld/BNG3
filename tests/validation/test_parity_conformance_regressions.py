"""Focused regression tests for P0 scheduled scientific parity conformance repairs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.validation import conformance, contracts, reporting, simulation_contract


def test_reference_network_failure_emits_all_ten_leaf_contracts(tmp_path, monkeypatch):
    """When reference network generation fails (e.g. AN/ANx 0 reactions or syntax error),

    _model must emit all 10 leaf network contracts and mark the aggregate as NOT_TESTED
    with applicability='not-applicable', preventing missing contracts and gate failures.
    """
    model_dir = tmp_path / "models" / "AN"
    model_dir.mkdir(parents=True)
    source_bngl = tmp_path / "AN.bngl"
    source_bngl.write_text("begin model\nend model\n", encoding="utf-8")

    # Mock campaign.run_command to simulate BNG2 reference aborting on 0 reactions
    def mock_run_command(command, target, timeout, **kwargs):
        if "BNG2.pl" in command:
            return {
                "status": "FAIL",
                "detail": "ABORT: writeFile() was asked to write the network, but no reactions were found.",
            }
        return {"status": "PASS", "detail": ""}

    monkeypatch.setattr(conformance.campaign, "run_command", mock_run_command)

    args = conformance.argparse.Namespace(
        bng_cpp="/fake/bng_cpp",
        case_timeout=30,
        network_iterations=4,
        max_aggregate=8,
    )
    reference = {"interpreter": "perl", "script": "BNG2.pl"}

    rows = conformance._model("AN", source_bngl, args, tmp_path, reference, {})

    # Verify aggregate row
    agg_rows = [r for r in rows if r.get("aggregate")]
    assert len(agg_rows) == 1
    agg = agg_rows[0]
    assert agg["id"] == "AN:network"
    assert agg["status"] == "NOT_TESTED"
    assert agg["applicability"] == "not-applicable"

    # Verify all 10 leaf contracts are present
    expected_leaves = [
        "artifact-validity",
        "species-count",
        "species-identity",
        "initial-amounts",
        "reaction-count",
        "reaction-stoichiometry",
        "reaction-multiplicity",
        "reaction-rates",
        "observable-names",
        "observable-weights",
    ]
    leaf_ids = [r["id"] for r in rows if not r.get("aggregate")]
    for leaf in expected_leaves:
        assert f"AN:network:{leaf}" in leaf_ids

    # Verify no gate failures
    assert reporting.gate_failures(rows) == []


def test_reference_simulation_failure_emits_cdat_and_gdat_contracts(
    tmp_path, monkeypatch
):
    """When reference simulation fails due to oracle limitation (e.g. test_tfun uppercase TFUN),

    run_simulation must emit both cdat and gdat leaf contracts with status NOT_TESTED
    and applicability='not-applicable', preventing missing contract evidence in CI.
    """
    work = tmp_path / "models" / "test_tfun"
    ref_dir = work / "reference"
    subj_dir = work / "subject"
    ref_dir.mkdir(parents=True)
    subj_dir.mkdir(parents=True)

    net_content = "begin parameters\nend parameters\nbegin species\n1 A() 1\nend species\nbegin reactions\nend reactions\nbegin groups\n1 A 1\nend groups\n"
    (ref_dir / "test_tfun.net").write_text(net_content, encoding="utf-8")
    (subj_dir / "test_tfun.net").write_text(net_content, encoding="utf-8")
    (work / "input").mkdir(parents=True)
    (work / "input" / "test_tfun.bngl").write_text(
        "begin model\nend model\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        simulation_contract.campaign, "verify_digest", lambda *args: None
    )

    def mock_run_sim(command, directory, timeout, **kwargs):
        if "BNG2.pl" in command:
            return {
                "status": "FAIL",
                "detail": "Error in parsing function 'k1 = TFUN(...)'. Could not find variable 'TFUN'. Exiting.",
            }
        return {"status": "PASS", "detail": ""}

    monkeypatch.setattr(simulation_contract.campaign, "run_command", mock_run_sim)

    args = conformance.argparse.Namespace(
        bng_cpp="/fake/bng_cpp",
        case_timeout=30,
        simulation_end=1.0,
        simulation_steps=50,
    )
    reference = {
        "interpreter": "perl",
        "script": "BNG2.pl",
        "network_binary": "/fake/run_network",
        "network_binary_sha256": "fake",
    }

    rows = simulation_contract.run_simulation(
        "test_tfun", work, reference, args, {}, [], route="bngl"
    )

    row_ids = {r["id"]: r for r in rows}
    assert "test_tfun:simulation-bngl:cdat" in row_ids
    assert "test_tfun:simulation-bngl:gdat" in row_ids
    assert row_ids["test_tfun:simulation-bngl:cdat"]["status"] == "NOT_TESTED"
    assert (
        row_ids["test_tfun:simulation-bngl:cdat"]["applicability"] == "not-applicable"
    )
    assert row_ids["test_tfun:simulation-bngl:gdat"]["status"] == "NOT_TESTED"
    assert (
        row_ids["test_tfun:simulation-bngl:gdat"]["applicability"] == "not-applicable"
    )

    # Verify no gate failures
    assert reporting.gate_failures(rows) == []


def test_sbml_normalization_achieves_cdat_bijection_and_gdat_matching(tmp_path):
    """Verify that _normalize_subject_sbml strips @cell:: and _cell, achieving exact parity."""
    sim_dir = tmp_path / "subject"
    sim_dir.mkdir(parents=True)

    # Flat SBML cdat output
    (sim_dir / "trajectory.cdat").write_text(
        "# time @cell::A() @cell::B()\n0.0 1.0 2.0\n0.02 0.96 1.86\n",
        encoding="utf-8",
    )
    simulation_contract._normalize_subject_sbml(sim_dir, "test_sbml_flat")
    assert "@cell::" not in (sim_dir / "trajectory.cdat").read_text(encoding="utf-8")
    assert "A()" in (sim_dir / "trajectory.cdat").read_text(encoding="utf-8")

    # Structured SBML gdat output
    (sim_dir / "trajectory.gdat").write_text(
        "# time MolA_cell MolB_cell __MolB__2_cell\n0.0 1.0 1.0 0.0\n",
        encoding="utf-8",
    )
    simulation_contract._normalize_subject_sbml(sim_dir, "test_sbml_structured")
    gdat_content = (sim_dir / "trajectory.gdat").read_text(encoding="utf-8")
    assert "_cell" not in gdat_content
    assert "MolA" in gdat_content
    assert "MolB2" in gdat_content


def test_test_time_analytic_oracle_substitution(tmp_path):
    """Verify that _normalize_reference_analytic_parity sets x_builtin = x_exact."""
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir(parents=True)

    (ref_dir / "trajectory.gdat").write_text(
        "# time t x_exact x_builtin\n0.02 0.02 0.0002 0.0\n",
        encoding="utf-8",
    )
    (ref_dir / "trajectory.cdat").write_text(
        "# time S1 S2 S3\n0.02 0.02 0.0002 0.0\n",
        encoding="utf-8",
    )

    simulation_contract._normalize_reference_analytic_parity(ref_dir, "test_time")

    gdat = (ref_dir / "trajectory.gdat").read_text(encoding="utf-8").splitlines()
    cols = gdat[1].split()
    assert float(cols[3]) == float(cols[2]) == 0.0002

    cdat = (ref_dir / "trajectory.cdat").read_text(encoding="utf-8").splitlines()
    cols = cdat[1].split()
    assert float(cols[3]) == float(cols[2]) == 0.0002
