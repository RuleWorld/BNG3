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
    api_surface,
    stochastic_parity,
    graph_identity_contract,
    bngir_format_contracts,
    bngir_reconstruction_contracts,
    bngsim_boundary,
    integrated_consumers,
    integrated_marginals,
    integrated_protocol,
    export_format_tier,
    jax_backend_measurement,
    netrule_execution,
    nfnext_slices,
    rate_law_contract,
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
    "export-format-tier",
    "netrule-execution",
    "bngsim-boundary",
    "jax-backend-measurement",
    "rate-law-contract",
    "nfnext-slices",
    "api-surface",
    "stochastic-parity",
    "graph-identity-contract",
)

# The focused-campaign flag that reproduces one qualification on its own.
FOCUS_FLAGS = {
    "quantity-laws": "--quantity-laws-only",
    "boundaries": "--boundaries-only",
    "bngir-adversarial": "--bngir-adversarial-only",
    "graph-identity": "--graph-identity-only",
    "export-format-tier": "--export-format-tier-only",
    "jax-backend-measurement": "--jax-backend-measurement-only",
    "rate-law-contract": "--rate-law-contract-only",
    "nfnext-slices": "--nfnext-slices-only",
    "api-surface": "--api-surface-only",
    "stochastic-parity": "--stochastic-parity-only",
    "graph-identity-contract": "--graph-identity-contract-only",
}


def check_ids(operation, case=None, *, full=False):
    if operation == "quantity-laws":
        return integrated_marginals.source_law_check_ids(full=full)
    if operation == "bngsim-boundary":
        return bngsim_boundary.check_ids()
    if operation == "boundaries":
        return integrated_boundaries.expected_check_ids()
    if operation == "netrule-execution":
        return netrule_execution.check_ids()
    if operation == "jax-backend-measurement":
        return jax_backend_measurement.check_ids()
    if operation == "api-surface":
        return api_surface.check_ids()
    if operation == "stochastic-parity":
        return stochastic_parity.check_ids()
    if operation == "graph-identity-contract":
        from .graph_identity_contract import (
            CASES as GRAPH_CASES,
            CHECKS as GRAPH_CHECKS,
        )

        return [
            f"graph-identity-contract:{case['id']}:{check}"
            for case in GRAPH_CASES
            for check in GRAPH_CHECKS
        ]
    if operation == "api-surface":
        return api_surface.run(Path.cwd())
    if operation == "stochastic-parity":
        return stochastic_parity.run_worker(Path.cwd())
    if operation == "graph-identity-contract":
        return graph_identity_contract.run_worker(Path.cwd())
    if operation == "rate-law-contract":
        return rate_law_contract.check_ids()
    if operation == "nfnext-slices":
        return nfnext_slices.check_ids()
    if operation == "protocol":
        return [
            f"{case['id']}:protocol:{name}"
            for name in integrated_protocol.expected_check_names
        ]
    if operation == "graph-identity":
        from .graph_identity import CASES

        return [f"graph-identity:{case['id']}" for case in CASES]
    if operation == "bngir-adversarial":
        return [
            *bngir_adversarial.check_ids(),
            *bngir_format_contracts.check_ids(),
            *bngir_reconstruction_contracts.check_ids(),
        ]
    if operation == "export-format-tier":
        return export_format_tier.check_ids()
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
    include_export_format_tier=True,
    include_netrule_execution=True,
    include_bngsim_boundary=True,
    include_jax_backend_measurement=True,
    include_rate_law_contract=True,
    include_nfnext_slices=True,
    include_api_surface=True,
    include_stochastic_parity=True,
    include_graph_identity_contract=True,
    full=False,
):
    ids = []
    if include_quantity_laws:
        ids.extend(["campaign:quantity-laws", *check_ids("quantity-laws", full=full)])
    if include_bngsim_boundary:
        ids.extend(["campaign:bngsim-boundary", *check_ids("bngsim-boundary")])
    if include_boundaries:
        ids.extend(["campaign:boundaries", *check_ids("boundaries")])
    if include_graph_identity:
        ids.extend(["campaign:graph-identity", *check_ids("graph-identity")])
    if include_bngir_adversarial:
        ids.extend(["campaign:bngir-adversarial", *check_ids("bngir-adversarial")])
    if include_export_format_tier:
        ids.extend(["campaign:export-format-tier", *check_ids("export-format-tier")])
    if include_netrule_execution:
        ids.extend(["campaign:netrule-execution", *check_ids("netrule-execution")])
    if include_jax_backend_measurement:
        ids.extend(
            [
                "campaign:jax-backend-measurement",
                *check_ids("jax-backend-measurement"),
            ]
        )
    if include_rate_law_contract:
        ids.extend(["campaign:rate-law-contract", *check_ids("rate-law-contract")])
    if include_nfnext_slices:
        ids.extend(["campaign:nfnext-slices", *check_ids("nfnext-slices")])
    if include_api_surface:
        ids.extend(["campaign:api-surface", *check_ids("api-surface")])
    if include_stochastic_parity:
        ids.extend(["campaign:stochastic-parity", *check_ids("stochastic-parity")])
    if include_graph_identity_contract:
        ids.extend(
            [
                "campaign:graph-identity-contract",
                *check_ids("graph-identity-contract"),
            ]
        )
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
    if operation == "bngsim-boundary":
        return bngsim_boundary.run(Path.cwd(), runs=args.ensemble_runs)
    if operation == "boundaries":
        return integrated_boundaries.run(Path.cwd())
    if operation == "netrule-execution":
        return netrule_execution.run_worker(Path.cwd())
    if operation == "jax-backend-measurement":
        return jax_backend_measurement.run_worker(Path.cwd())
    if operation == "api-surface":
        return api_surface.check_ids()
    if operation == "stochastic-parity":
        return stochastic_parity.check_ids()
    if operation == "graph-identity-contract":
        from .graph_identity_contract import (
            CASES as GRAPH_CASES,
            CHECKS as GRAPH_CHECKS,
        )

        return [
            f"graph-identity-contract:{case['id']}:{check}"
            for case in GRAPH_CASES
            for check in GRAPH_CHECKS
        ]
    if operation == "api-surface":
        return api_surface.run(Path.cwd())
    if operation == "stochastic-parity":
        return stochastic_parity.run_worker(Path.cwd())
    if operation == "graph-identity-contract":
        return graph_identity_contract.run_worker(Path.cwd())
    if operation == "rate-law-contract":
        return rate_law_contract.run_worker(Path.cwd())
    if operation == "nfnext-slices":
        return nfnext_slices.run_worker(Path.cwd())
    if operation == "graph-identity":
        from .graph_identity import run_worker as run_graph_identity

        return run_graph_identity(Path.cwd())
    if operation == "bngir-adversarial":
        return [
            *bngir_adversarial.run_worker(Path.cwd()),
            *bngir_format_contracts.run_worker(Path.cwd()),
            *bngir_reconstruction_contracts.run_worker(Path.cwd()),
        ]
    if operation == "export-format-tier":
        return export_format_tier.run_worker(Path.cwd(), bng_cpp=args.bng_cpp)
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
    if operation == "export-format-tier":
        command += ["--bng-cpp", str(args.bng_cpp)]
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
            else (
                240
                if operation == "nf-marginals"
                else (
                    300
                    if operation == "export-format-tier"
                    else (600 if operation == "jax-backend-measurement" else 120)
                )
            )
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
                if operation in (
                    "bngir-adversarial",
                    "netrule-execution",
                    "rate-law-contract",
                    "nfnext-slices",
                ):
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
