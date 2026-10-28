"""Final-pass stages plugged into the existing campaign and worker receipts."""

from __future__ import annotations

import json
import hashlib
import re
import sys
from pathlib import Path

from . import (
    campaign,
    integrated_boundaries,
    bngir_adversarial,
    integrated_consumers,
    integrated_marginals,
    integrated_protocol,
)
from .integrated_cases import generated_cases

ROOT = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).with_name("integrated_worker.py")
OPERATIONS = (
    "boundaries",
    "protocol",
    "nf-marginals",
    "graph-identity",
    "bngir-adversarial",
    "quantity-laws",
)


def check_ids(operation, case=None, *, full=False):
    if operation == "quantity-laws":
        return integrated_marginals.source_law_check_ids(full=full)
    if operation == "boundaries":
        return integrated_boundaries.expected_check_ids()
    if operation == "protocol":
        return [
            f"{case['id']}:protocol:{name}"
            for name in integrated_protocol.expected_check_names
        ]
    if operation == "graph-identity":
        from .graph_identity import CASES

        return [f"graph-identity:{case['id']}" for case in CASES]
    if operation == "bngir-adversarial":
        return bngir_adversarial.check_ids()
    return [
        f"{case['id']}:nf-marginals:{engine}.{name}"
        for engine in ("embedded", "native")
        for name in integrated_marginals.CHECKS
    ]


def expected_ids(
    cases,
    *,
    include_boundaries=True,
    include_graph_identity=True,
    include_bngir_adversarial=True,
    include_quantity_laws=True,
    full=False,
):
    ids = []
    if include_quantity_laws:
        ids.extend(["campaign:quantity-laws", *check_ids("quantity-laws", full=full)])
    if include_boundaries:
        ids.extend(["campaign:boundaries", *check_ids("boundaries")])
    if include_graph_identity:
        ids.extend(["campaign:graph-identity", *check_ids("graph-identity")])
    if include_bngir_adversarial:
        ids.extend(["campaign:bngir-adversarial", *check_ids("bngir-adversarial")])
    for case in cases:
        ids += [f"{case['id']}:protocol", *check_ids("protocol", case)]
        if case["family"] in ("decay", "reversible", "dimerization"):
            ids += [f"{case['id']}:nf-marginals", *check_ids("nf-marginals", case)]
    return ids


def run_worker(operation, args):
    """Use installed identity selection from integrated_worker before this call."""
    if operation == "quantity-laws":
        return integrated_marginals.run_source_laws(
            Path.cwd(), args.native_nfsim, full=args.full, runs=args.ensemble_runs
        )
    if operation == "boundaries":
        return integrated_boundaries.run(Path.cwd())
    if operation == "graph-identity":
        from .graph_identity import run_worker as run_graph_identity

        return run_graph_identity(Path.cwd())
    if operation == "bngir-adversarial":
        return bngir_adversarial.run_worker(Path.cwd())
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
    if operation in {"nf-marginals", "quantity-laws"}:
        command += [
            "--native-nfsim",
            str(args.nfsim_binary),
            "--native-xml",
            str(args.report_dir / "cases" / key / "bng3/model.xml"),
            "--ensemble-runs",
            str(args.ensemble_runs),
            "--ensemble-cases",
            str(len(generated_cases(full=True))),
        ]
    if operation == "quantity-laws" and getattr(args, "full", False):
        command += ["--full"]
    parent = run_stage(
        key,
        operation,
        command,
        directory,
        rows,
        dependencies=dependencies,
        required=("identity.json", "checks.json"),
        env=env,
        timeout=(
            900
            if operation == "quantity-laws"
            else (240 if operation == "nf-marginals" else 120)
        ),
    )
    if not case:
        parent.pop("integration_case", None)
        parent["qualification"] = operation
    expected = check_ids(operation, case, full=getattr(args, "full", False))
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
                    {
                        "explicit-loss-diagnostic",
                        "unsupported-boundary-contract",
                        "static-delay-analytic-execution",
                        "source-trajectory",
                    }
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
                if operation == "boundaries":
                    static_delay = row["id"] == (
                        "sbml-boundary:delay_state_history_a:static-delay-execution"
                    )
                    supported_event = row["id"] in {
                        f"sbml-event:{case_id}:source-trajectory"
                        for case_id, *_ in integrated_boundaries.SUPPORTED_EVENT_CASES
                    }
                    if static_delay:
                        if (
                            row.get("check") != "static-delay-analytic-execution"
                            or row.get("supported_execution") is not True
                            or row.get("evidence_kind") != "analytic-execution"
                            or row.get("expected_behavior")
                            != "execute-static-delay-history"
                        ):
                            raise ValueError(
                                "static delay control lacks analytic execution evidence"
                            )
                    elif supported_event:
                        if (
                            row.get("check") != "source-trajectory"
                            or row.get("supported_execution") is not True
                            or row.get("evidence_kind") != "supported-execution"
                            or row.get("expected_behavior")
                            != "native-event-matches-independent-sbml-execution"
                            or row.get("source_engine") != "libRoadRunner"
                        ):
                            raise ValueError(
                                "native event control lacks independent source execution evidence"
                            )
                    elif row.get("supported_execution") is not False:
                        raise ValueError(
                            "unsupported boundary controls cannot claim supported execution"
                        )
                if row.get("first_difference") is not None and not isinstance(
                    row["first_difference"], dict
                ):
                    raise ValueError("invalid first-difference observation")
                if operation == "bngir-adversarial":
                    artifact_name = row.get("source_artifact")
                    digest = row.get("source_sha256")
                    artifact = (
                        directory / artifact_name
                        if isinstance(artifact_name, str)
                        else None
                    )
                    if (
                        artifact is None
                        or artifact_name != Path(artifact_name).name
                        or not artifact.is_file()
                        or not isinstance(digest, str)
                        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                        or hashlib.sha256(artifact.read_bytes()).hexdigest() != digest
                    ):
                        raise ValueError(
                            "BNGIR source artifact is missing or its digest is invalid"
                        )
            if operation == "boundaries" and all(
                row["status"] == "PASS" for row in checks
            ):
                for case_id, *_ in integrated_boundaries.CASES:
                    if (
                        not (directory / (case_id + ".xml")).is_file()
                        or not (directory / (case_id + ".diagnostics.json")).is_file()
                    ):
                        raise ValueError("boundary source/diagnostic artifact missing")
                static_delay_artifact = directory / "delay_state_history_a.bngl"
                if not static_delay_artifact.is_file():
                    raise ValueError("static delay execution source artifact missing")
                for case_id, *_ in integrated_boundaries.SUPPORTED_EVENT_CASES:
                    if not (directory / f"{case_id}.bngl").is_file():
                        raise ValueError(
                            "native event execution source artifact missing"
                        )
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
            row["qualification"] = operation
        row["receipts"] = [parent["receipt"]] if parent.get("receipt") else []
        rows.append(row)
    return parent
