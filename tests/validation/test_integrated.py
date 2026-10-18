"""Detector controls for the linked monorepo integration campaign."""

import json
import sys
from itertools import combinations
from pathlib import Path

import pytest

from tests.validation import integrated


def test_pr_selection_covers_each_pair_of_integration_dimensions():
    full = integrated.generated_cases(full=True)
    selected = integrated.generated_cases()
    assert len(full) == 48 and len(selected) == 18
    assert len({c["id"] for c in full}) == len(full)
    for family in {c["family"] for c in full}:
        for left, right in combinations(("volume", "initial", "reverse", "atomize"), 2):
            assert {(c[left], c[right]) for c in selected if c["family"] == family} == {
                (c[left], c[right]) for c in full if c["family"] == family
            }


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
