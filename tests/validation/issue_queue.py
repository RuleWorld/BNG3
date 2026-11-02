"""Join exact-revision observations to issues without inferring issue completion.

This is read-only evidence triage. Approval decisions, unresolved upstream drift,
and unexecuted claims stay visible; the tool never closes issues or approves locks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

from . import campaign, inventory

ROOT = Path(__file__).resolve().parents[2]
FAILURES = {"FAIL", "HARNESS_ERROR", "TIMEOUT", "INVALID_INPUT"}
ISSUE_142_CHECKS = (
    "release-graph-identity",
    "release-graph-observables",
    "release-obligation-142",
)
S6_SIMULATE_ROWS = (
    "action.simulate.t_start",
    "action.simulate.t_end",
    "action.simulate.n_steps",
    "action.simulate.sample_times",
    "action.simulate.continue",
    "action.simulate.method",
    "action.simulate.atol",
    "action.simulate.rtol",
)
S6_SIMULATE_SELECTOR = (
    "tests/validation/release/cases/sprint-s6-simulate-options/"
    "test_simulate_options.py::test_simulate_option_contract[{row}]"
)
S6_SIMULATE_ORACLE = (
    "pinned BNG2 plus the analytic first-order conversion law; "
    "SSA scope is invariant-only"
)
S6_SIMULATE_SCOPE = (
    "default, explicit, invalid, and one row-relevant interaction; "
    "only the admitted ODE/SSA pair is attempted"
)
S6_EXPECTED_LAW = (
    "For A -> B at k=0.4 from A(0)=10, B(0)=0, "
    "A(t)=10*exp(-0.4*t), B(t)=10-A(t). ODE observable error bound: "
    "1e-6 absolute; schedule assertions are exact apart from 1e-12 time representation."
)
S6_EXPECTED_SSA_SCOPE = (
    "The admitted SSA case checks dispatch, requested schedule, integer populations, "
    "and A+B conservation only. It does not claim distributional or pathwise parity."
)
S6_SIMULATE_CONTRACT = (
    "tests/validation/release/cases/sprint-s6-simulate-options/contract.json"
)
S6_SCENARIOS = ("default", "explicit", "invalid", "interaction")


def issue142_receipt_reports(
    receipt, identity_path, observables_path, revision, *, artifact_run_id=None
):
    """Adapt the dedicated Issue 142 receipt and both child reports to queue leaves."""
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
        raise ValueError("invalid Issue 142 receipt schema")
    if receipt.get("acceptance_check") != "release-obligation-142":
        raise ValueError("conflicting Issue 142 receipt identity")
    source_revision = receipt.get("source_revision")
    if source_revision != revision:
        raise ValueError("stale Issue 142 receipt revision")
    if receipt.get("source_dirty") is not False:
        raise ValueError("Issue 142 receipt source was not recorded clean")
    checks = receipt.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(ISSUE_142_CHECKS):
        raise ValueError("Issue 142 receipt is missing or has conflicting child checks")
    for check_id, result in checks.items():
        if not isinstance(result, dict) or result.get("status") != "PASS":
            raise ValueError(f"Issue 142 check {check_id} did not pass")

    identity = checks["release-graph-identity"]
    observables = checks["release-graph-observables"]
    hash_fields = {
        "release-graph-identity": (
            "independent_isomorphism_oracle_sha256",
            "subject_sha256",
            "report_sha256",
        ),
        "release-graph-observables": (
            "bng2_script_sha256",
            "nfsim_binary_sha256",
            "subject_sha256",
            "report_sha256",
        ),
    }
    for check_id, fields in hash_fields.items():
        for field in fields:
            value = checks[check_id].get(field)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(
                    f"Issue 142 check {check_id} lacks valid {field} identity"
                )
    for check_id in ("release-graph-observables",):
        for field in ("bng2_revision", "nfsim_revision"):
            if not isinstance(checks[check_id].get(field), str) or not re.fullmatch(
                r"[0-9a-f]{40}", checks[check_id][field]
            ):
                raise ValueError(f"Issue 142 check {check_id} lacks valid {field}")
    if identity.get("case_count") != 9 or identity.get("exhaustive_case_count") != 116:
        raise ValueError(
            "Issue 142 graph identity receipt has stale bounded case counts"
        )
    if observables.get("run_count") != 200 or observables.get("dkw_alpha") != 0.005:
        raise ValueError(
            "Issue 142 observable receipt has stale run budget or error control"
        )
    if artifact_run_id is not None and not re.fullmatch(r"[0-9]+", artifact_run_id):
        raise ValueError("invalid Issue 142 artifact workflow run ID")
    for label, path, expected_hash in (
        ("identity", identity_path, identity["report_sha256"]),
        ("observables", observables_path, observables["report_sha256"]),
    ):
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash
        ):
            raise ValueError(
                f"Issue 142 {label} report hash differs from the consumed receipt"
            )
    identity_report = json.loads(identity_path.read_text())
    observables_report = json.loads(observables_path.read_text())

    def verify_source(report, label):
        if report.get("source_revision") != revision:
            raise ValueError(f"stale Issue 142 {label} report source revision")
        if report.get("source_dirty") is not False:
            raise ValueError(f"Issue 142 {label} report source was not recorded clean")

    verify_source(identity_report, "identity")
    verify_source(observables_report, "observables")
    if identity_report.get("acceptance_check") != "release-graph-identity":
        raise ValueError("conflicting Issue 142 identity report check ID")
    if observables_report.get("acceptance_check") != "release-graph-observables":
        raise ValueError("conflicting Issue 142 observables report check ID")
    if (
        identity_report.get("independent_isomorphism_oracle_sha256")
        != identity["independent_isomorphism_oracle_sha256"]
        or identity_report.get("subject_sha256") != identity["subject_sha256"]
        or identity_report.get("case_count") != 9
        or identity_report.get("exhaustive_case_count") != 116
    ):
        raise ValueError(
            "Issue 142 identity report conflicts with the consumed receipt"
        )
    if (
        observables_report.get("bng2_revision") != observables["bng2_revision"]
        or observables_report.get("bng2_script_sha256")
        != observables["bng2_script_sha256"]
        or observables_report.get("nfsim_revision") != observables["nfsim_revision"]
        or observables_report.get("nfsim_binary_sha256")
        != observables["nfsim_binary_sha256"]
        or observables_report.get("model_source_sha256")
        != observables["subject_sha256"]
        or observables_report.get("run_count") != 200
        or observables_report.get("dkw_alpha") != 0.005
    ):
        raise ValueError(
            "Issue 142 observables report conflicts with the consumed receipt"
        )
    from .graph_identity_contract import CASES, CHECKS

    expected_identity_ids = {
        f"graph-identity-contract:{case['id']}:{check}"
        for case in CASES
        for check in CHECKS
    }
    catalog_identity_ids = {
        check["id"]
        for issue in json.loads(
            (ROOT / "provenance/issue-obligations.json").read_text()
        )["issues"]
        if issue["number"] == 142
        for obligation in issue["obligations"]
        for check in obligation["required_checks"]
        if check["id"].startswith("graph-identity-contract:")
    }
    if not catalog_identity_ids <= expected_identity_ids:
        raise ValueError("Issue 142 catalog names unknown identity component checks")
    identity_rows = identity_report.get("results")
    if not isinstance(identity_rows, list):
        raise ValueError("Issue 142 identity report has no component rows")
    by_id = {row.get("id"): row for row in identity_rows if isinstance(row, dict)}
    if len(by_id) != len(identity_rows) or set(by_id) != expected_identity_ids:
        raise ValueError(
            "Issue 142 identity report has missing or conflicting component checks"
        )
    if any(row.get("status") != "PASS" for row in identity_rows):
        raise ValueError("an Issue 142 identity component check did not pass")

    source = {"revision": source_revision, "dirty": False}
    replay_references = {}
    if artifact_run_id is not None:
        replay_references = {
            "workflow_run_id": artifact_run_id,
            "identity": {
                "artifact_name": f"issue142-release-graph-identity-{artifact_run_id}",
                "file": identity_path.name,
                "sha256": identity["report_sha256"],
            },
            "observables": {
                "artifact_name": f"issue142-release-graph-observables-{artifact_run_id}",
                "file": observables_path.name,
                "sha256": observables["report_sha256"],
            },
        }
    identity_report_for_queue = {
        "source": source,
        "references": {
            "independent_isomorphism": {
                "sha256": identity["independent_isomorphism_oracle_sha256"]
            }
        },
        "subject": {"sha256": identity["subject_sha256"]},
        "checks": checks,
        "results": [
            dict(
                row,
                stage="graph-identity-contract",
                related_issues=[142],
                supported_execution=True,
                evidence_kind="supported-execution",
                receipt=identity,
            )
            for row in identity_rows
        ],
    }
    observables_report_for_queue = {
        "source": source,
        "references": {
            "bionetgen": {
                "revision": observables["bng2_revision"],
                "sha256": observables["bng2_script_sha256"],
            },
            "nfsim": {
                "revision": observables["nfsim_revision"],
                "sha256": observables["nfsim_binary_sha256"],
            },
        },
        "subject": {"sha256": observables["subject_sha256"]},
        "checks": checks,
        "results": [],
    }
    receipt_report = {
        "source": source,
        "references": {
            "independent_isomorphism": {
                "sha256": identity["independent_isomorphism_oracle_sha256"]
            },
            "bionetgen": {
                "revision": observables["bng2_revision"],
                "sha256": observables["bng2_script_sha256"],
            },
            "nfsim": {
                "revision": observables["nfsim_revision"],
                "sha256": observables["nfsim_binary_sha256"],
            },
        },
        "checks": checks,
        "results": [],
    }
    for check_id, report in (
        ("release-graph-identity", identity_report_for_queue),
        ("release-graph-observables", observables_report_for_queue),
        ("release-obligation-142", receipt_report),
    ):
        evidence_kind = (
            "disposition"
            if check_id == "release-obligation-142"
            else "supported-execution"
        )
        row = {
            "id": check_id,
            "status": "PASS",
            "stage": "issue142-release-receipt",
            "check": check_id,
            "related_issues": [142],
            "evidence_kind": evidence_kind,
            "receipt": checks[check_id],
        }
        if evidence_kind == "supported-execution":
            row["supported_execution"] = True
        report["results"].append(row)
    receipt_report["results"].append(
        {
            "id": "qualification:issue:142:closure-record",
            "status": "PASS",
            "stage": "issue142-release-receipt",
            "check": "release-obligation-142",
            "related_issues": [142],
            "evidence_kind": "disposition",
            "receipt": checks["release-obligation-142"],
        }
    )
    if replay_references:
        for report in (
            identity_report_for_queue,
            observables_report_for_queue,
            receipt_report,
        ):
            report["replay_references"] = replay_references
    return [identity_report_for_queue, observables_report_for_queue, receipt_report]


def _s6_expected_times(row, scenario):
    """Return the declared output grid for a valid S6 scenario."""
    grids = {
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
    if scenario == "invalid" or (
        row == "action.simulate.method" and scenario == "default"
    ):
        return None
    return grids.get((row, scenario), [0, 0.25, 0.5, 0.75, 1])


def _s6_validate_outcome(outcome, row, scenario, expected_rejection, engine):
    if not isinstance(outcome, dict):
        raise ValueError(f"S6 {engine} scenario has no execution outcome")
    transcript_hash = outcome.get("transcript_sha256")
    if not isinstance(transcript_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", transcript_hash
    ):
        raise ValueError(f"S6 {engine} scenario lacks transcript identity")
    nonincreasing_time = scenario == "invalid" and row in {
        "action.simulate.t_start",
        "action.simulate.t_end",
    }
    if expected_rejection and not nonincreasing_time:
        if (
            outcome.get("execution_status") != "REJECTED"
            or outcome.get("rejected") is not True
            or outcome.get("output") is not None
            or outcome.get("trajectory") is not None
        ):
            raise ValueError(f"S6 {engine} expected-rejection control was not refused")
        return
    if nonincreasing_time and outcome.get("execution_status") == "REJECTED":
        if outcome.get("rejected") is not True or outcome.get("trajectory") is not None:
            raise ValueError(
                f"S6 {engine} invalid time interval has conflicting outcome"
            )
        return
    if (
        outcome.get("execution_status") != "PRODUCED"
        or outcome.get("rejected") is not False
        or not outcome.get("output")
        or not isinstance(outcome.get("output_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", outcome["output_sha256"])
    ):
        raise ValueError(f"S6 {engine} valid case lacks produced output identity")
    trajectory = outcome.get("trajectory")
    if not isinstance(trajectory, dict) or trajectory.get("columns") != [
        "time",
        "A_count",
        "B_count",
    ]:
        raise ValueError(f"S6 {engine} trajectory lacks the declared observables")
    values = trajectory.get("values")
    expected_times = _s6_expected_times(row, scenario)
    if (
        not isinstance(values, list)
        or expected_times is None
        or len(values) != len(expected_times)
    ):
        if nonincreasing_time and isinstance(values, list) and len(values) == 1:
            if (
                trajectory.get("shape") != [1, 3]
                or len(values[0]) != 3
                or not all(math.isfinite(float(item)) for item in values[0])
                or values[0][1:] != [10.0, 0.0]
            ):
                raise ValueError(
                    f"S6 {engine} nonincreasing interval changed initial observables"
                )
            return
        raise ValueError(f"S6 {engine} trajectory has an undeclared output grid")
    if trajectory.get("shape") != [len(values), 3] or any(
        not isinstance(point, list)
        or len(point) != 3
        or not all(math.isfinite(float(value)) for value in point)
        for point in values
    ):
        raise ValueError(f"S6 {engine} trajectory has invalid shape or values")
    if any(
        abs(float(point[0]) - time) > 1e-12
        for point, time in zip(values, expected_times)
    ):
        raise ValueError(f"S6 {engine} trajectory schedule differs from the contract")
    if row == "action.simulate.method" and scenario == "interaction":
        if any(
            any(value < 0 or value != int(value) for value in point[1:])
            or sum(point[1:]) != 10
            for point in values
        ):
            raise ValueError(f"S6 {engine} SSA invariants were violated")
        return
    relative_start = (
        0.5
        if row == "action.simulate.t_start" and scenario in {"explicit", "interaction"}
        else 0.0
    )
    for time, a_count, b_count in values:
        expected_a = 10 * math.exp(-0.4 * (time - relative_start))
        if abs(a_count - expected_a) > 1e-6 or abs(b_count - (10 - expected_a)) > 1e-6:
            raise ValueError(f"S6 {engine} trajectory differs from the analytic law")


def s6_simulate_receipt_report(
    receipt_dir, revision, contract, *, artifact_run_id=None
):
    """Validate and adapt the eight bounded S6 receipts as queue evidence."""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("invalid S6 candidate revision")
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise ValueError("invalid S6 contract schema")
    oracle = contract.get("source")
    if (
        not isinstance(oracle, dict)
        or oracle.get("repository") != "RuleWorld/bionetgen"
        or oracle.get("path") != "bng2/Perl2/BNGAction.pm"
        or not re.fullmatch(r"[0-9a-f]{40}", str(oracle.get("revision", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(oracle.get("sha256", "")))
    ):
        raise ValueError("S6 contract lacks the pinned BNG2 source identity")
    oracle_contract = contract.get("oracle")
    if (
        not isinstance(oracle_contract, dict)
        or oracle_contract.get("identity")
        != "pinned BNG2 executable at source revision above; separately derived mass-action law"
        or oracle_contract.get("law") != S6_EXPECTED_LAW
        or oracle_contract.get("stochastic_scope") != S6_EXPECTED_SSA_SCOPE
    ):
        raise ValueError("S6 contract changed its independent oracle or bounded law")
    from scripts.ci.oracle_sources import load_lock, load_oracle_source

    if oracle["revision"] != load_oracle_source(load_lock(), "bionetgen")["revision"]:
        raise ValueError("S6 contract BNG2 revision differs from the source lock")
    if not isinstance(contract.get("rows"), dict) or set(contract["rows"]) != set(
        S6_SIMULATE_ROWS
    ):
        raise ValueError("S6 contract must name exactly the eight simulate rows")
    for row, scenarios in contract["rows"].items():
        if (
            not isinstance(scenarios, dict)
            or set(scenarios) != set(S6_SCENARIOS)
            or any(
                not isinstance(description, str) or not description
                for description in scenarios.values()
            )
        ):
            raise ValueError(f"S6 contract has incomplete scenarios for {row}")
    if artifact_run_id is not None and not re.fullmatch(r"[0-9]+", artifact_run_id):
        raise ValueError("invalid S6 artifact workflow run ID")
    receipt_dir = Path(receipt_dir)
    files = sorted(receipt_dir.glob("*.json")) if receipt_dir.is_dir() else []
    if len(files) != len(S6_SIMULATE_ROWS) or {path.name for path in files} != {
        f"{row}.json" for row in S6_SIMULATE_ROWS
    }:
        raise ValueError("S6 receipt directory must contain exactly eight named rows")

    receipts = []
    product_sha256 = None
    for row in S6_SIMULATE_ROWS:
        path = receipt_dir / f"{row}.json"
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read S6 receipt {path.name}: {exc}") from exc
        if not isinstance(receipt, dict) or receipt.get("row_id") != row:
            raise ValueError(f"S6 receipt row identity conflicts: {path.name}")
        if receipt.get("selector") != S6_SIMULATE_SELECTOR.format(row=row):
            raise ValueError(f"S6 receipt has unexpected selector: {row}")
        if receipt.get("status") != "PASS" or receipt.get("failures") != []:
            raise ValueError(f"S6 receipt did not pass: {row}")
        if (
            receipt.get("oracle") != S6_SIMULATE_ORACLE
            or receipt.get("scope") != S6_SIMULATE_SCOPE
        ):
            raise ValueError(f"S6 receipt changed its declared oracle or scope: {row}")
        reported_oracle = receipt.get("source")
        if (
            not isinstance(reported_oracle, dict)
            or reported_oracle.get("revision") != oracle["revision"]
            or reported_oracle.get("path") != oracle["path"]
            or reported_oracle.get("sha256") != oracle["sha256"]
        ):
            raise ValueError(f"S6 receipt conflicts with the pinned BNG2 oracle: {row}")
        product = receipt.get("product")
        if (
            not isinstance(product, dict)
            or product.get("revision") != revision
            or not re.fullmatch(r"[0-9a-f]{64}", str(product.get("bng_cpp_sha256", "")))
        ):
            raise ValueError(f"S6 product identity is stale or invalid: {row}")
        if product_sha256 is None:
            product_sha256 = product["bng_cpp_sha256"]
        elif product_sha256 != product["bng_cpp_sha256"]:
            raise ValueError(
                "S6 receipts were produced by conflicting bng_cpp binaries"
            )
        scenarios = receipt.get("scenarios")
        if not isinstance(scenarios, list) or [
            item.get("name") if isinstance(item, dict) else None for item in scenarios
        ] != list(S6_SCENARIOS):
            raise ValueError(f"S6 receipt has missing or duplicated scenarios: {row}")
        for scenario in scenarios:
            name = scenario["name"]
            expected_rejection = name == "invalid" or (
                row == "action.simulate.method" and name == "default"
            )
            if (
                scenario.get("status") != "PASS"
                or scenario.get("failures") != []
                or scenario.get("expected_rejection") is not expected_rejection
                or not re.fullmatch(
                    r"[0-9a-f]{64}", str(scenario.get("source_sha256", ""))
                )
            ):
                raise ValueError(
                    f"S6 scenario did not pass its named contract: {row}/{name}"
                )
            for engine in ("bng2", "bng3"):
                _s6_validate_outcome(
                    scenario.get(engine), row, name, expected_rejection, engine
                )
        receipts.append((row, path, receipt))

    references = {
        "bionetgen": {"revision": oracle["revision"], "sha256": oracle["sha256"]},
        "s6_receipts": {
            row.replace(".", "_"): {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()
            }
            for row, _, _ in receipts
        },
    }
    if artifact_run_id is not None:
        references["workflow_run_id"] = artifact_run_id
    return {
        "source": {"revision": revision, "dirty": False},
        "references": references,
        "subject": {"sha256": product_sha256},
        "artifact": {
            "name": "bng3-s6-simulate-option-receipts",
            "workflow_run_id": artifact_run_id,
        },
        "scope": S6_SIMULATE_SCOPE,
        "claim_limit": "SSA evidence checks invariants only; no pathwise or distributional equivalence is claimed.",
        "results": [
            {
                "id": row,
                "status": "PASS",
                "stage": "s6-simulate-options",
                "check": f"release-capability[{row}]",
                "related_issues": [140],
                "capabilities": [row],
                "test_file": S6_SIMULATE_SELECTOR.format(row=row).split("::", 1)[0],
                "supported_execution": True,
                "evidence_kind": "supported-execution",
                "receipt_sha256": references["s6_receipts"][row.replace(".", "_")][
                    "sha256"
                ],
            }
            for row, path, _ in receipts
        ],
    }


def acceptance_criteria(issue):
    """Retain live issue criteria separately from broad issue-linked evidence.

    A maintainer checkbox and a passing related contract are both useful,
    but neither establishes execution of the entire acceptance sentence.
    """
    criteria, active = [], False
    for raw_line in (issue.get("body") or "").splitlines():
        line = raw_line.strip()
        if line.strip("#* ").lower() == "acceptance criteria":
            active = True
            continue
        if not active:
            continue
        if line.startswith("#") or (
            line.startswith("**") and line.strip("* :").lower() != "inventory rows"
        ):
            break
        match = re.match(r"[-*] \[([ xX])\] (.+)", line)
        if match:
            criteria.append(
                dict(
                    id=f"issue:{issue['number']}:acceptance:{len(criteria) + 1}",
                    text=match.group(2),
                    maintainer_checked=match.group(1).lower() == "x",
                    evidence_status="UNVERIFIED",
                )
            )
    return criteria


def build_queue(issues, reports, revision):
    if not isinstance(issues, list):
        raise ValueError("issue snapshot must be a list")
    metadata = {}
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("issue snapshot entries must be objects")
        number = issue.get("number")
        if type(number) is not int or number < 1 or number in metadata:
            raise ValueError("issue snapshot requires unique positive numbers")
        metadata[number] = issue
    observations, capability_issues, mapped, packet_ids = {}, {}, set(), {}
    for report in reports:
        if not isinstance(report, dict):
            raise ValueError("evidence report must be an object")
        if report.get("source", {}).get("dirty") is not False:
            raise ValueError(
                "dirty or unverifiable report cannot establish exact-revision evidence"
            )
        if report.get("source", {}).get("revision") != revision:
            raise ValueError(
                "report revision differs from requested issue-queue revision"
            )
        for capability in report.get("capabilities", []):
            if capability.get("kind") == "semantic-claim":
                numbers = set(capability.get("issues", []))
                capability_issues.setdefault(capability["id"], set()).update(numbers)
                mapped.update(numbers)
        for task in report.get("investigation_tasks", []):
            if task.get("case_id") and task.get("id"):
                packet_ids.setdefault(task["case_id"], set()).add(task["id"])
        seen_in_report = set()
        for row in report.get("results", []):
            if row.get("status") not in campaign.STATUSES or not row.get("id"):
                raise ValueError("invalid result identity/status")
            if row["id"] in seen_in_report:
                raise ValueError("duplicate result identity within a report")
            seen_in_report.add(row["id"])
            if row.get("aggregate"):
                continue
            # A successful command is not a successful semantic contract. Keep
            # failures actionable even if a crashing process emitted no checks.
            mapped.update(row.get("related_issues") or [])
            key = row["id"]
            observed = {
                k: row.get(k)
                for k in (
                    "status",
                    "stage",
                    "check",
                    "first_difference",
                    "related_issues",
                    "capabilities",
                    "test_file",
                    "supported_execution",
                    "evidence_kind",
                )
            }
            if key in observations and observations[key] != observed:
                raise ValueError("conflicting exact-revision observations: " + key)
            observations[key] = observed
    result = []
    numbers = set(metadata) | mapped
    for row in observations.values():
        numbers.update(row.get("related_issues") or [])
    for number in sorted(numbers):
        issue = metadata.get(number, {})
        evidence, diagnostics = {}, {}
        for key, row in observations.items():
            if row["status"] == "PASS" and not (
                row.get("check") or row.get("test_file")
            ):
                continue
            related = set(row.get("related_issues") or [])
            if not related:
                for capability in row.get("capabilities") or []:
                    related.update(capability_issues.get(capability, set()))
            if number in related:
                if row["status"] == "PASS" and (
                    row.get("supported_execution") is False
                    or row.get("evidence_kind") == "diagnostic-only"
                ):
                    diagnostics[key] = row
                else:
                    evidence[key] = row
        counts = Counter(row["status"] for row in evidence.values())
        decision = "maintainer/product decision" in (issue.get("body") or "")
        if FAILURES & counts.keys():
            disposition, action = "OBSERVED_FAILURE", "investigate-recorded-contract"
        elif decision:
            disposition, action = "DECISION_REQUIRED", "maintainer-scope-or-approval"
        elif counts.get("PASS"):
            disposition, action = (
                "PARTIAL_EXECUTION",
                "expand-named-acceptance-contracts",
            )
        elif number in mapped or evidence:
            disposition, action = "EVIDENCE_GAP", "add-or-execute-reusable-contract"
        else:
            disposition, action = "UNMAPPED", "map-acceptance-criteria-to-capabilities"
        result.append(
            dict(
                number=number,
                title=issue.get("title"),
                state=issue.get("state", "NOT_IN_SNAPSHOT"),
                disposition=disposition,
                next_action=action,
                outcomes=dict(sorted(counts.items())),
                evidence_ids=sorted(evidence),
                diagnostic_control_ids=sorted(diagnostics),
                diagnostic_control_outcomes=dict(
                    sorted(
                        Counter(row["status"] for row in diagnostics.values()).items()
                    )
                ),
                acceptance_criteria=acceptance_criteria(dict(issue, number=number)),
                closure_eligible=False,
                maintainer_decision_required=decision,
                investigation_task_ids=sorted(
                    {
                        packet
                        for key in evidence
                        for packet in packet_ids.get(key, set())
                    }
                ),
            )
        )
    return result


def obligation_inventory(issues, catalog=None):
    """Bind reviewed scope to live text; additions and changed scope stay visible."""
    catalog = catalog or json.loads(
        (ROOT / "provenance/issue-obligations.json").read_text()
    )
    known = {row["number"]: row for row in catalog["issues"]}
    obligations = []
    for issue in issues:
        number = issue["number"]
        body = issue.get("body") or ""
        digest = hashlib.sha256(body.encode()).hexdigest()
        entry = known.get(number, {})
        entry_digest_current = entry.get("body_sha256") == digest
        criteria = acceptance_criteria(issue)
        texts = [row["text"] for row in criteria] or [
            body or issue.get("title", "Scope absent")
        ]
        reviewed = entry.get("obligations", [])
        mapped_live = {}
        represented_live = set()
        for item in reviewed:
            live_criteria = item.get("live_acceptance_criteria", [])
            current = entry_digest_current or item.get("live_body_sha256") == digest
            row = dict(
                item, issue=number, scope_status="CURRENT" if current else "STALE_SCOPE"
            )
            if not current:
                row["unmapped_scope"] = list(row.get("unmapped_scope", [])) + [
                    "Live issue body differs from reviewed scope; reconcile before demonstrating acceptance."
                ]
            obligations.append(row)
            if current and item.get("criterion") in texts:
                represented_live.update(
                    text for text in texts if text == item["criterion"]
                )
            for live in live_criteria:
                if live.get("live_body_sha256") == digest:
                    mapped_live[live.get("text")] = (item, live)
                    represented_live.add(live.get("text"))
        for text in texts:
            if (
                any(
                    (
                        row.get("criterion") == text
                        and (
                            entry_digest_current
                            or row.get("live_body_sha256") == digest
                        )
                    )
                    for row in reviewed
                )
                or text in represented_live
            ):
                continue
            identity = hashlib.sha256(text.encode()).hexdigest()[:16]
            obligations.append(
                dict(
                    id=f"issue:{number}:unmapped:{identity}",
                    issue=number,
                    criterion=text,
                    scope=text,
                    scope_status="UNMAPPED",
                    dependencies=[],
                    boundaries=[],
                    required_checks=[],
                    test_references=[],
                    completion_condition="Maintainer-reviewed mapping and named evidence required.",
                    decisions=[
                        "Map remaining live scope without narrowing acceptance."
                    ],
                    unmapped_scope=[text],
                )
            )
        emitted = set()
        for text, (parent, live) in mapped_live.items():
            check_id = live.get("check_id")
            if text not in texts or not check_id or check_id in emitted:
                continue
            check = next(
                (
                    candidate
                    for candidate in parent.get("required_checks", [])
                    if candidate.get("id") == check_id
                ),
                None,
            )
            if check is None:
                continue
            obligations.append(
                dict(
                    id=f"issue:{number}:live-acceptance:{check_id}",
                    issue=number,
                    criterion=text,
                    scope=text,
                    live_acceptance_criteria=[dict(live)],
                    live_body_sha256=digest,
                    scope_status="CURRENT",
                    dependencies=live.get("dependencies", []),
                    boundaries=parent.get("boundaries", []),
                    required_checks=[dict(check)],
                    test_references=parent.get("test_references", []),
                    completion_condition=(
                        "Exact-revision result satisfies the live acceptance check "
                        "with its required selector and consuming receipt."
                    ),
                    decisions=[],
                    unmapped_scope=[],
                )
            )
            emitted.add(check_id)
    ids = [row["id"] for row in obligations]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate obligation identity")
    return obligations


def _identity_value(report, path):
    value = report
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _report_status(report, revision):
    if not isinstance(report, dict):
        raise ValueError("evidence report must be an object")
    source = report.get("source")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("revision"), str)
        or not re.fullmatch("[0-9a-f]{40}", source["revision"])
        or source.get("dirty") is not False
    ):
        return "UNVERIFIABLE"
    return "STALE" if source["revision"] != revision else None


def assess_obligations(obligations, reports, revision):
    """Audit exact leaf checks; missing evidence is never inferred from issue links."""
    observations, audit, conflicts = {}, [], set()
    for index, report in enumerate(reports):
        source = report.get("source", {})
        reason = _report_status(report, revision)
        if reason:
            audit.append(dict(report=index, status=reason, source=source))
            continue
        seen = set()
        for row in report.get("results", []):
            key = row.get("id")
            if not key or row.get("status") not in campaign.STATUSES:
                raise ValueError("invalid result identity/status")
            if key in seen:
                conflicts.add(key)
                audit.append(
                    dict(
                        report=index,
                        id=key,
                        status="CONFLICT",
                        reason="duplicate leaf identity",
                    )
                )
            seen.add(key)
            if row.get("aggregate"):
                continue
            evidence = dict(
                observation=row,
                candidate_identity=source,
                oracle_identities=report.get("references", {}),
            )
            if key in observations and observations[key][0] != evidence:
                conflicts.add(key)
                audit.append(
                    dict(
                        report=index,
                        id=key,
                        status="CONFLICT",
                        reason="different exact-revision observations or identities",
                    )
                )
            observations[key] = (evidence, report)
    assessed = []
    for obligation in obligations:
        for name in ("id", "criterion", "scope", "completion_condition"):
            if not isinstance(obligation.get(name), str) or not obligation[name]:
                raise ValueError("missing obligation field: " + name)
        for name in (
            "dependencies",
            "boundaries",
            "required_checks",
            "test_references",
            "decisions",
            "unmapped_scope",
        ):
            if not isinstance(obligation.get(name), list):
                raise ValueError("invalid obligation list: " + name)
        checks = obligation["required_checks"]
        if len({c["id"] for c in checks}) != len(checks):
            raise ValueError("duplicate required check identity")
        for check in checks:
            if check.get("evidence_kind") not in {
                "supported-execution",
                "diagnostic-only",
                "disposition",
                "native-bngir-semantic-control",
            } or not check.get("expectation"):
                raise ValueError(
                    "required check needs evidence kind and independent expectation"
                )
            if check.get("selector_status") not in {
                None,
                "COLLECTED",
                "MISSING_SELECTOR",
            }:
                raise ValueError("invalid required-check selector status")
            if check.get("selector_status") == "COLLECTED" and not check.get(
                "selector"
            ):
                raise ValueError(
                    "collected required check needs an executable selector"
                )
            if check.get("selector_status") == "MISSING_SELECTOR" and check.get(
                "selector"
            ):
                raise ValueError(
                    "missing required-check selector cannot name a selector"
                )
            if check.get("receipt_producer_status") not in {
                None,
                "CONSUMER_READY",
                "MISSING_PRODUCER",
                "MISSING_CONSUMER",
            }:
                raise ValueError("invalid receipt-producer status")
            if check.get("receipt_producer_status") in {
                "CONSUMER_READY",
                "MISSING_CONSUMER",
            } and not check.get("receipt_producer"):
                raise ValueError("declared receipt producer status needs its producer")
            if check.get("receipt_producer_status") == "MISSING_PRODUCER" and check.get(
                "receipt_producer"
            ):
                raise ValueError("missing receipt producer cannot name a producer")
            missing_evidence = check.get("missing_evidence", [])
            if not isinstance(missing_evidence, list) or any(
                not isinstance(item, str) or not item for item in missing_evidence
            ):
                raise ValueError(
                    "required-check missing evidence must be a string list"
                )
    ids = [o["id"] for o in obligations]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate obligation identity")
    for obligation in obligations:
        checks = []
        for required in obligation["required_checks"]:
            key = required["id"]
            record = dict(required, status="NOT_TESTED", missing_evidence=[])
            record["missing_evidence"].extend(required.get("missing_evidence", []))
            if required.get("selector_status") == "MISSING_SELECTOR":
                record["missing_evidence"].append("selector:MISSING_SELECTOR")
            if required.get("receipt_producer_status") in {
                "MISSING_PRODUCER",
                "MISSING_CONSUMER",
            }:
                record["missing_evidence"].append(
                    "receipt_producer:" + required["receipt_producer_status"]
                )
            record["missing_evidence"] = list(dict.fromkeys(record["missing_evidence"]))
            if key in conflicts:
                record["status"] = "CONFLICT"
            elif key in observations:
                evidence, report = observations[key]
                row = evidence["observation"]
                record.update(evidence)
                record["status"] = row["status"]
                if row["status"] == "PASS":
                    kind = required["evidence_kind"]
                    if kind in {
                        "supported-execution",
                        "native-bngir-semantic-control",
                    } and (
                        row.get("supported_execution") is not True
                        or row.get("evidence_kind") != kind
                    ):
                        record["missing_evidence"].append(
                            "explicit supported-execution evidence"
                        )
                    elif (
                        kind != "supported-execution"
                        and row.get("evidence_kind") != kind
                    ):
                        record["missing_evidence"].append("evidence_kind:" + kind)
                    # A successful conversion/process may still report lost
                    # required semantics. Receipt labels cannot override loss.
                    if kind == "supported-execution" and any(
                        str(diagnostic.get("severity", "")).lower()
                        in {
                            "dropped",
                            "approximated",
                            "unsupported",
                            "untranslated",
                            "error",
                        }
                        for diagnostic in row.get("diagnostics", [])
                        if isinstance(diagnostic, dict)
                    ):
                        record["missing_evidence"].append(
                            "loss diagnostics prevent supported execution"
                        )
                if row["status"] not in {"NOT_TESTED", "UNSUPPORTED", "INVALID_INPUT"}:
                    for path in required.get("identity_requirements", []):
                        if not _identity_value(report, path):
                            record["missing_evidence"].append(path)
                    if record["missing_evidence"]:
                        record["status"] = "EVIDENCE_GAP"
            else:
                record["missing_evidence"].append(key)
            checks.append(record)
        for check in checks:
            check["executed"] = (
                bool(check.get("observation")) and check["status"] != "NOT_TESTED"
            )
        statuses = {c["status"] for c in checks}
        if (
            obligation.get("scope_status") in {"STALE_SCOPE", "UNMAPPED"}
            or obligation.get("unmapped_scope")
            or obligation.get("decisions")
        ):
            status = "DECISION_REQUIRED"
        else:
            status = "DEMONSTRATED" if checks else "EVIDENCE_GAP"
        for candidate in (
            "NOT_TESTED",
            "EVIDENCE_GAP",
            "UNSUPPORTED",
            "INVALID_INPUT",
            "TIMEOUT",
            "FAIL",
            "HARNESS_ERROR",
            "CONFLICT",
        ):
            if candidate in statuses:
                status = candidate
        if status == "DEMONSTRATED" and statuses != {"PASS"}:
            status = "EVIDENCE_GAP"
        assessed.append(
            dict(
                obligation,
                status=status,
                checks=checks,
                test_reference_status=(
                    "RELEVANT_TEST_EXISTS"
                    if obligation.get("test_references")
                    else "NO_TEST_REFERENCE"
                ),
                missing_evidence=[m for c in checks for m in c["missing_evidence"]],
                untested_routes=[
                    dict(
                        check=c["id"],
                        boundaries=obligation["boundaries"],
                        feature_combinations=obligation.get(
                            "feature_combinations",
                            [
                                "Only explicitly named check scope; broader combinations unspecified."
                            ],
                        ),
                    )
                    for c in checks
                    if not c["executed"]
                ],
            )
        )
    # Fixed-point dependency audit also blocks cycles; do not interpret a cycle as proof.
    demonstrated = set()
    while True:
        added = {
            o["id"]
            for o in assessed
            if o["status"] == "DEMONSTRATED" and set(o["dependencies"]) <= demonstrated
        } - demonstrated
        if not added:
            break
        demonstrated.update(added)
    for row in assessed:
        row["blocked_dependencies"] = sorted(set(row["dependencies"]) - demonstrated)
        if row["status"] == "DEMONSTRATED" and row["id"] not in demonstrated:
            row["status"] = "BLOCKED"
    return dict(obligations=assessed, evidence_audit=audit)


def select_campaign(obligations, *, findings=(), max_families=3, active_issues=None):
    """Choose plans from existing generators; this never authorizes execution."""
    if active_issues is not None:
        obligations = [o for o in obligations if o.get("issue") in active_issues]
        findings = [
            dict(
                row,
                related_issues=sorted(
                    set(row.get("related_issues", [])) & active_issues
                ),
            )
            for row in findings
            if set(row.get("related_issues", [])) & active_issues
        ]
    if type(max_families) is not int or not 0 <= max_families <= 10:
        raise ValueError("campaign family budget must be between zero and ten")
    from .integrated_cases import generated_cases
    from .integrated import expected_contract_ids
    from .bngir_adversarial import check_ids

    cases = generated_cases(full=False)
    families = []
    for family in ("decay", "reversible", "dimerization"):
        selected = [case for case in cases if case["family"] == family]
        families.append(
            dict(
                id="generated-" + family,
                case_ids=[c["id"] for c in selected],
                check_ids=expected_contract_ids(
                    selected,
                    include_boundaries=False,
                    include_graph_identity=False,
                    include_bngir_adversarial=False,
                    include_quantity_laws=False,
                ),
                runner="tests.validation.integrated",
                budget=dict(
                    cases=len(selected), stage_timeout_seconds=60, ensemble_runs=32
                ),
                limits="PR representatives only; no full corpus, lifecycle concurrency, or universal physical-unit qualification.",
            )
        )
    families.append(
        dict(
            id="native-bngir-adversarial",
            case_ids=[],
            check_ids=check_ids(),
            runner="tests.validation.integrated",
            budget=dict(checks=len(check_ids()), stage_timeout_seconds=60),
            limits="Bounded generated native reader shapes; no complete migration or arbitrary graph coverage.",
        )
    )
    from .integrated_marginals import source_law_check_ids
    from .integrated_cases import source_law_cases

    families.append(
        dict(
            id="quantity-source-laws",
            case_ids=[case["id"] for case in source_law_cases()],
            check_ids=source_law_check_ids(),
            runner="tests.validation.integrated",
            budget=dict(
                cases=len(source_law_cases()),
                ensemble_runs=32,
                stage_timeout_seconds=900,
            ),
            limits="Finite prelowered physical-law and bare BNGL count controls; no unit-annotation ingestion or joint-law qualification.",
        )
    )
    selected = []
    for family in families:
        available = set(family["check_ids"])
        targets = [
            o
            for o in obligations
            if o.get("status") != "DEMONSTRATED"
            and any(c["id"] in available for c in o["required_checks"])
        ]
        known = [
            r
            for r in findings
            if r.get("id") in available
            and not r.get("aggregate")
            and r.get("status") in {"FAIL", "HARNESS_ERROR", "TIMEOUT"}
        ]
        if not targets and not known:
            continue
        family.update(
            obligation_ids=sorted(o["id"] for o in targets),
            issues=sorted(
                {o.get("issue", int(o["id"].split(":")[1])) for o in targets}
                | {number for row in known for number in row.get("related_issues", [])}
            ),
            known_finding_ids=sorted({r["id"] for r in known}),
            reason="Existing family contains uncovered exact obligation checks or named failing observations; finding issue links are investigation hints only and establish no additional obligation coverage.",
            authorization="PLAN_ONLY",
            complete_corpus_coverage=False,
        )
        family["selection_arguments"] = (
            ["--bngir-adversarial-only"]
            if family["id"] == "native-bngir-adversarial"
            else (
                ["--quantity-laws-only"]
                if family["id"] == "quantity-source-laws"
                else [
                    argument
                    for case_id in family["case_ids"]
                    for argument in ("--case", case_id)
                ]
            )
        )
        family["confirmed_failures"] = sum(o.get("status") == "FAIL" for o in targets)
        selected.append(family)
    return sorted(
        selected,
        key=lambda f: (
            -f["confirmed_failures"],
            -len(f["known_finding_ids"]),
            -len(f["issues"]),
            -len(f["obligation_ids"]),
            f["id"],
        ),
    )[:max_families]


def acceptance_dashboard(queue, assessment, campaigns):
    for row in queue:
        obligations = [
            o for o in assessment["obligations"] if o.get("issue") == row["number"]
        ]
        live_status = {
            o["criterion"]: o["status"]
            for o in obligations
            if o.get("live_acceptance_criteria") and o.get("scope_status") == "CURRENT"
        }
        for criterion in row["acceptance_criteria"]:
            status = live_status.get(criterion["text"])
            if status:
                criterion["evidence_status"] = (
                    "PASS" if status == "DEMONSTRATED" else status
                )
        row["obligations"] = obligations
        row["obligation_outcomes"] = dict(Counter(o["status"] for o in obligations))
        row["demonstrated_obligations"] = [
            o["id"] for o in obligations if o["status"] == "DEMONSTRATED"
        ]
        row["remaining_obligations"] = [
            o["id"] for o in obligations if o["status"] != "DEMONSTRATED"
        ]
        row["selected_families"] = [
            f["id"] for f in campaigns if row["number"] in f["issues"]
        ]
        row["confirmed_failures"] = [
            c["id"] for o in obligations for c in o["checks"] if c["status"] == "FAIL"
        ]
        row["unexecuted_checks"] = [
            c["id"] for o in obligations for c in o["checks"] if not c["executed"]
        ]
        row["unsupported_boundaries"] = [
            dict(check=c["id"], boundaries=o["boundaries"])
            for o in obligations
            for c in o["checks"]
            if c["status"] == "UNSUPPORTED"
        ]
        row["decisions_required"] = [
            dict(
                obligation=o["id"],
                decisions=o["decisions"],
                unmapped_scope=o["unmapped_scope"],
            )
            for o in obligations
            if o["decisions"]
        ]
        row["scope_reconciliation_required"] = [
            dict(
                obligation=o["id"],
                scope_status=o.get("scope_status"),
                unmapped_scope=o["unmapped_scope"],
            )
            for o in obligations
            if o.get("scope_status") in {"STALE_SCOPE", "UNMAPPED"}
            or o["unmapped_scope"]
        ]
        row["ranking_basis"] = dict(
            confirmed_failures=sum(o["status"] == "FAIL" for o in obligations),
            remaining=len(row["remaining_obligations"]),
            shared_issues=len(
                {
                    i
                    for f in campaigns
                    if row["number"] in f["issues"]
                    for i in f["issues"]
                }
            ),
        )
        row["ranking_explanation"] = (
            "Confirmed failing obligations first, then shared selected-family impact, then concrete remaining obligations; decisions and unmapped scope remain blocking."
        )
    ranked = sorted(
        (row for row in queue if row["state"] == "OPEN"),
        key=lambda r: (
            -r["ranking_basis"]["confirmed_failures"],
            -r["ranking_basis"]["shared_issues"],
            -r["ranking_basis"]["remaining"],
            r["number"],
        ),
    )
    for index, row in enumerate(ranked, 1):
        row["rank"] = index
    inactive = sorted(
        (row for row in queue if row["state"] != "OPEN"),
        key=lambda row: row["number"],
    )
    for row in inactive:
        row["rank"] = None
    return ranked + inactive


def source_drift(lock, heads):
    rows = []
    for name, source in lock["sources"].items():
        if name == "bng3":
            continue
        observed = (heads or {}).get("sources", {}).get(name)
        status = "UNOBSERVED"
        if observed:
            observed_repository = (
                observed.get("repository", "").lower().removesuffix(".git")
            )
            if observed_repository != source["repository"].lower().removesuffix(".git"):
                raise ValueError("upstream repository identity differs: " + name)
            if observed.get("branch") != source["branch"]:
                raise ValueError("upstream branch identity differs: " + name)
            revision = observed.get("revision")
            if revision is None:
                status = "UNAVAILABLE"
            elif not isinstance(revision, str) or not re.fullmatch(
                "[0-9a-f]{40}", revision
            ):
                raise ValueError("invalid upstream revision: " + name)
            else:
                status = "MATCHES_LOCK" if revision == source["revision"] else "DRIFTED"
        rows.append(
            dict(
                source=name,
                locked_revision=source["revision"],
                observed_revision=(observed or {}).get("revision"),
                status=status,
                approval=source.get("status"),
                related_issues=[137, 179, 180],
            )
        )
    return rows


def collect_heads(lock, directory):
    sources = {}
    for name, source in lock["sources"].items():
        if name == "bng3":
            continue
        work = directory / name
        receipt = campaign.run_command(
            [
                "git",
                "ls-remote",
                "--refs",
                source["repository"],
                "refs/heads/" + source["branch"],
            ],
            work,
            20,
        )
        lines = (work / "stdout.log").read_text().splitlines()
        revision = None
        if receipt["status"] == "PASS" and len(lines) == 1:
            fields = lines[0].split()
            if len(fields) == 2 and fields[1] == "refs/heads/" + source["branch"]:
                revision = fields[0]
        sources[name] = dict(
            repository=source["repository"],
            branch=source["branch"],
            revision=revision,
            receipt=str(work / "command.json"),
        )
    return dict(sources=sources)


def provenance_debt(heads=None):
    from scripts.validate_provenance import validate_lock, validate_ledger
    from scripts.validate_reconciliation_tests import (
        CLAIM_CLASSIFICATIONS,
        evidence_inventory,
        load_ledgers,
        validate_test_references,
    )

    lock = json.loads((ROOT / "provenance/upstreams.lock.yml").read_text())
    errors, warnings = validate_lock(lock, require_approved=True, repository_root=ROOT)
    ledgers = load_ledgers(ROOT / "provenance/reconciliation")
    claims = []
    for path, ledger in ledgers:
        for entry in ledger.get("entries", []):
            if entry.get("classification") not in CLAIM_CLASSIFICATIONS:
                continue
            claims.append(
                dict(
                    source=ledger.get("source", path.stem),
                    source_revision=entry.get("source_revision"),
                    capability=entry.get("capability"),
                    tests=entry.get("tests", []),
                    evidence=(
                        "REFERENCE_ONLY" if entry.get("tests") else "NO_TEST_REFERENCE"
                    ),
                    execution_claim=False,
                    related_issues=[180],
                )
            )
    return dict(
        inputs={
            str(path.relative_to(ROOT)): inventory.sha256(path)
            for path in [
                ROOT / "provenance/upstreams.lock.yml",
                *[path for path, _ in ledgers],
            ]
        },
        strict_approval_errors=errors,
        warnings=warnings,
        source_drift=source_drift(lock, heads),
        reconciliation_inventory=evidence_inventory(ledgers),
        ledger_errors=[
            error for _, ledger in ledgers for error in validate_ledger(ledger, lock)
        ],
        stale_test_references=validate_test_references(ledgers, ROOT),
        reconciliation_claims=claims,
        approvals_modified=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues-json", type=Path, required=True)
    parser.add_argument(
        "--obligations-json",
        type=Path,
        default=ROOT / "provenance/issue-obligations.json",
    )
    parser.add_argument("--max-families", type=int, default=3)
    parser.add_argument("--report", action="append", type=Path, default=[])
    parser.add_argument("--issue142-release-record", type=Path)
    parser.add_argument("--issue142-identity-report", type=Path)
    parser.add_argument("--issue142-observables-report", type=Path)
    parser.add_argument("--s6-simulate-receipt-dir", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--upstream-heads", type=Path)
    parser.add_argument("--collect-upstream-heads", action="store_true")
    args = parser.parse_args(argv)
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("output directory must be empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.revision != campaign.git(ROOT, "rev-parse", "HEAD"):
            raise ValueError("requested revision differs from checked-out candidate")
        issues_bytes = args.issues_json.read_bytes()
        issues = json.loads(issues_bytes)
        reports = [json.loads(path.read_text()) for path in args.report]
        receipt_reports = []
        if args.issue142_release_record:
            if (
                not args.issue142_identity_report
                or not args.issue142_observables_report
            ):
                raise ValueError(
                    "Issue 142 receipt requires both raw child reports for exact evidence"
                )
            receipt_reports = issue142_receipt_reports(
                json.loads(args.issue142_release_record.read_text()),
                args.issue142_identity_report,
                args.issue142_observables_report,
                args.revision,
                artifact_run_id=os.environ.get("GITHUB_RUN_ID"),
            )
            reports.extend(receipt_reports)
            queue_receipt = receipt_reports[-1]
            receipt_reports = [
                dict(
                    kind="issue142-release-record",
                    path=str(args.issue142_release_record),
                    sha256=inventory.sha256(args.issue142_release_record),
                    replay_references=queue_receipt.get("replay_references", {}),
                    component_reports=[
                        {
                            "path": str(path),
                            "sha256": inventory.sha256(path),
                        }
                        for path in (
                            args.issue142_identity_report,
                            args.issue142_observables_report,
                        )
                    ],
                ),
            ]
        if args.s6_simulate_receipt_dir:
            if campaign.git(ROOT, "status", "--porcelain"):
                raise ValueError("S6 receipt consumer requires a clean candidate tree")
            workflow_run_id = os.environ.get("GITHUB_RUN_ID")
            if not workflow_run_id:
                raise ValueError(
                    "S6 receipt consumer requires the workflow run identity"
                )
            contract_path = ROOT / S6_SIMULATE_CONTRACT
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            s6_report = s6_simulate_receipt_report(
                args.s6_simulate_receipt_dir,
                args.revision,
                contract,
                artifact_run_id=workflow_run_id,
            )
            reports.append(s6_report)
            receipt_reports.append(
                {
                    "kind": "s6-simulate-option-receipts",
                    "path": str(args.s6_simulate_receipt_dir),
                    "artifact_name": s6_report["artifact"]["name"],
                    "workflow_run_id": s6_report["artifact"]["workflow_run_id"],
                    "files": [
                        {
                            "name": f"{row}.json",
                            "sha256": s6_report["references"]["s6_receipts"][
                                row.replace(".", "_")
                            ]["sha256"],
                        }
                        for row in S6_SIMULATE_ROWS
                    ],
                }
            )
        heads = (
            json.loads(args.upstream_heads.read_text()) if args.upstream_heads else None
        )
        if args.collect_upstream_heads:
            if heads is not None:
                raise ValueError(
                    "choose a supplied or collected upstream snapshot, not both"
                )
            lock = json.loads((ROOT / "provenance/upstreams.lock.yml").read_text())
            heads = collect_heads(lock, args.output_dir / "upstream-commands")
        catalog = json.loads(args.obligations_json.read_text())
        obligations = obligation_inventory(issues, catalog)
        assessment = assess_obligations(obligations, reports, args.revision)
        conflicts = {
            a["id"] for a in assessment["evidence_audit"] if a["status"] == "CONFLICT"
        }
        usable = [
            dict(
                r,
                results=[
                    row for row in r.get("results", []) if row["id"] not in conflicts
                ],
            )
            for r in reports
            if _report_status(r, args.revision) is None
        ]
        campaigns = select_campaign(
            assessment["obligations"],
            findings=[row for r in usable for row in r.get("results", [])],
            max_families=args.max_families,
            active_issues={
                issue["number"] for issue in issues if issue.get("state") == "OPEN"
            },
        )
        queue = acceptance_dashboard(
            build_queue(issues, usable, args.revision), assessment, campaigns
        )
        report = dict(
            schema_version=1,
            revision=args.revision,
            issue_snapshot_sha256=inventory.sha256(args.issues_json),
            issue_snapshot_scope="provided snapshot; collection completeness not inferred",
            evidence_reports=[
                dict(path=str(p), sha256=inventory.sha256(p)) for p in args.report
            ]
            + receipt_reports,
            queue=queue,
            acceptance=assessment,
            campaign_selection=campaigns,
            obligations_sha256=inventory.sha256(args.obligations_json),
            authorization="Existing campaign limits remain in force; selections are plans only.",
            provenance=provenance_debt(heads),
        )
        (args.output_dir / "issues-input.json").write_bytes(issues_bytes)
        if heads is not None:
            (args.output_dir / "upstream-heads.json").write_text(
                json.dumps(heads, indent=2) + "\n"
            )
        (args.output_dir / "issue-queue.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        for filename, value in (
            ("obligation-assessment.json", assessment),
            ("campaign-selection.json", campaigns),
        ):
            (args.output_dir / filename).write_text(json.dumps(value, indent=2) + "\n")
        from .ci_report import acceptance_markdown

        lines = acceptance_markdown(report).splitlines()
        debt = report["provenance"]
        lines += [
            "",
            f"Strict approval blockers: {len(debt['strict_approval_errors'])}; stale reconciliation references: {len(debt['stale_test_references'])}.",
            "Reconciliation test references are source evidence, not proof of current execution. See issue-queue.json for named claims and upstream observations.",
            "",
        ]
        (args.output_dir / "issue-queue.md").write_text("\n".join(lines))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        (args.output_dir / "error.json").write_text(
            json.dumps(dict(status="HARNESS_ERROR", detail=str(exc)), indent=2) + "\n"
        )
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
