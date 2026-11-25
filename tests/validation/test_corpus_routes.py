"""Focused tests for authored-entry-point corpus routing and refusal separation."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.validation import compare, conformance, contracts, corpus_routes, reporting

REPO = Path(__file__).resolve().parents[2]


def test_classify_command_status_separates_refusal_invalid_timeout_and_failure():
    assert corpus_routes.classify_command_status({"status": "PASS"}) == (
        "PASS",
        "supported-execution",
    )
    assert corpus_routes.classify_command_status({"status": "TIMEOUT"}) == (
        "TIMEOUT",
        "timeout",
    )
    assert corpus_routes.classify_command_status({"status": "HARNESS_ERROR"}) == (
        "HARNESS_ERROR",
        "harness-error",
    )
    assert corpus_routes.classify_command_status(
        {
            "status": "FAIL",
            "detail": "NFsim param flag '-rnf' is not supported by the in-process adapter",
        }
    ) == ("UNSUPPORTED", "unsupported-construct")
    assert corpus_routes.classify_command_status(
        {"status": "FAIL", "detail": "line 10: semantic parse failed: syntax error"}
    ) == ("INVALID_INPUT", "invalid-input")
    assert corpus_routes.classify_command_status(
        {"status": "FAIL", "detail": "CVODE failed with flag -4"}
    ) == ("FAIL", "observed-failure")


def test_corpus_case_result_preserves_unsupported_and_invalid_input():
    refusal = conformance._corpus_case_result(
        "actin_branch_forFitToData",
        [
            {"id": "actin_branch_forFitToData:parse", "status": "PASS"},
            {
                "id": "actin_branch_forFitToData:authored-action",
                "status": "UNSUPPORTED",
                "detail": "NFsim param flag '-rnf' is not supported",
            },
        ],
        [
            "actin_branch_forFitToData:parse",
            "actin_branch_forFitToData:authored-action",
        ],
    )
    assert refusal["status"] == "UNSUPPORTED"
    assert refusal["supported_execution"] is False
    assert refusal["evidence_kind"] == "unsupported-construct"
    assert reporting.gate_failures([refusal]) == []

    invalid = conformance._corpus_case_result(
        "bad_case",
        [{"id": "bad_case:parse", "status": "INVALID_INPUT", "detail": "syntax error"}],
        ["bad_case:parse"],
    )
    assert invalid["status"] == "INVALID_INPUT"
    assert invalid["supported_execution"] is False
    assert invalid["evidence_kind"] == "invalid-input"


def test_species_columns_prefilter_matches_complex_names_and_rejects_missing():
    net = SimpleNamespace(
        species_by_index={
            1: "A(x~0,y)",
            2: "A(x~1,y!1).B(z!1)",
        }
    )
    mapped = contracts.species_columns(["time", "A(y,x~0)", "B(z!2).A(y!2,x~1)"], net)
    assert mapped == {1: "A(y,x~0)", 2: "B(z!2).A(y!2,x~1)"}

    with pytest.raises(ValueError, match="do not cover"):
        contracts.species_columns(["time", "A(x~0,y)"], net)

    with pytest.raises(ValueError, match="ambiguous"):
        contracts.species_columns(["time", "A(x~0,y)", "C()"], net)


def test_routed_nfsim_case_never_fakes_pass_without_verified_nfsim(
    tmp_path, monkeypatch
):
    source = REPO / "models/chemotaxisAdaptation/AN.bngl"
    xml_text = (
        '<sbml xmlns="http://www.sbml.org/sbml/level3" level="3" version="1">'
        '<model id="AN"><ListOfMoleculeTypes/><ListOfSpecies/>'
        "<ListOfReactionRules/><ListOfObservables/></model></sbml>"
    )

    def fake_run_command(
        command, directory, timeout, *, required=(), env=None, cwd=None
    ):
        directory.mkdir(parents=True, exist_ok=True)
        for req in required:
            if req.endswith(".xml"):
                (directory / req).write_text(xml_text, encoding="utf-8")
        return {"status": "PASS", "detail": ""}

    monkeypatch.setattr(corpus_routes.campaign, "run_command", fake_run_command)
    args = Namespace(
        bng_cpp=Path("/fake/bng_cpp"),
        case_timeout=10,
        simulate=True,
        net_reload=True,
    )
    rows = corpus_routes.run_case(
        "AN",
        source,
        args,
        tmp_path,
        {"bionetgen": {"interpreter": "perl", "script": "BNG2.pl"}},
        {},
        conformance._model,
    )
    expected = corpus_routes.expected_contract_ids("AN", simulate=True, net_reload=True)
    summary = conformance._corpus_case_result("AN", rows, expected)
    assert summary["status"] == "NOT_TESTED"
    assert summary["supported_execution"] is False
    assert "AN:nfsim:gdat" in summary["blocked_by"]


def test_routed_refusal_case_marks_rnf_unsupported(tmp_path, monkeypatch):
    source = REPO / "models/actin/actin_branch_forFitToData.bngl"

    def fake_run_command(
        command, directory, timeout, *, required=(), env=None, cwd=None
    ):
        directory.mkdir(parents=True, exist_ok=True)
        if "--check" in command:
            return {"status": "PASS", "detail": ""}
        return {
            "status": "FAIL",
            "detail": "NFsim param flag '-rnf' is not supported by the in-process adapter",
        }

    monkeypatch.setattr(corpus_routes.campaign, "run_command", fake_run_command)
    args = Namespace(
        bng_cpp=Path("/fake/bng_cpp"),
        case_timeout=10,
        simulate=True,
        net_reload=True,
    )
    rows = corpus_routes.run_case(
        "actin_branch_forFitToData",
        source,
        args,
        tmp_path,
        {},
        {},
        conformance._model,
    )
    expected = corpus_routes.expected_contract_ids(
        "actin_branch_forFitToData", simulate=True, net_reload=True
    )
    summary = conformance._corpus_case_result(
        "actin_branch_forFitToData", rows, expected
    )
    assert summary["status"] == "UNSUPPORTED"
    assert summary["supported_execution"] is False


def test_post_action_amount_evaluation_computes_set_plus_add_exactly(tmp_path):
    net = tmp_path / "michment_cont.net"
    net.write_text(
        "begin parameters\n  1 S0 100\nend parameters\n"
        "begin species\n  1 S(a~0,c~R) 102.302255180226\nend species\n",
        encoding="utf-8",
    )
    updates = corpus_routes._eval_post_action_amounts(
        REPO / "models/michment_cont.bngl", net
    )
    assert updates["S(a~0,c~R)"] == pytest.approx(200.0)
    patched = tmp_path / "patched.net"
    corpus_routes._patch_net_species(net, patched, updates)
    assert "1 S(a~0,c~R) 200" in patched.read_text(encoding="utf-8")


def test_selection_cases_cover_all_expected_routes():
    selection = json.loads((REPO / "provenance/corpus/selection.json").read_text())
    for row in selection["records"]:
        cid = row["id"]
        custom = corpus_routes.expected_contract_ids(
            cid, simulate=True, net_reload=True
        )
        if custom is not None:
            assert f"{cid}:parse" in custom


def test_corpus_resume_allows_no_observables_but_rejects_unexecuted_not_tested(
    tmp_path,
):
    from tests.validation import corpus_resume

    identity = corpus_resume.case_identity(
        "blbr",
        source_sha256="sha256:" + "a" * 64,
        candidate_sha256="sha256:" + "b" * 64,
        oracle_identity={},
        configuration={},
        expected_contract_ids=["blbr:parse", "blbr:simulation-bngl:gdat"],
    )
    rows = [
        {"id": "blbr:parse", "status": "PASS"},
        {
            "id": "blbr:simulation-bngl:gdat",
            "status": "NOT_TESTED",
            "applicability": "no-observables",
        },
    ]
    corpus_resume.save(tmp_path, identity, rows)
    loaded, reason = corpus_resume.load(tmp_path, identity)
    assert reason == "hit" and loaded == rows

    rows_incomplete = [
        {"id": "blbr:parse", "status": "PASS"},
        {"id": "blbr:simulation-bngl:gdat", "status": "NOT_TESTED"},
    ]
    corpus_resume.save(tmp_path, identity, rows_incomplete)
    loaded, reason = corpus_resume.load(tmp_path, identity)
    assert reason == "invalid" and loaded is None
