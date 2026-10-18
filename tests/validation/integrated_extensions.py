"""Final-pass stages plugged into the existing campaign and worker receipts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import (
    campaign,
    integrated_boundaries,
    integrated_consumers,
    integrated_marginals,
    integrated_protocol,
)
from .integrated_cases import generated_cases

ROOT = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).with_name("integrated_worker.py")
OPERATIONS = ("boundaries", "protocol", "nf-marginals")


def check_ids(operation, case=None):
    if operation == "boundaries":
        return integrated_boundaries.expected_check_ids()
    if operation == "protocol":
        return [
            f"{case['id']}:protocol:{name}"
            for name in integrated_protocol.expected_check_names
        ]
    return [
        f"{case['id']}:nf-marginals:{engine}.{name}"
        for engine in ("embedded", "native")
        for name in integrated_marginals.CHECKS
    ]


def expected_ids(cases):
    ids = ["campaign:boundaries", *check_ids("boundaries")]
    for case in cases:
        ids += [f"{case['id']}:protocol", *check_ids("protocol", case)]
        if case["family"] in ("decay", "reversible", "dimerization"):
            ids += [f"{case['id']}:nf-marginals", *check_ids("nf-marginals", case)]
    return ids


def run_worker(operation, args):
    """Use installed identity selection from integrated_worker before this call."""
    if operation == "boundaries":
        return integrated_boundaries.run(Path.cwd())
    if operation == "protocol":
        rows = integrated_protocol.run(
            args.input, args.case_id, Path.cwd(), case=json.loads(args.case_json)
        )
        return [
            dict(row, id=row["check"], check=row["check"].rsplit(":", 1)[-1])
            for row in rows
        ]
    case = json.loads(args.case_json)
    rows = integrated_marginals.run(
        args.input,
        case,
        args.native_nfsim,
        args.native_xml,
        Path.cwd(),
        runs=args.ensemble_runs,
        cases=args.ensemble_cases,
    )
    return [dict(row, id=f"{args.case_id}:nf-marginals:{row['check']}") for row in rows]


def invoke(operation, args, rows, env, run_stage, *, case=None, dependencies=()):
    key = case["id"] if case else "campaign"
    directory = args.report_dir / ("cases/" + key if case else "campaign") / operation
    source = (
        args.report_dir / "cases" / key / "atomizer/model.bngl"
        if case
        else Path(integrated_boundaries.__file__)
    )
    command = [
        sys.executable,
        "-I",
        "-B",
        str(WORKER),
        operation,
        "--input",
        str(source),
        "--case-id",
        key,
    ]
    if case is not None:
        command += ["--case-json", json.dumps(case, sort_keys=True)]
    if operation == "nf-marginals":
        command += [
            "--native-nfsim",
            str(args.nfsim_binary),
            "--native-xml",
            str(args.report_dir / "cases" / key / "bng2/model.xml"),
            "--ensemble-runs",
            str(args.ensemble_runs),
            "--ensemble-cases",
            str(len(generated_cases(full=True))),
        ]
    parent = run_stage(
        key,
        operation,
        command,
        directory,
        rows,
        dependencies=dependencies,
        required=("identity.json", "checks.json"),
        env=env,
        timeout=240 if operation == "nf-marginals" else 60,
    )
    if not case:
        parent.pop("integration_case", None)
        parent["qualification"] = "boundaries"
    expected = check_ids(operation, case)
    path = directory / "checks.json"
    checks = []
    try:
        if path.is_file():
            checks = json.loads(path.read_text())
            ids = [row["id"] for row in checks]
            if len(ids) != len(set(ids)) or set(ids) != set(expected):
                raise ValueError(
                    "qualification evidence identities are missing, extra or duplicated"
                )
            for row in checks:
                if row.get("status") not in campaign.STATUSES:
                    raise ValueError("invalid qualification outcome")
                expected_names = (
                    {"explicit-loss-diagnostic", "unsupported-boundary-contract"}
                    if operation == "boundaries"
                    else {row["id"].rsplit(":", 1)[-1]}
                )
                if row.get("check") not in expected_names or not isinstance(
                    row.get("detail"), str
                ):
                    raise ValueError(
                        "qualification is missing its named observation/detail"
                    )
                issues = row.get("related_issues")
                if (
                    not isinstance(issues, list)
                    or not issues
                    or any(type(n) is not int or n < 1 for n in issues)
                ):
                    raise ValueError("qualification issue links are missing or invalid")
                if (
                    operation == "boundaries"
                    and row.get("supported_execution") is not False
                ):
                    raise ValueError(
                        "boundary controls cannot claim supported execution"
                    )
                if row.get("first_difference") is not None and not isinstance(
                    row["first_difference"], dict
                ):
                    raise ValueError("invalid first-difference observation")
            if operation == "boundaries" and all(
                row["status"] == "PASS" for row in checks
            ):
                for case_id, *_ in integrated_boundaries.CASES:
                    if (
                        not (directory / (case_id + ".xml")).is_file()
                        or not (directory / (case_id + ".diagnostics.json")).is_file()
                    ):
                        raise ValueError("boundary source/diagnostic artifact missing")
        elif parent["status"] == "PASS":
            raise ValueError("qualification worker emitted no named checks")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parent.update(status="HARNESS_ERROR", detail=str(exc))
        checks = []
    if checks:
        integrated_consumers.mark_process_summary(parent, checks)
    if not checks:
        checks = [
            dict(
                id=identity,
                check=identity.rsplit(":", 1)[-1],
                status="NOT_TESTED",
                detail="qualification prerequisite did not produce complete evidence",
                blocked_by=[parent["id"]],
            )
            for identity in expected
        ]
    for row in checks:
        row["stage"] = operation
        if case:
            row["integration_case"] = key
        else:
            row["qualification"] = "boundaries"
        row["receipts"] = [parent["receipt"]] if parent.get("receipt") else []
        rows.append(row)
    return parent
