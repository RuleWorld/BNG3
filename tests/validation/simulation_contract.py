"""Bounded deterministic simulation of each engine's independently generated NET.

This intentionally uses an explicit diagnostic protocol, never a source model's
possibly unbounded action block. A matching bounded NET is a prerequisite.
"""

from __future__ import annotations

import shutil
import re
from pathlib import Path

import numpy as np

from . import campaign, contracts
from scripts.validate import copy_referenced_support_files


def simulation_text(setup, args, *, netfile=None):
    netfile_option = f',netfile=>"{netfile}"' if netfile else ""
    action = f'simulate_ode({{prefix=>"trajectory"{netfile_option},t_start=>0,t_end=>{args.simulation_end},n_steps=>{args.simulation_steps},rtol=>1e-8,atol=>1e-12,print_CDAT=>1}})'
    if re.search(r"(?m)^\s*end actions\s*$", setup):
        return re.sub(
            r"(?m)^(\s*end actions\s*)$", lambda m: action + "\n" + m[1], setup, count=1
        )
    return setup + "\n" + action + "\n"


def net_reload_context(source):
    """Keep model declarations needed to interpret a NET, without its actions."""
    lines = Path(source).read_text(encoding="utf-8").splitlines()
    context = []
    active_block = None
    for line in lines:
        if active_block is not None:
            context.append(line)
            if re.match(rf"^\s*end\s+{active_block}\s*$", line, re.IGNORECASE):
                active_block = None
            continue

        start = re.match(
            r"^\s*begin\s+(parameters|compartments)\s*$", line, re.IGNORECASE
        )
        if start:
            active_block = start.group(1).lower()
            context.append(line)

    if active_block is not None:
        raise ValueError(f"unterminated {active_block} block in NET reload source")
    return "begin model\n" + "\n".join(context) + "\nend model\n"


def _copy_staged_support_files(source, directory):
    """Copy staged sidecars while keeping the original model actions unloaded."""
    source = Path(source)
    return copy_referenced_support_files(
        source,
        source.parent,
        source.parent / "DAT_validate",
        Path(directory),
    )


def run_simulation(name, work, reference, args, env, network_rows, *, route="bngl"):
    common = dict(
        route=route,
        model=name,
        reference="bionetgen",
        question="bounded-deterministic-agreement",
        capabilities=["simulation.ode"],
    )
    blockers = [r["id"] for r in network_rows if r["status"] != "PASS"]
    if blockers:
        return [
            dict(
                id=f"{name}:simulation-{route}:{kind}",
                check=kind,
                stage="simulation-preflight",
                status="NOT_TESTED",
                detail="network prerequisites did not pass; downstream values cannot qualify",
                blocked_by=blockers,
                **common,
            )
            for kind in ("cdat", "gdat")
        ]
    if not reference or not reference.get("network_binary_sha256"):
        return [
            dict(
                id=name + ":simulation",
                stage="simulation-preflight",
                status="HARNESS_ERROR",
                detail="simulation requires --bng2-network-sha256 for independently built run_network; no golden or embedded fallback",
                **common,
            )
        ]
    # Verify again immediately before execution; the campaign also checks final
    # identity. Missing or swapped references never become simulation support.
    campaign.verify_digest(
        Path(reference["network_binary"]), reference["network_binary_sha256"]
    )
    outputs = {}
    has_observables = bool(
        contracts.strict_network(work / "reference" / (name + ".net")).groups
    )
    for label in ("reference", "subject"):
        directory = work / ("simulation-" + route) / label
        directory.mkdir(parents=True)
        net = work / label / (name + ".net")
        shutil.copy2(net, directory / "input.net")
        action = directory / "protocol.bngl"
        if route == "net-reload":
            source = work / "input" / (name + ".bngl")
            (directory / "context.bngl").write_text(
                net_reload_context(source), encoding="utf-8"
            )
            _copy_staged_support_files(source, directory)
            setup = (
                'readFile({file=>"context.bngl"})\n' 'readFile({file=>"input.net"})\n'
            )
        elif route == "bngl":
            for item in (work / "input").iterdir():
                if item.is_dir():
                    shutil.copytree(item, directory / item.name)
                else:
                    shutil.copy2(item, directory / item.name)
            setup = (work / "input" / (name + ".bngl")).read_text() + "\n"
        else:
            raise ValueError("unknown simulation route")
        action.write_text(
            simulation_text(
                setup, args, netfile="input.net" if route == "net-reload" else None
            )
        )
        command = (
            [
                reference["interpreter"],
                reference["script"],
                "--outdir",
                str(directory.resolve()),
                str(action.resolve()),
            ]
            if label == "reference"
            else [str(args.bng_cpp), str(action.resolve())]
        )
        receipt = campaign.run_command(
            command,
            directory,
            args.case_timeout,
            env=env,
            required=["trajectory.cdat"]
            + (["trajectory.gdat"] if has_observables else []),
        )
        if receipt["status"] != "PASS":
            return [
                dict(
                    id=name + ":simulation-" + route + ":" + label,
                    stage=label + "-simulation",
                    status=(
                        "HARNESS_ERROR"
                        if label == "reference" and receipt["status"] == "FAIL"
                        else receipt["status"]
                    ),
                    detail=receipt["detail"]
                    or "simulation failed; inspect receipt/logs",
                    receipt=str(directory / "command.json"),
                    **common,
                )
            ]
        outputs[label] = directory
    rows = []
    times = np.linspace(0, args.simulation_end, args.simulation_steps + 1)
    for kind in ("cdat", "gdat"):
        if kind == "gdat" and not has_observables:
            rows.append(
                dict(
                    id=name + ":simulation-" + route + ":gdat",
                    check="gdat",
                    stage="observable-trajectory",
                    status="NOT_TESTED",
                    detail="no declared observable groups; cdat still required",
                    applicability="no-observables",
                    **common,
                )
            )
            continue
        paths = [
            outputs[side] / ("trajectory." + kind) for side in ("reference", "subject")
        ]
        networks = [work / side / (name + ".net") for side in ("reference", "subject")]
        checked = contracts.trajectory_contracts(
            *paths, kind=kind, networks=networks, expected_times=times
        )
        rows.append(
            dict(
                id=name + ":simulation-" + route + ":" + kind,
                stage="simulation-summary",
                status=(
                    "PASS" if all(r["status"] == "PASS" for r in checked) else "FAIL"
                ),
                aggregate=True,
                detail="see named child contracts",
                **common,
            )
        )
        for row in checked:
            rows.append(
                dict(
                    id=name + ":simulation-" + route + ":" + row["check"],
                    stage=(
                        "species-trajectory"
                        if kind == "cdat"
                        else "observable-trajectory"
                    ),
                    **row,
                    evidence=[str(p) for p in paths],
                    receipts=[
                        str(outputs[side] / "command.json")
                        for side in ("reference", "subject")
                    ],
                    **common,
                )
            )
    return rows
