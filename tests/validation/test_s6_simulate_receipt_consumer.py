"""Strict consumer tests for the bounded S6 action.simulate receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from tests.validation import issue_queue

ROWS = (
    "action.simulate.t_start",
    "action.simulate.t_end",
    "action.simulate.n_steps",
    "action.simulate.sample_times",
    "action.simulate.continue",
    "action.simulate.method",
    "action.simulate.atol",
    "action.simulate.rtol",
)
SOURCE_REVISION = "a" * 40
BNG2_REVISION = "9601746f8884ed19ab2acea49fe87fc4660ace46"
BNG2_SHA256 = "b" * 64
PRODUCT_SHA256 = "c" * 64
ORACLE = "pinned BNG2 plus the analytic first-order conversion law; SSA scope is invariant-only"
SCOPE = "default, explicit, invalid, and one row-relevant interaction; only the admitted ODE/SSA pair is attempted"
LAW = (
    "For A -> B at k=0.4 from A(0)=10, B(0)=0, "
    "A(t)=10*exp(-0.4*t), B(t)=10-A(t). ODE observable error bound: "
    "1e-6 absolute; schedule assertions are exact apart from 1e-12 time representation."
)
SSA_SCOPE = (
    "The admitted SSA case checks dispatch, requested schedule, integer populations, "
    "and A+B conservation only. It does not claim distributional or pathwise parity."
)
SCENARIOS = ("default", "explicit", "invalid", "interaction")
TIMES = {
    ("action.simulate.t_start", "default"): [0, 0.25, 0.5, 0.75, 1],
    ("action.simulate.t_start", "explicit"): [0.5, 0.75, 1, 1.25, 1.5],
    ("action.simulate.t_start", "interaction"): [0.5, 0.75, 1, 1.25, 1.5],
    ("action.simulate.t_end", "default"): [0, 0.5, 1],
    ("action.simulate.t_end", "explicit"): [0, 0.5, 1, 1.5],
    ("action.simulate.t_end", "interaction"): [0, 0.4, 0.8, 1],
    ("action.simulate.n_steps", "default"): [0, 1],
    ("action.simulate.sample_times", "explicit"): [0, 0.25, 0.75],
    ("action.simulate.sample_times", "interaction"): [0, 0.4, 0.8, 1],
    ("action.simulate.continue", "default"): [0, 0.25, 0.5],
}


def _trajectory(row: str, scenario: str) -> dict:
    times = TIMES.get((row, scenario), [0, 0.25, 0.5, 0.75, 1])
    values = []
    for time in times:
        if row == "action.simulate.method" and scenario == "interaction":
            counts = [10, 9, 7, 5, 4][len(values)]
            values.append([time, counts, 10 - counts])
        else:
            relative_start = (
                0.5
                if row == "action.simulate.t_start"
                and scenario in {"explicit", "interaction"}
                else 0
            )
            a_count = 10 * np.exp(-0.4 * (time - relative_start))
            values.append([time, a_count, 10 - a_count])
    return {
        "shape": [len(values), 3],
        "columns": ["time", "A_count", "B_count"],
        "values": values,
    }


def _outcome(row: str, scenario: str, engine: str) -> dict:
    rejected = scenario == "invalid" or (
        row == "action.simulate.method" and scenario == "default"
    )
    trajectory = None if rejected else _trajectory(row, scenario)
    return {
        "execution_status": "REJECTED" if rejected else "PRODUCED",
        "rejected": rejected,
        "return_code": 1 if rejected else 0,
        "output": None if rejected else f"{engine}.gdat",
        "output_sha256": None if rejected else "d" * 64,
        "trajectory": trajectory,
        "transcript_sha256": "e" * 64,
    }


def _contract() -> dict:
    return {
        "schema_version": 1,
        "source": {
            "repository": "RuleWorld/bionetgen",
            "revision": BNG2_REVISION,
            "path": "bng2/Perl2/BNGAction.pm",
            "sha256": BNG2_SHA256,
        },
        "oracle": {
            "identity": "pinned BNG2 executable at source revision above; separately derived mass-action law",
            "law": LAW,
            "stochastic_scope": SSA_SCOPE,
        },
        "rows": {
            row: {scenario: f"declared {scenario} case" for scenario in SCENARIOS}
            for row in ROWS
        },
    }


def _receipts(tmp_path: Path) -> tuple[Path, dict]:
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir(parents=True)
    for row in ROWS:
        receipt = {
            "row_id": row,
            "selector": (
                "tests/validation/release/cases/sprint-s6-simulate-options/"
                f"test_simulate_options.py::test_simulate_option_contract[{row}]"
            ),
            "source": {
                "revision": BNG2_REVISION,
                "path": "bng2/Perl2/BNGAction.pm",
                "sha256": BNG2_SHA256,
            },
            "product": {
                "revision": SOURCE_REVISION,
                "bng_cpp_sha256": PRODUCT_SHA256,
            },
            "oracle": ORACLE,
            "scope": SCOPE,
            "scenarios": [
                {
                    "name": scenario,
                    "source_sha256": "f" * 64,
                    "expected_rejection": scenario == "invalid"
                    or (row == "action.simulate.method" and scenario == "default"),
                    "bng2": _outcome(row, scenario, "bng2"),
                    "bng3": _outcome(row, scenario, "bng3"),
                    "status": "PASS",
                    "failures": [],
                }
                for scenario in SCENARIOS
            ],
            "status": "PASS",
            "failures": [],
        }
        (receipt_dir / f"{row}.json").write_text(json.dumps(receipt))
    return receipt_dir, _contract()


def test_s6_consumer_requires_and_maps_all_eight_exact_rows(tmp_path):
    receipt_dir, contract = _receipts(tmp_path)

    report = issue_queue.s6_simulate_receipt_report(
        receipt_dir, SOURCE_REVISION, contract, artifact_run_id="4145"
    )

    assert report["source"] == {"revision": SOURCE_REVISION, "dirty": False}
    assert report["references"]["bionetgen"] == {
        "revision": BNG2_REVISION,
        "sha256": BNG2_SHA256,
    }
    assert report["artifact"]["workflow_run_id"] == "4145"
    assert [row["id"] for row in report["results"]] == list(ROWS)
    assert all(row["status"] == "PASS" for row in report["results"])
    assert [row["check"] for row in report["results"]] == [
        f"release-capability[{row}] (new parameterized case)" for row in ROWS
    ]
    assert all(row["related_issues"] == [140] for row in report["results"])
    assert all(row["supported_execution"] for row in report["results"])
    issue = {
        "number": 140,
        "title": "Simulate options",
        "state": "OPEN",
        "body": "## Acceptance criteria\n- [ ] `release-actions`: all actions pass.\n",
    }
    queue = issue_queue.build_queue([issue], [report], SOURCE_REVISION)[0]
    assert queue["outcomes"] == {"PASS": len(ROWS)}
    assert queue["disposition"] == "PARTIAL_EXECUTION"
    assert queue["closure_eligible"] is False
    dashboard = issue_queue.acceptance_dashboard([queue], {"obligations": []}, [])[0]
    assert dashboard["acceptance_criteria"][0]["evidence_status"] != "PASS"


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda r: r.update(row_id="action.simulate.unknown"), "row identity"),
        (lambda r: r["product"].update(revision="b" * 40), "stale"),
        (lambda r: r["source"].update(sha256="bad"), "oracle"),
        (lambda r: r.update(status="SKIP"), "did not pass"),
        (lambda r: r["scenarios"].pop(), "missing or duplicated"),
        (lambda r: r["scenarios"][0].update(status="TIMEOUT"), "scenario"),
        (
            lambda r: r["scenarios"][0]["bng3"].update(transcript_sha256="bad"),
            "identity",
        ),
    ],
)
def test_s6_consumer_rejects_stale_incomplete_or_nonpassing_receipts(
    tmp_path, mutate, message
):
    receipt_dir, contract = _receipts(tmp_path)
    path = receipt_dir / f"{ROWS[0]}.json"
    receipt = json.loads(path.read_text())
    mutate(receipt)
    path.write_text(json.dumps(receipt))

    with pytest.raises(ValueError, match=message):
        issue_queue.s6_simulate_receipt_report(receipt_dir, SOURCE_REVISION, contract)


def test_s6_consumer_rejects_missing_duplicate_extra_and_bad_budget(tmp_path):
    receipt_dir, contract = _receipts(tmp_path)
    (receipt_dir / f"{ROWS[0]}.json").unlink()
    with pytest.raises(ValueError, match="exactly eight"):
        issue_queue.s6_simulate_receipt_report(receipt_dir, SOURCE_REVISION, contract)

    receipt_dir, contract = _receipts(tmp_path / "duplicate")
    duplicate = json.loads((receipt_dir / f"{ROWS[0]}.json").read_text())
    duplicate["scenarios"].append(duplicate["scenarios"][0])
    (receipt_dir / f"{ROWS[0]}.json").write_text(json.dumps(duplicate))
    with pytest.raises(ValueError, match="missing or duplicated"):
        issue_queue.s6_simulate_receipt_report(receipt_dir, SOURCE_REVISION, contract)

    receipt_dir, contract = _receipts(tmp_path / "extra")
    (receipt_dir / "unexpected.json").write_text("{}")
    with pytest.raises(ValueError, match="exactly eight"):
        issue_queue.s6_simulate_receipt_report(receipt_dir, SOURCE_REVISION, contract)

    receipt_dir, contract = _receipts(tmp_path / "budget")
    contract["rows"].pop(ROWS[-1])
    with pytest.raises(ValueError, match="exactly the eight"):
        issue_queue.s6_simulate_receipt_report(receipt_dir, SOURCE_REVISION, contract)


def test_s6_consumer_rejects_contract_oracle_drift(tmp_path):
    receipt_dir, contract = _receipts(tmp_path)
    contract["oracle"]["law"] = "A different law"

    with pytest.raises(ValueError, match="independent oracle"):
        issue_queue.s6_simulate_receipt_report(receipt_dir, SOURCE_REVISION, contract)

    receipt_dir, contract = _receipts(tmp_path / "revision")
    contract["source"]["revision"] = "0" * 40

    with pytest.raises(ValueError, match="source lock"):
        issue_queue.s6_simulate_receipt_report(receipt_dir, SOURCE_REVISION, contract)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda r: r["scenarios"][1]["bng3"]["trajectory"]["values"][1].__setitem__(
                1, 99
            ),
            "analytic law",
        ),
        (
            lambda r: r["scenarios"][1]["bng2"].update(output_sha256=None),
            "output identity",
        ),
    ],
)
def test_s6_consumer_independently_checks_ode_law_and_raw_output_identity(
    tmp_path, mutate, message
):
    receipt_dir, contract = _receipts(tmp_path)
    path = receipt_dir / f"{ROWS[0]}.json"
    receipt = json.loads(path.read_text())
    mutate(receipt)
    path.write_text(json.dumps(receipt))

    with pytest.raises(ValueError, match=message):
        issue_queue.s6_simulate_receipt_report(receipt_dir, SOURCE_REVISION, contract)


def test_s6_consumer_checks_ssa_invariants_without_claiming_pathwise_parity(tmp_path):
    receipt_dir, contract = _receipts(tmp_path)
    path = receipt_dir / "action.simulate.method.json"
    receipt = json.loads(path.read_text())
    receipt["scenarios"][3]["bng3"]["trajectory"]["values"][1][2] = 88
    path.write_text(json.dumps(receipt))

    with pytest.raises(ValueError, match="SSA invariants"):
        issue_queue.s6_simulate_receipt_report(receipt_dir, SOURCE_REVISION, contract)


def test_s6_nonincreasing_time_control_accepts_only_refusal_or_initial_row(tmp_path):
    receipt_dir, contract = _receipts(tmp_path)
    path = receipt_dir / "action.simulate.t_start.json"
    receipt = json.loads(path.read_text())
    for engine in ("bng2", "bng3"):
        receipt["scenarios"][2][engine].update(
            execution_status="PRODUCED",
            rejected=False,
            output=f"{engine}.gdat",
            output_sha256="d" * 64,
            trajectory={
                "shape": [1, 3],
                "columns": ["time", "A_count", "B_count"],
                "values": [[2, 10.0, 0.0]],
            },
        )
    path.write_text(json.dumps(receipt))

    report = issue_queue.s6_simulate_receipt_report(
        receipt_dir, SOURCE_REVISION, contract
    )

    assert len(report["results"]) == len(ROWS)


def test_s6_queue_entrypoint_records_run_and_receipt_hashes(tmp_path, monkeypatch):
    receipt_dir, contract = _receipts(tmp_path)
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract))
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            [
                {
                    "number": 140,
                    "title": "Simulate options",
                    "state": "OPEN",
                    "body": "## Acceptance criteria\n- [ ] `release-actions`: all actions pass.\n",
                }
            ]
        )
    )
    monkeypatch.setattr(issue_queue, "S6_SIMULATE_CONTRACT", str(contract_path))
    monkeypatch.setenv("GITHUB_RUN_ID", "4145")

    def git(_root, *args):
        if args == ("rev-parse", "HEAD"):
            return SOURCE_REVISION
        if args == ("status", "--porcelain"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(issue_queue.campaign, "git", git)
    output_dir = tmp_path / "queue"
    result = issue_queue.main(
        [
            "--issues-json",
            str(issues_path),
            "--s6-simulate-receipt-dir",
            str(receipt_dir),
            "--revision",
            SOURCE_REVISION,
            "--output-dir",
            str(output_dir),
        ]
    )

    assert result == 0
    queue_report = json.loads((output_dir / "issue-queue.json").read_text())
    receipt_record = next(
        row
        for row in queue_report["evidence_reports"]
        if row["kind"] == "s6-simulate-option-receipts"
    )
    assert receipt_record["workflow_run_id"] == "4145"
    assert len(receipt_record["files"]) == len(ROWS)


def test_s6_queue_entrypoint_refuses_a_dirty_candidate_tree(tmp_path, monkeypatch):
    receipt_dir, contract = _receipts(tmp_path)
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract))
    issues_path = tmp_path / "issues.json"
    issues_path.write_text("[]")
    monkeypatch.setattr(issue_queue, "S6_SIMULATE_CONTRACT", str(contract_path))
    monkeypatch.setenv("GITHUB_RUN_ID", "4145")

    def git(_root, *args):
        if args == ("rev-parse", "HEAD"):
            return SOURCE_REVISION
        if args == ("status", "--porcelain"):
            return " M tracked.py"
        raise AssertionError(args)

    monkeypatch.setattr(issue_queue.campaign, "git", git)
    output_dir = tmp_path / "queue"
    result = issue_queue.main(
        [
            "--issues-json",
            str(issues_path),
            "--s6-simulate-receipt-dir",
            str(receipt_dir),
            "--revision",
            SOURCE_REVISION,
            "--output-dir",
            str(output_dir),
        ]
    )

    assert result == 1
    error = json.loads((output_dir / "error.json").read_text())
    assert error["status"] == "HARNESS_ERROR"
    assert "clean candidate tree" in error["detail"]


def test_s6_rejection_accepts_hashed_diagnostic_residue_after_nonzero_exit(tmp_path):
    receipt_dir, contract = _receipts(tmp_path)
    path = receipt_dir / "action.simulate.atol.json"
    receipt = json.loads(path.read_text())
    outcome = receipt["scenarios"][2]["bng2"]
    outcome.update(
        return_code=1,
        output="diagnostic.gdat",
        output_sha256="f" * 64,
        trajectory={
            "shape": [1, 3],
            "columns": ["time", "A_count", "B_count"],
            "values": [[0.0, 10.0, 0.0]],
        },
    )
    path.write_text(json.dumps(receipt))

    report = issue_queue.s6_simulate_receipt_report(
        receipt_dir, SOURCE_REVISION, contract
    )

    assert len(report["results"]) == len(ROWS)
