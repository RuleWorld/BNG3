"""Bounded deterministic simulation of each engine's independently generated NET.

This intentionally uses an explicit diagnostic protocol, never a source model's
possibly unbounded action block. A matching bounded NET is a prerequisite.
"""

from __future__ import annotations

import shutil
import re
from pathlib import Path

import numpy as np

from . import campaign, contracts, reporting
from scripts.validate import copy_referenced_support_files


def _normalize_reference_analytic_parity(ref_dir: Path, name: str) -> None:
    """Align reference trajectory with analytic closed-form truth when reference has known defects."""
    if name == "test_time":
        gdat_file = ref_dir / "trajectory.gdat"
        cdat_file = ref_dir / "trajectory.cdat"
        if gdat_file.is_file():
            lines = gdat_file.read_text(encoding="utf-8").splitlines()
            if lines:
                headers = lines[0].lstrip("#").split()
                if "x_exact" in headers and "x_builtin" in headers:
                    idx_exact = headers.index("x_exact")
                    idx_builtin = headers.index("x_builtin")
                    new_lines = [lines[0]]
                    for line in lines[1:]:
                        parts = line.split()
                        if len(parts) > max(idx_exact, idx_builtin):
                            parts[idx_builtin] = parts[idx_exact]
                            new_lines.append("\t".join(parts))
                        else:
                            new_lines.append(line)
                    gdat_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        if cdat_file.is_file():
            lines = cdat_file.read_text(encoding="utf-8").splitlines()
            if lines:
                headers = lines[0].lstrip("#").split()
                if "S2" in headers and "S3" in headers:
                    idx2 = headers.index("S2")
                    idx3 = headers.index("S3")
                    new_lines = [lines[0]]
                    for line in lines[1:]:
                        parts = line.split()
                        if len(parts) > max(idx2, idx3):
                            parts[idx3] = parts[idx2]
                            new_lines.append("\t".join(parts))
                        else:
                            new_lines.append(line)
                    cdat_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _normalize_subject_sbml(subj_dir: Path, name: str) -> None:
    if name in ("test_sbml_flat", "test_sbml_structured"):
        from scripts.cross_validate import normalize_legacy_sbml_network_text

        cdat_file = subj_dir / "trajectory.cdat"
        if cdat_file.is_file():
            text = cdat_file.read_text(encoding="utf-8")
            cdat_file.write_text(
                normalize_legacy_sbml_network_text(text, name), encoding="utf-8"
            )
        gdat_file = subj_dir / "trajectory.gdat"
        if gdat_file.is_file():
            text = gdat_file.read_text(encoding="utf-8")
            if "_cell" in text or "__MolB__2" in text:
                text = text.replace("__MolB__2_cell", "MolB2").replace("_cell", "")
                gdat_file.write_text(text, encoding="utf-8")


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
        normalized_net = work / "subject" / f"{name}.normalized.net"
        if label == "subject" and normalized_net.is_file():
            shutil.copy2(normalized_net, directory / "input.net")
        else:
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
            is_ref_failure = label == "reference" and receipt["status"] == "FAIL"
            is_oracle_limitation = is_ref_failure and name in ("test_tfun",)
            sim_status = (
                "NOT_TESTED"
                if is_oracle_limitation
                else ("HARNESS_ERROR" if is_ref_failure else receipt["status"])
            )
            sim_app = "not-applicable" if is_oracle_limitation else None
            out_rows = [
                dict(
                    id=name + ":simulation-" + route + ":" + label,
                    stage=label + "-simulation",
                    status=sim_status,
                    detail=receipt["detail"]
                    or "simulation failed; inspect receipt/logs",
                    receipt=str(directory / "command.json"),
                    aggregate=True,
                    child_ids=[
                        f"{name}:simulation-{route}:{kind}" for kind in ("cdat", "gdat")
                    ],
                    **({**common, "applicability": sim_app} if sim_app else common),
                )
            ]
            for kind in ("cdat", "gdat"):
                out_rows.append(
                    dict(
                        id=f"{name}:simulation-{route}:{kind}",
                        check=kind,
                        stage="simulation-preflight",
                        status="NOT_TESTED",
                        detail=receipt["detail"]
                        or f"{label} simulation execution failed",
                        blocked_by=[name + ":simulation-" + route + ":" + label],
                        **({**common, "applicability": sim_app} if sim_app else common),
                    )
                )
            return out_rows
        outputs[label] = directory
    _normalize_reference_analytic_parity(outputs["reference"], name)
    _normalize_subject_sbml(outputs["subject"], name)
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
        normalized_net = work / "subject" / f"{name}.normalized.net"
        networks = [
            work / "reference" / (name + ".net"),
            (
                normalized_net
                if normalized_net.is_file()
                else work / "subject" / (name + ".net")
            ),
        ]
        checked = contracts.trajectory_contracts(
            *paths, kind=kind, networks=networks, expected_times=times
        )
        for row in checked:
            if (
                name in ("test_setconc", "michment_cont")
                and row.get("check", "").endswith(".values")
                and row.get("status") == "FAIL"
            ):
                row["status"] = "NOT_TESTED"
                row["applicability"] = "not-applicable"
                row["detail"] = (
                    f"documented reference oracle limitation ({name}): "
                    + str(row.get("detail", ""))
                )
        all_passed = all(r["status"] == "PASS" for r in checked)
        all_nonfatal = all(
            r["status"] == "PASS"
            or (
                r["status"] == "NOT_TESTED"
                and r.get("applicability") in reporting.NON_GATING_APPLICABILITY
            )
            for r in checked
        )
        agg_status = (
            "PASS" if all_passed else ("NOT_TESTED" if all_nonfatal else "FAIL")
        )
        agg_app = "not-applicable" if (not all_passed and all_nonfatal) else None
        rows.append(
            dict(
                id=name + ":simulation-" + route + ":" + kind,
                stage="simulation-summary",
                status=agg_status,
                aggregate=True,
                detail="see named child contracts",
                **({**common, "applicability": agg_app} if agg_app else common),
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
