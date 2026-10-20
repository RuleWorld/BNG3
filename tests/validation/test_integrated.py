"""Detector controls for the linked monorepo integration campaign."""

import json
import sys
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tests.validation import integrated, integrated_source


def test_pr_selection_covers_each_pair_of_integration_dimensions():
    full = integrated.generated_cases(full=True)
    selected = integrated.generated_cases()
    baseline_full = [case for case in full if not case.get("transform")]
    baseline_selected = [case for case in selected if not case.get("transform")]
    assert len(full) == 61 and len(selected) == 25
    assert len({c["id"] for c in full}) == len(full)
    assert len([case for case in selected if case.get("transform")]) == 7
    assert len([case for case in full if case.get("transform")]) == 13
    for family in {c["family"] for c in baseline_full}:
        for left, right in combinations(("volume", "initial", "reverse", "atomize"), 2):
            assert {
                (c[left], c[right]) for c in baseline_selected if c["family"] == family
            } == {(c[left], c[right]) for c in baseline_full if c["family"] == family}


def test_focused_qualification_registries_exclude_the_other_final_stage():
    boundary = integrated.expected_contract_ids(
        [], include_boundaries=True, include_graph_identity=False
    )
    graph = integrated.expected_contract_ids(
        [], include_boundaries=False, include_graph_identity=True
    )
    assert "campaign:boundaries" in boundary
    assert "campaign:graph-identity" not in boundary
    assert "campaign:graph-identity" in graph
    assert "campaign:boundaries" not in graph


def test_generated_source_validation_rejects_invalid_input_before_scoring(monkeypatch):
    class Error:
        def getMessage(self):
            return "invalid generated source"

        def getSeverity(self):
            return 2

    class Document:
        def checkConsistency(self):
            pass

        def getNumErrors(self):
            return 1

        def getError(self, _index):
            return Error()

        def getModel(self):
            return object()

    fake_libsbml = SimpleNamespace(
        readSBMLFromString=lambda _source: Document(), LIBSBML_SEV_ERROR=2
    )
    monkeypatch.setitem(sys.modules, "libsbml", fake_libsbml)

    status, detail = integrated_source.validate_sbml_source("<sbml/>")
    assert status == "INVALID_INPUT"
    assert "invalid generated source" in detail


def test_integrated_case_contract_requires_source_validation_and_independent_oracle():
    case = integrated.generated_cases()[0]
    ids = integrated.expected_contract_ids([case])
    assert f"{case['id']}:source-validation" in ids
    assert f"{case['id']}:source-sbml-oracle" in ids
    for check in (
        "source-compiled-rate-multiset",
        "compiled-net-rate-multiset",
        "net-bngxml-rate-coefficient",
    ):
        assert f"{case['id']}:rate-trace:{check}" in ids


def test_concentration_oracle_rejects_missing_or_duplicated_volume_factor():
    case = next(
        case
        for case in integrated.generated_cases()
        if case.get("transform") == "concentration-coordinate" and case["volume"] == 3
    )
    from tests.validation.integrated_cases import TIMES, RATE, expected_source_species

    expected, species = expected_source_species(case)
    correct = np.column_stack([TIMES, expected])
    assert (
        integrated_source.source_trajectory_difference(correct, case, species) is None
    )

    initial_concentration = case["initial"] / case["volume"]
    for effective_rate in (RATE / case["volume"], RATE * case["volume"]):
        amount_a = initial_concentration * np.exp(-effective_rate * TIMES)
        wrong = np.column_stack([TIMES, amount_a, initial_concentration - amount_a])
        assert integrated_source.source_trajectory_difference(wrong, case, species)


def test_roadrunner_selections_and_issue_links_follow_source_coordinates():
    concentration = next(
        case
        for case in integrated.generated_cases()
        if case.get("transform") == "concentration-coordinate"
    )
    function = next(
        case
        for case in integrated.generated_cases()
        if case.get("transform") == "function-shadowing"
    )
    assert integrated_source.source_selection_names(concentration, ["A", "B"]) == [
        "[A]",
        "[B]",
    ]
    assert integrated_source.source_selection_names(function, ["A", "B"]) == [
        "A",
        "B",
    ]
    assert integrated._candidate_issue_ids(function, "api-source-dynamics") == [143]
    assert integrated._candidate_issue_ids(concentration, "nf-independent") == [151]
    assert integrated._candidate_issue_ids(concentration, "api-source-dynamics") == [
        161
    ]
    assert integrated._candidate_issue_ids(concentration, "source-sbml-oracle") is None


def test_missing_stage_output_blocks_consumers_but_not_independent_routes(tmp_path):
    rows = []
    missing = integrated.run_stage(
        "case",
        "producer",
        [sys.executable, "-c", "pass"],
        tmp_path / "producer",
        rows,
        required=["missing.bngl"],
    )
    assert missing["status"] == "HARNESS_ERROR"
    blocked = integrated.run_stage(
        "case",
        "consumer",
        [sys.executable, "-c", "raise Exception('must not run')"],
        tmp_path / "consumer",
        rows,
        dependencies=[missing],
    )
    assert blocked["status"] == "NOT_TESTED"
    assert blocked["blocked_by"] == ["case:producer"]
    assert not (tmp_path / "consumer").exists()
    independent = integrated.run_stage(
        "case",
        "independent",
        [sys.executable, "-c", "pass"],
        tmp_path / "independent",
        rows,
    )
    assert independent["status"] == "PASS"
    assert json.loads((tmp_path / "producer/command.json").read_text())["command"]


def test_missing_oracle_emits_actionable_failure_packet(tmp_path):
    output = tmp_path / "report"
    flags = []
    for name in (
        "bng-cpp",
        "bng2-root",
        "nfsim-root",
        "nfsim-binary",
        "pybionetgen-root",
        "pybionetgen-python",
    ):
        flags += ["--" + name, str(tmp_path / "missing")]
    for name in ("bng2-network-sha256", "nfsim-sha256"):
        flags += ["--" + name, "0" * 64]
    assert integrated.main(flags + ["--report-dir", str(output)]) == 1
    report = json.loads((output / "report.json").read_text())
    assert report["results"][0]["status"] == "HARNESS_ERROR"
    tasks = json.loads((output / "investigation-tasks.json").read_text())
    assert len(tasks) == 1
    assert tasks[0]["reproduce_command"]
    assert "--report-dir" in tasks[0]["reproduce_command"]
    assert Path(tasks[0]["reproduce_cwd"]).is_absolute()
    assert (output / "artifacts.json").is_file()


def test_unknown_case_is_rejected_instead_of_running_an_empty_green_matrix(tmp_path):
    with pytest.raises(SystemExit):
        flags = []
        for name in (
            "bng-cpp",
            "bng2-root",
            "nfsim-root",
            "nfsim-binary",
            "pybionetgen-root",
            "pybionetgen-python",
        ):
            flags += ["--" + name, str(tmp_path / "missing")]
        for name in ("bng2-network-sha256", "nfsim-sha256"):
            flags += ["--" + name, "0" * 64]
        integrated.main(flags + ["--case", "typo", "--report-dir", str(tmp_path)])
    assert not (tmp_path / "report.json").exists()


def test_successful_processes_without_semantic_evidence_cannot_pass_strict_gate(
    tmp_path,
):
    from tests.validation import ci_report

    case = integrated.generated_cases()[0]
    rows = [
        dict(id=f"{case['id']}:{stage}", stage=stage, status="PASS", detail="")
        for stage in integrated.PROCESS_STAGES
    ]
    report = dict(
        results=rows, expected_contract_ids=integrated.expected_contract_ids([case])
    )
    assert ci_report.publish(report, tmp_path / "summary.md", strict=True) == 1


def test_corrupted_handoff_keeps_first_divergent_value(tmp_path):
    reference, subject = tmp_path / "reference.gdat", tmp_path / "subject.gdat"
    reference.write_text("# time A B\n0 20 0\n1 10 10\n2 5 15\n")
    subject.write_text("# time A B\n0 20 0\n1 11 9\n2 5 15\n")
    # The requested grid is a separate contract; use a matching three-point
    # request here so the injected numeric error reaches the value comparator.
    import numpy as np
    from unittest.mock import patch

    rows = []
    with patch.object(integrated, "TIMES", np.array([0, 1, 2])):
        integrated._compare(
            "case",
            "handoff",
            rows,
            [dict(id="producer", status="PASS")],
            reference,
            subject,
        )
    failure = next(r for r in rows if r["check"] == "gdat.values")
    assert failure["status"] == "FAIL"
    assert failure["first_difference"]["time"] == 1
    assert failure["first_difference"]["column"] == "A"


def test_reversible_stochastic_controls_detect_conservation_and_alias_corruption(
    tmp_path,
):
    import numpy as np

    case = next(c for c in integrated.generated_cases() if c["family"] == "reversible")
    expected, names = integrated.expected_trajectory(case)
    data = np.tile(expected[0], (len(integrated.TIMES), 1))
    data[:, 0] = integrated.TIMES
    path = tmp_path / "nf.gdat"
    np.savetxt(path, data, header=" ".join(names))
    rows = []
    integrated._nf_invariants(case, "nf", path, rows, dict(id="nf", status="PASS"))
    assert all(r["status"] == "PASS" for r in rows)
    data[1, names.index("B")] += 1
    np.savetxt(path, data, header=" ".join(names))
    rows = []
    integrated._nf_invariants(case, "nf", path, rows, dict(id="nf", status="PASS"))
    assert (
        next(r for r in rows if r["check"] == "observable-aliases")["status"] == "FAIL"
    )
    assert (
        next(r for r in rows if r["check"] == "invariant.conserved-total")["status"]
        == "FAIL"
    )


def test_adversarial_registry_can_be_selected_without_other_campaigns():
    ids = integrated.expected_contract_ids(
        [],
        include_boundaries=False,
        include_graph_identity=False,
        include_bngir_adversarial=True,
    )
    assert "campaign:bngir-adversarial" in ids
    assert "campaign:graph-identity" not in ids
    assert "campaign:boundaries" not in ids
    assert len(ids) > 10


def test_checks_preserve_cross_stage_prerequisite_ids():
    rows = []
    integrated._checks(
        "case",
        "worker-identity",
        [
            {
                "check": "same-build",
                "status": "NOT_TESTED",
                "blocked_by": ["case:bngir-v02"],
            }
        ],
        rows,
        [],
    )
    assert rows[0]["blocked_by"] == ["case:bngir-v02"]


def test_every_focused_qualification_flag_is_defined_and_selects_one_family(
    tmp_path,
):
    """A focused flag the parser does not define crashes the whole campaign.

    The campaign consulted ``args.stochastic_parity_only`` and
    ``args.api_surface_only`` without ever defining them, so every campaign run
    died with an ``AttributeError`` before a single check was executed.  Each
    focused flag must now be a real argument, and a focused run must select
    exactly one family: its own.
    """
    from tests.validation import integrated_extensions

    base = [
        "--bng-cpp",
        str(tmp_path / "bng_cpp"),
        "--bng2-root",
        str(tmp_path / "bng2"),
        "--nfsim-root",
        str(tmp_path / "nfsim"),
        "--nfsim-binary",
        str(tmp_path / "NFsim"),
        "--pybionetgen-root",
        str(tmp_path / "pybng"),
        "--pybionetgen-python",
        str(tmp_path / "python"),
        "--bng2-network-sha256",
        "0" * 64,
        "--nfsim-sha256",
        "0" * 64,
        "--report-dir",
        str(tmp_path / "report"),
    ]
    # One campaign run reads every focused flag, so an undefined flag fails
    # here instead of silently disabling a family.
    assert integrated.main(base) == 1
    report = json.loads(
        (tmp_path / "report" / "report.json").read_text(encoding="utf-8")
    )
    preflight = [
        row for row in report["results"] if row.get("stage") == "integration-preflight"
    ]
    assert preflight
    assert preflight[0]["status"] == "HARNESS_ERROR"
    assert "AttributeError" not in preflight[0]["detail"]

    for name, dest in integrated.FOCUS_FLAGS.items():
        args = SimpleNamespace(
            **{other: other == dest for other in integrated.FOCUS_FLAGS.values()}
        )
        selection = integrated.focus_selection(args)
        included = [key for key, value in selection.items() if value]
        assert included == [f"include_{name}"], name
    unselected = SimpleNamespace(
        **{dest: False for dest in integrated.FOCUS_FLAGS.values()}
    )
    selection = integrated.focus_selection(unselected)
    assert all(selection.values())
    assert set(selection) == {f"include_{name}" for name in integrated.FOCUS_FLAGS}
    assert set(integrated_extensions.OPERATIONS) == {
        "boundaries",
        "protocol",
        "nf-marginals",
        "graph-identity",
        "bngir-adversarial",
        "quantity-laws",
        "export-format-tier",
        "netrule-execution",
        "bngsim-boundary",
        "jax-backend-measurement",
        "api-surface",
        "stochastic-parity",
        "semantic-identity",
        "graph-differential",
    }
