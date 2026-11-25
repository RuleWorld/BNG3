"""Authored entry-point and independent-oracle routes for locked corpus cases.

This module extends the bounded BNG2 network/ODE runner with explicit routes for
locked selection cases whose authored entry point or valid source constructs do
not execute under BNG2 network generation:

* Authored XML/SBML-Multi/hybrid/visualization exports (`cross_validate` /
  `validate_actions`), paired with pinned native `NFsim` execution where
  applicable.
* Independent SBML simulation via `libRoadRunner` (`test_sbml_flat`,
  `test_sbml_structured`) where `BNG2` lacks `sbmlTranslator`.
* Independent SciPy ODE integration for analytic BNG3-extended expressions
  (`exhaustion_switch`).
* Analytic post-action state verification (`michment_cont`, `test_setconc`) fed
  into `BNG2` `run_network` where `BNG2` drops `setConcentration` before
  `addConcentration`.
* Honest refusal (`UNSUPPORTED`) and invalid-source (`INVALID_INPUT`)
  classification (e.g. `actin_branch_forFitToData` `-rnf`).
"""

from __future__ import annotations

import math
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from . import campaign, contracts, simulation_contract

ROOT = Path(__file__).resolve().parents[2]

NETWORK_CHECKS = (
    "artifact-validity",
    "species-count",
    "species-identity",
    "initial-amounts",
    "reaction-count",
    "reaction-stoichiometry",
    "reaction-multiplicity",
    "reaction-rates",
    "observable-names",
    "observable-weights",
)

SBML_IMPORT_CASES = frozenset({"test_sbml_flat", "test_sbml_structured"})
SCIPY_ODE_CASES = frozenset({"exhaustion_switch"})
ACTION_AND_NETWORK_CASES = frozenset(
    {"hybrid_test", "test_tfun_xml", "test_write_sbml_multi", "visualize"}
)
AUTHORED_XML_AND_NETWORK_CASES = frozenset({"test_tfun"})
AUTHORED_XML_BNG2_AND_NFSIM_CASES = frozenset({"AN", "ANx"})
NFSIM_XML_CASES_DIRECT = frozenset(
    {
        "fceri_fyn",
        "fceri_fyn_lig",
        "fceri_fyn_trimer",
        "fceri_gamma2",
        "fceri_lyn_745",
        "fceri_trimer",
    }
)
NFSIM_XML_ONLY_CASES = frozenset(
    {"fceri_ji", "fceri_ji_red", "actin_branch", "actin_simple"}
)
REFUSAL_AUTHORED_CASES = frozenset({"actin_branch_forFitToData"})
POST_ACTION_CONCENTRATION_CASES = frozenset({"michment_cont", "test_setconc"})

_UNSUPPORTED_RE = re.compile(r"not supported|unsupported", re.IGNORECASE)
_INVALID_INPUT_RE = re.compile(
    r"syntax error|semantic parse failed|unrecognized token|"
    r"cannot build model from source|parse failed",
    re.IGNORECASE,
)


def classify_command_status(receipt: dict) -> tuple[str, str]:
    """Classify a failed subprocess receipt without flattening refusals/errors."""
    status = receipt.get("status", "FAIL")
    detail = str(receipt.get("detail", ""))
    if status == "PASS":
        return "PASS", "supported-execution"
    if status == "TIMEOUT":
        return "TIMEOUT", "timeout"
    if status == "HARNESS_ERROR":
        return "HARNESS_ERROR", "harness-error"
    if _UNSUPPORTED_RE.search(detail):
        return "UNSUPPORTED", "unsupported-construct"
    if _INVALID_INPUT_RE.search(detail):
        return "INVALID_INPUT", "invalid-input"
    return "FAIL", "observed-failure"


def _row(
    identity: str,
    stage: str,
    status: str,
    detail: str = "",
    *,
    model: str,
    reference: str | None = None,
    **kwargs,
) -> dict:
    row = dict(
        id=identity,
        stage=stage,
        status=status,
        detail=detail,
        model=model,
        **kwargs,
    )
    if reference is not None:
        row["reference"] = reference
    return row


def uses_custom_route(name: str) -> bool:
    """Return True when ``name`` uses an authored or dedicated oracle route."""
    return name in (
        SBML_IMPORT_CASES
        | SCIPY_ODE_CASES
        | ACTION_AND_NETWORK_CASES
        | AUTHORED_XML_AND_NETWORK_CASES
        | AUTHORED_XML_BNG2_AND_NFSIM_CASES
        | NFSIM_XML_CASES_DIRECT
        | NFSIM_XML_ONLY_CASES
        | REFUSAL_AUTHORED_CASES
        | POST_ACTION_CONCENTRATION_CASES
    )


def expected_contract_ids(
    name: str, *, simulate: bool, net_reload: bool
) -> list[str] | None:
    """Return expected contract IDs for routed cases, or None for default route."""
    if name in SBML_IMPORT_CASES or name in SCIPY_ODE_CASES:
        ids = [f"{name}:parse", f"{name}:network:artifact-validity"]
        if simulate:
            ids.append(f"{name}:simulation-bngl:gdat")
            if net_reload:
                ids.append(f"{name}:simulation-net-reload:gdat")
        return ids
    if name in AUTHORED_XML_BNG2_AND_NFSIM_CASES:
        return [f"{name}:parse", f"{name}:authored-xml", f"{name}:nfsim:gdat"]
    if name in AUTHORED_XML_AND_NETWORK_CASES:
        return (
            [f"{name}:parse"]
            + [f"{name}:network:{c}" for c in NETWORK_CHECKS]
            + [f"{name}:authored-action"]
        )
    if name in NFSIM_XML_CASES_DIRECT:
        return [f"{name}:parse", f"{name}:authored-xml", f"{name}:nfsim"]
    if name in NFSIM_XML_ONLY_CASES:
        return [f"{name}:parse", f"{name}:authored-xml", f"{name}:nfsim-consumer"]
    if name in REFUSAL_AUTHORED_CASES:
        return [f"{name}:parse", f"{name}:authored-action"]
    if name in ACTION_AND_NETWORK_CASES:
        ids = [f"{name}:parse"] + [f"{name}:network:{c}" for c in NETWORK_CHECKS]
        if simulate:
            routes = ["bngl", "net-reload"] if net_reload else ["bngl"]
            ids += [
                f"{name}:simulation-{route}:{kind}"
                for route in routes
                for kind in ("cdat", "gdat")
            ]
        ids.append(f"{name}:authored-action")
        return ids
    return None


def _stage_unmodified_source(source: Path, dest_dir: Path) -> Path:
    """Copy unmodified source BNGL and sibling data files into ``dest_dir``."""
    from scripts.validate import copy_referenced_support_files

    dest_dir.mkdir(parents=True, exist_ok=True)
    staged = dest_dir / source.name
    shutil.copy2(source, staged)
    copy_referenced_support_files(
        source,
        source.parent,
        ROOT / "tests/validation/Validate",
        dest_dir,
    )
    for rnf in source.parent.glob("*.rnf"):
        shutil.copy2(rnf, dest_dir / rnf.name)
    return staged


def _run_parse(name: str, source: Path, args, work: Path, env: dict) -> dict:
    original_dir = work / "original"
    staged = _stage_unmodified_source(source, original_dir)
    check = campaign.run_command(
        [str(args.bng_cpp), "--check", str(staged)],
        work / "parse",
        args.case_timeout,
        env=env,
    )
    status, kind = classify_command_status(check)
    return _row(
        f"{name}:parse",
        "parse",
        status,
        check["detail"],
        model=name,
        capabilities=["parser.grammar"],
        evidence_kind=kind,
        receipt=str(work / "parse/command.json"),
    )


def _validate_bng_xml(xml_path: Path, *, require_observables: bool) -> str | None:
    try:
        root = ET.parse(xml_path).getroot()
    except (ET.ParseError, OSError) as exc:
        return f"invalid BNG-XML {xml_path.name}: {exc}"
    model = next((child for child in root if child.tag.split("}")[-1] == "model"), None)
    if model is None:
        return f"missing <model> element in {xml_path.name}"
    present = {child.tag.split("}")[-1] for child in model}
    required = ["ListOfMoleculeTypes", "ListOfSpecies", "ListOfReactionRules"]
    if require_observables:
        required.append("ListOfObservables")
    missing = [tag for tag in required if tag not in present]
    if missing:
        return f"missing BNG-XML section(s) {', '.join(missing)}"
    return None


def _check_authored_action(
    name: str, source: Path, args, work: Path, env: dict, bng2_ref: dict | None
) -> dict:
    """Verify authored action exports using cross_validate / validate_actions."""
    from scripts.validate_actions import validate_action_model

    action_dir = work / "authored-action"
    action_dir.mkdir(parents=True, exist_ok=True)
    if name in {"ANx", "hybrid_test", "test_write_sbml_multi"}:
        if not bng2_ref:
            return _row(
                f"{name}:authored-action",
                "authored-action",
                "NOT_TESTED",
                "no verified BNG2 reference requested",
                model=name,
                reference="bionetgen",
            )
        from scripts.cross_validate import _run_authored_export_comparison

        status, detail = _run_authored_export_comparison(
            source,
            args.bng_cpp,
            Path(bng2_ref["script"]),
            source.parent,
            bng2_ref["interpreter"],
            args.case_timeout,
            artifact_dir=action_dir / "artifacts",
        )
        ok = status == "pass"
        return _row(
            f"{name}:authored-action",
            "authored-action",
            "PASS" if ok else ("HARNESS_ERROR" if status == "error" else "FAIL"),
            detail,
            model=name,
            reference="bionetgen",
            capabilities=[
                (
                    "export.bng_xml"
                    if name != "test_write_sbml_multi"
                    else "export.sbml_multi"
                )
            ],
            evidence_kind="supported-execution" if ok else "observed-failure",
        )
    status, detail = validate_action_model(
        args.bng_cpp,
        ROOT / "tests/validation/Validate",
        name,
    )
    mapped = (
        "PASS"
        if status == "pass"
        else (
            "NOT_TESTED"
            if status == "skip"
            else ("HARNESS_ERROR" if status == "error" else "FAIL")
        )
    )
    return _row(
        f"{name}:authored-action",
        "authored-action",
        mapped,
        detail,
        model=name,
        reference="bionetgen" if mapped == "PASS" else None,
        capabilities=["interface.cli-actions"],
        evidence_kind="supported-execution" if mapped == "PASS" else "observed-failure",
    )


def _write_gdat(path: Path, columns: list[str], data: np.ndarray) -> None:
    header = "# " + " ".join(columns)
    lines = [header] + [" ".join(f"{float(v):.15g}" for v in row) for row in data]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_params(source: Path) -> dict[str, float]:
    lines = source.read_text(encoding="utf-8").splitlines()
    params: dict[str, float] = {}
    safe_env = {"__builtins__": {}, "pow": pow, "exp": math.exp, "sqrt": math.sqrt}
    in_params = False
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if re.match(r"^begin\s+parameters\s*$", line, re.I):
            in_params = True
            continue
        if re.match(r"^end\s+parameters\s*$", line, re.I):
            in_params = False
            continue
        if in_params:
            parts = line.replace("=", " ").split(None, 1)
            if len(parts) == 2:
                try:
                    params[parts[0]] = float(eval(parts[1], safe_env, params))
                except Exception:
                    pass
    return params


def _run_sbml_import_case(
    name: str, source: Path, args, work: Path, env: dict
) -> list[dict]:
    parse_row = _run_parse(name, source, args, work, env)
    rows = [parse_row]
    if parse_row["status"] != "PASS":
        return rows

    subj_dir = work / "subject"
    staged = _stage_unmodified_source(source, subj_dir)
    # Remove any authored simulate actions; network stage validates network generation only.
    net_bngl = [
        line
        for line in staged.read_text(encoding="utf-8").splitlines()
        if not re.match(r"^\s*simulate", line, re.I)
    ]
    staged.write_text("\n".join(net_bngl) + "\n", encoding="utf-8")
    receipt = campaign.run_command(
        [str(args.bng_cpp), str(staged)],
        subj_dir,
        args.case_timeout,
        required=[f"{name}.net"],
        env=env,
    )
    if receipt["status"] != "PASS":
        status, kind = classify_command_status(receipt)
        rows.append(
            _row(
                f"{name}:network:artifact-validity",
                "network.artifact-validity",
                status,
                receipt["detail"],
                model=name,
                reference="libroadrunner",
                capabilities=["io.sbml.import"],
                evidence_kind=kind,
                receipt=str(subj_dir / "command.json"),
            )
        )
        return rows

    from scripts.cross_validate import normalize_legacy_sbml_network_file

    norm_net = subj_dir / f"{name}.normalized.net"
    normalize_legacy_sbml_network_file(subj_dir / f"{name}.net", norm_net, name)
    parsed_net = contracts.strict_network(norm_net)
    rows.append(
        _row(
            f"{name}:network:artifact-validity",
            "network.artifact-validity",
            "PASS",
            f"normalized network ({parsed_net.n_species} species, {parsed_net.n_reactions} reactions)",
            model=name,
            reference="libroadrunner",
            capabilities=["io.sbml.import", "export.net"],
            evidence_kind="supported-execution",
            receipt=str(subj_dir / "command.json"),
        )
    )
    if not args.simulate:
        return rows

    sbml_path = ROOT / "tests/validation/Validate/INPUT_FILES" / f"{name}_SBML.xml"
    try:
        import roadrunner
    except ImportError:
        for route in (["bngl", "net-reload"] if args.net_reload else ["bngl"]):
            rows.append(
                _row(
                    f"{name}:simulation-{route}:gdat",
                    "observable-trajectory",
                    "NOT_TESTED",
                    "independent libRoadRunner oracle not installed",
                    model=name,
                    reference="libroadrunner",
                    capabilities=["io.sbml.import", "simulation.ode"],
                )
            )
        return rows

    rr = roadrunner.RoadRunner(str(sbml_path))
    integrator = rr.getIntegrator()
    integrator.setValue("relative_tolerance", 1e-10)
    integrator.setValue("absolute_tolerance", 1e-12)
    times = np.linspace(0, args.simulation_end, args.simulation_steps + 1)
    rr_arr = np.asarray(
        rr.simulate(0.0, args.simulation_end, args.simulation_steps + 1)
    )

    from scripts.cross_validate import normalize_legacy_sbml_network_text

    # Map SBML species columns [S1..] -> normalized BNG observable column names.
    expected_cols = (
        ["time", "A", "B", "C", "D", "AA"]
        if name == "test_sbml_flat"
        else ["time", "MolA", "MolB", "MolA_MolB", "MolA_P", "MolB2"]
    )
    ref_gdat = work / "reference" / "roadrunner.gdat"
    ref_gdat.parent.mkdir(parents=True, exist_ok=True)
    _write_gdat(ref_gdat, expected_cols, rr_arr)

    for route in (["bngl", "net-reload"] if args.net_reload else ["bngl"]):
        sim_dir = work / f"simulation-{route}" / "subject"
        sim_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(norm_net, sim_dir / "input.net")
        proto = sim_dir / "protocol.bngl"
        if route == "net-reload":
            (sim_dir / "context.bngl").write_text(
                "begin model\nbegin parameters\nend parameters\nbegin compartments\n"
                "  cell 3 1\nend compartments\nend model\n",
                encoding="utf-8",
            )
            setup = 'readFile({file=>"context.bngl"})\nreadFile({file=>"input.net"})\n'
            proto.write_text(
                simulation_contract.simulation_text(setup, args, netfile="input.net"),
                encoding="utf-8",
            )
        else:
            _stage_unmodified_source(source, sim_dir)
            base_lines = [
                line
                for line in (sim_dir / source.name)
                .read_text(encoding="utf-8")
                .splitlines()
                if not re.match(r"^\s*simulate", line, re.I)
            ]
            proto.write_text(
                simulation_contract.simulation_text("\n".join(base_lines) + "\n", args),
                encoding="utf-8",
            )
        sim_receipt = campaign.run_command(
            [str(args.bng_cpp), str(proto)],
            sim_dir,
            args.case_timeout,
            required=["trajectory.gdat"],
            env=env,
        )
        if sim_receipt["status"] != "PASS":
            st, ek = classify_command_status(sim_receipt)
            rows.append(
                _row(
                    f"{name}:simulation-{route}:gdat",
                    "observable-trajectory",
                    st,
                    sim_receipt["detail"],
                    model=name,
                    reference="libroadrunner",
                    capabilities=["io.sbml.import", "simulation.ode"],
                    evidence_kind=ek,
                    receipt=str(sim_dir / "command.json"),
                )
            )
            continue
        gdat_path = sim_dir / "trajectory.gdat"
        text = gdat_path.read_text(encoding="utf-8")
        if "_cell" in text or "__MolB__2" in text:
            text = text.replace("__MolB__2_cell", "MolB2").replace("_cell", "")
            gdat_path.write_text(text, encoding="utf-8")
        checked = contracts.trajectory_contracts(
            ref_gdat, gdat_path, kind="gdat", expected_times=times
        )
        ok = all(r["status"] == "PASS" for r in checked)
        bad_detail = "; ".join(
            f"{r['check']}: {r.get('detail', '')}"
            for r in checked
            if r["status"] != "PASS"
        )
        rows.append(
            _row(
                f"{name}:simulation-{route}:gdat",
                "observable-trajectory",
                "PASS" if ok else "FAIL",
                "matched independent libRoadRunner SBML oracle" if ok else bad_detail,
                model=name,
                reference="libroadrunner",
                capabilities=["io.sbml.import", "simulation.ode"],
                evidence_kind="supported-execution" if ok else "observed-failure",
                receipt=str(sim_dir / "command.json"),
            )
        )
    return rows


def _run_scipy_ode_case(
    name: str, source: Path, args, work: Path, env: dict
) -> list[dict]:
    parse_row = _run_parse(name, source, args, work, env)
    rows = [parse_row]
    if parse_row["status"] != "PASS":
        return rows

    subj_dir = work / "subject"
    staged = _stage_unmodified_source(source, subj_dir)
    net_only = re.sub(r"(?im)^\s*simulate.*\n?", "", staged.read_text(encoding="utf-8"))
    staged.write_text(net_only, encoding="utf-8")
    receipt = campaign.run_command(
        [str(args.bng_cpp), str(staged)],
        subj_dir,
        args.case_timeout,
        required=[f"{name}.net"],
        env=env,
    )
    if receipt["status"] != "PASS":
        st, ek = classify_command_status(receipt)
        rows.append(
            _row(
                f"{name}:network:artifact-validity",
                "network.artifact-validity",
                st,
                receipt["detail"],
                model=name,
                reference="scipy-analytic-ode",
                capabilities=["compiler.rate-laws"],
                evidence_kind=ek,
                receipt=str(subj_dir / "command.json"),
            )
        )
        return rows

    parsed_net = contracts.strict_network(subj_dir / f"{name}.net")
    net_ok = parsed_net.n_species == 3 and parsed_net.n_reactions == 3
    rows.append(
        _row(
            f"{name}:network:artifact-validity",
            "network.artifact-validity",
            "PASS" if net_ok else "FAIL",
            f"species={parsed_net.n_species}, reactions={parsed_net.n_reactions}",
            model=name,
            reference="scipy-analytic-ode",
            capabilities=["compiler.rate-laws", "network.expansion"],
            evidence_kind="supported-execution" if net_ok else "observed-failure",
            receipt=str(subj_dir / "command.json"),
        )
    )
    if not args.simulate or not net_ok:
        return rows

    try:
        from scipy.integrate import solve_ivp
    except ImportError:
        for route in (["bngl", "net-reload"] if args.net_reload else ["bngl"]):
            rows.append(
                _row(
                    f"{name}:simulation-{route}:gdat",
                    "observable-trajectory",
                    "NOT_TESTED",
                    "independent SciPy ODE oracle not installed",
                    model=name,
                    reference="scipy-analytic-ode",
                    capabilities=["simulation.ode"],
                )
            )
        return rows

    p = _parse_params(source)
    times = np.linspace(0.0, args.simulation_end, args.simulation_steps + 1)

    def rhs(_t: float, y: list[float]) -> list[float]:
        eff, _mem, stim = y
        hill = (stim ** p["n"]) / (p["THETA"] ** p["n"] + stim ** p["n"])
        return [
            p["kprol"] * eff - p["kmem"] * hill * eff,
            p["kmem"] * hill * eff,
            p["a"],
        ]

    sol = solve_ivp(
        rhs,
        [0.0, float(args.simulation_end)],
        [p["E0"], 0.0, p["S0"]],
        t_eval=times,
        rtol=1e-11,
        atol=1e-12,
    )
    ref_arr = np.column_stack(
        [times, sol.y[0], sol.y[1], sol.y[2], sol.y[0] + sol.y[1]]
    )
    ref_gdat = work / "reference" / "scipy.gdat"
    ref_gdat.parent.mkdir(parents=True, exist_ok=True)
    _write_gdat(
        ref_gdat, ["time", "Effector", "Memory", "Stimulus", "TotalCD8"], ref_arr
    )

    for route in (["bngl", "net-reload"] if args.net_reload else ["bngl"]):
        sim_dir = work / f"simulation-{route}" / "subject"
        sim_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(subj_dir / f"{name}.net", sim_dir / "input.net")
        proto = sim_dir / "protocol.bngl"
        if route == "net-reload":
            (sim_dir / "context.bngl").write_text(
                simulation_contract.net_reload_context(source), encoding="utf-8"
            )
            setup = 'readFile({file=>"context.bngl"})\nreadFile({file=>"input.net"})\n'
            proto.write_text(
                simulation_contract.simulation_text(setup, args, netfile="input.net"),
                encoding="utf-8",
            )
        else:
            setup = re.sub(
                r"(?im)^\s*simulate.*\n?", "", source.read_text(encoding="utf-8")
            )
            proto.write_text(
                simulation_contract.simulation_text(setup, args), encoding="utf-8"
            )
        sim_receipt = campaign.run_command(
            [str(args.bng_cpp), str(proto)],
            sim_dir,
            args.case_timeout,
            required=["trajectory.gdat"],
            env=env,
        )
        if sim_receipt["status"] != "PASS":
            st, ek = classify_command_status(sim_receipt)
            rows.append(
                _row(
                    f"{name}:simulation-{route}:gdat",
                    "observable-trajectory",
                    st,
                    sim_receipt["detail"],
                    model=name,
                    reference="scipy-analytic-ode",
                    capabilities=["simulation.ode"],
                    evidence_kind=ek,
                    receipt=str(sim_dir / "command.json"),
                )
            )
            continue
        checked = contracts.trajectory_contracts(
            ref_gdat, sim_dir / "trajectory.gdat", kind="gdat", expected_times=times
        )
        ok = all(r["status"] == "PASS" for r in checked)
        bad_detail = "; ".join(
            f"{r['check']}: {r.get('detail', '')}"
            for r in checked
            if r["status"] != "PASS"
        )
        rows.append(
            _row(
                f"{name}:simulation-{route}:gdat",
                "observable-trajectory",
                "PASS" if ok else "FAIL",
                "matched independent SciPy analytic ODE" if ok else bad_detail,
                model=name,
                reference="scipy-analytic-ode",
                capabilities=["compiler.rate-laws", "simulation.ode"],
                evidence_kind="supported-execution" if ok else "observed-failure",
                receipt=str(sim_dir / "command.json"),
            )
        )
    return rows


def _run_nfsim_xml_case(
    name: str,
    source: Path,
    args,
    work: Path,
    references: dict,
    env: dict,
    *,
    compare_bng2_xml: bool,
    compare_direct_nf: bool,
) -> list[dict]:
    parse_row = _run_parse(name, source, args, work, env)
    rows = [parse_row]
    if parse_row["status"] != "PASS":
        return rows

    subj_dir = work / "subject"
    staged = _stage_unmodified_source(source, subj_dir)
    xml_receipt = campaign.run_command(
        [str(args.bng_cpp), str(staged)],
        subj_dir,
        args.case_timeout,
        required=[f"{name}.xml"],
        env=env,
    )
    if xml_receipt["status"] != "PASS":
        st, ek = classify_command_status(xml_receipt)
        rows.append(
            _row(
                f"{name}:authored-xml",
                "authored-xml",
                st,
                xml_receipt["detail"],
                model=name,
                capabilities=["export.bng_xml"],
                evidence_kind=ek,
                receipt=str(subj_dir / "command.json"),
            )
        )
        return rows

    subj_xml = subj_dir / f"{name}.xml"
    require_obs = name in {
        "AN",
        "ANx",
        "fceri_ji",
        "fceri_ji_red",
        "actin_branch",
        "actin_simple",
    }
    xml_err = _validate_bng_xml(subj_xml, require_observables=require_obs)
    if xml_err:
        rows.append(
            _row(
                f"{name}:authored-xml",
                "authored-xml",
                "FAIL",
                xml_err,
                model=name,
                capabilities=["export.bng_xml"],
                evidence_kind="observed-failure",
                receipt=str(subj_dir / "command.json"),
            )
        )
        return rows

    if compare_bng2_xml:
        bng2_ref = references.get("bionetgen")
        if not bng2_ref:
            rows.append(
                _row(
                    f"{name}:authored-xml",
                    "authored-xml",
                    "NOT_TESTED",
                    "no verified BNG2 reference requested",
                    model=name,
                    reference="bionetgen",
                )
            )
        else:
            ref_dir = work / "reference"
            ref_staged = _stage_unmodified_source(source, ref_dir)
            ref_receipt = campaign.run_command(
                [
                    bng2_ref["interpreter"],
                    bng2_ref["script"],
                    "--outdir",
                    str(ref_dir),
                    str(ref_staged),
                ],
                ref_dir,
                args.case_timeout,
                required=[f"{name}.xml"],
                env=env,
            )
            if ref_receipt["status"] != "PASS":
                rows.append(
                    _row(
                        f"{name}:authored-xml",
                        "authored-xml",
                        "NOT_TESTED",
                        ref_receipt["detail"],
                        model=name,
                        reference="bionetgen",
                    )
                )
            elif name == "ANx":
                from scripts.cross_validate import diff_structural_xml

                diff = diff_structural_xml(
                    subj_xml,
                    ref_dir / f"{name}.xml",
                    sections=(
                        "ListOfMoleculeTypes",
                        "ListOfSpecies",
                        "ListOfReactionRules",
                        "ListOfObservables",
                        "ListOfFunctions",
                    ),
                )
                rows.append(
                    _row(
                        f"{name}:authored-xml",
                        "authored-xml",
                        "PASS" if diff.equal else "FAIL",
                        diff.summary(),
                        model=name,
                        reference="bionetgen",
                        capabilities=["export.bng_xml"],
                        evidence_kind=(
                            "supported-execution" if diff.equal else "observed-failure"
                        ),
                    )
                )
            else:
                rows.append(
                    _row(
                        f"{name}:authored-xml",
                        "authored-xml",
                        "PASS",
                        "BNG3 and BNG2 writeXML outputs valid",
                        model=name,
                        reference="bionetgen",
                        capabilities=["export.bng_xml"],
                        evidence_kind="supported-execution",
                    )
                )
    else:
        rows.append(
            _row(
                f"{name}:authored-xml",
                "authored-xml",
                "PASS",
                "authored writeXML valid BNG-XML",
                model=name,
                capabilities=["export.bng_xml"],
                evidence_kind="supported-execution",
                receipt=str(subj_dir / "command.json"),
            )
        )

    nfsim_ref = references.get("nfsim")
    row_id = (
        f"{name}:nfsim:gdat"
        if compare_bng2_xml
        else (f"{name}:nfsim" if compare_direct_nf else f"{name}:nfsim-consumer")
    )
    if not nfsim_ref or not nfsim_ref.get("binary"):
        rows.append(
            _row(
                row_id,
                "nfsim-execution",
                "NOT_TESTED",
                "no verified native NFsim reference requested",
                model=name,
                reference="nfsim",
                capabilities=["backend.nfsim"],
            )
        )
        return rows

    nf_dir = work / "nfsim-oracle"
    nf_dir.mkdir(parents=True, exist_ok=True)
    xml_for_nfsim = subj_xml
    if compare_bng2_xml and (work / "reference" / f"{name}.xml").is_file():
        xml_for_nfsim = work / "reference" / f"{name}.xml"
    oracle_gdat = nf_dir / "oracle.gdat"
    nf_receipt = campaign.run_command(
        [
            nfsim_ref["binary"],
            "-xml",
            str(xml_for_nfsim),
            "-sim",
            "0.01",
            "-oSteps",
            "2",
            "-o",
            str(oracle_gdat),
            "-seed",
            "1",
        ],
        nf_dir,
        args.case_timeout,
        required=["oracle.gdat"],
        env=env,
    )
    if nf_receipt["status"] != "PASS":
        st, ek = classify_command_status(nf_receipt)
        rows.append(
            _row(
                row_id,
                "nfsim-execution",
                st,
                nf_receipt["detail"],
                model=name,
                reference="nfsim",
                capabilities=["export.bng_xml", "backend.nfsim"],
                evidence_kind=ek,
                receipt=str(nf_dir / "command.json"),
            )
        )
        return rows

    if not compare_direct_nf:
        try:
            _data, cols = contracts._trajectory(oracle_gdat)
            ok = len(cols) >= 1 and cols[0] == "time"
            detail = f"pinned native NFsim consumed exported XML ({len(cols) - 1} observables)"
        except (ValueError, OSError) as exc:
            ok = False
            detail = f"invalid NFsim output: {exc}"
        rows.append(
            _row(
                row_id,
                "nfsim-execution",
                "PASS" if ok else "FAIL",
                detail,
                model=name,
                reference="nfsim",
                capabilities=["export.bng_xml"],
                evidence_kind="supported-execution" if ok else "observed-failure",
                receipt=str(nf_dir / "command.json"),
            )
        )
        return rows

    cpp_nf_dir = work / "nfsim-subject"
    staged_nf = _stage_unmodified_source(source, cpp_nf_dir)
    nf_text = re.sub(
        r"(?im)^\s*writeXML\s*\([^)]*\)\s*;?\s*$",
        'simulate_nf({t_end=>0.01,n_steps=>2,seed=>1,suffix=>"cpp_nf"})',
        staged_nf.read_text(encoding="utf-8"),
    )
    if "simulate_nf" not in nf_text:
        nf_text += '\nsimulate_nf({t_end=>0.01,n_steps=>2,seed=>1,suffix=>"cpp_nf"})\n'
    staged_nf.write_text(nf_text, encoding="utf-8")
    cpp_gdat_name = f"{source.stem}_cpp_nf.gdat"
    cpp_receipt = campaign.run_command(
        [str(args.bng_cpp), str(staged_nf)],
        cpp_nf_dir,
        args.case_timeout,
        required=[cpp_gdat_name],
        env=env,
    )
    if cpp_receipt["status"] != "PASS":
        st, ek = classify_command_status(cpp_receipt)
        rows.append(
            _row(
                row_id,
                "nfsim-execution",
                st,
                cpp_receipt["detail"],
                model=name,
                reference="nfsim",
                capabilities=["backend.nfsim"],
                evidence_kind=ek,
                receipt=str(cpp_nf_dir / "command.json"),
            )
        )
        return rows

    expected_times = np.linspace(0.0, 0.01, 3)
    ref_data, ref_cols = contracts._trajectory(oracle_gdat)
    subj_data, subj_cols = contracts._trajectory(cpp_nf_dir / cpp_gdat_name)
    if len(ref_cols) == 1 and len(subj_cols) == 1:
        ok = (
            ref_data.shape == subj_data.shape
            and len(ref_data) == len(expected_times)
            and bool(np.allclose(ref_data[:, 0], expected_times, rtol=0.0, atol=0.0))
            and bool(np.allclose(subj_data[:, 0], expected_times, rtol=0.0, atol=0.0))
        )
        detail = (
            "same-seed NFsim time grid matched pinned native NFsim (no declared observables)"
            if ok
            else "time-grid mismatch on zero-observable NFsim model"
        )
    else:
        checked = contracts.trajectory_contracts(
            oracle_gdat,
            cpp_nf_dir / cpp_gdat_name,
            kind="gdat",
            expected_times=expected_times,
            rtol=0.0,
            atol=0.0,
        )
        ok = all(r["status"] == "PASS" for r in checked)
        detail = (
            "same-seed NFsim trajectory matched pinned native NFsim"
            if ok
            else "; ".join(
                f"{r['check']}: {r.get('detail', '')}"
                for r in checked
                if r["status"] != "PASS"
            )
        )
    rows.append(
        _row(
            row_id,
            "nfsim-execution",
            "PASS" if ok else "FAIL",
            detail,
            model=name,
            reference="nfsim",
            capabilities=["export.bng_xml", "backend.nfsim"],
            evidence_kind="supported-execution" if ok else "observed-failure",
            receipt=str(cpp_nf_dir / "command.json"),
        )
    )
    return rows


def _run_refusal_case(
    name: str, source: Path, args, work: Path, env: dict
) -> list[dict]:
    parse_row = _run_parse(name, source, args, work, env)
    rows = [parse_row]
    if parse_row["status"] != "PASS":
        return rows
    act_dir = work / "authored-action"
    staged = _stage_unmodified_source(source, act_dir)
    receipt = campaign.run_command(
        [str(args.bng_cpp), str(staged)],
        act_dir,
        args.case_timeout,
        env=env,
    )
    status, kind = classify_command_status(receipt)
    rows.append(
        _row(
            f"{name}:authored-action",
            "authored-action",
            status,
            receipt["detail"],
            model=name,
            capabilities=["backend.nfsim", "nf.option.rnf"],
            evidence_kind=kind,
            receipt=str(act_dir / "command.json"),
        )
    )
    return rows


def _eval_post_action_amounts(source: Path, net_path: Path) -> dict[str, float]:
    """Compute analytic post-action initial species counts for set/addConcentration."""
    params = _parse_params(source)
    net_text = net_path.read_text(encoding="utf-8").splitlines()
    # Read initial species lines and parameter defs from generated .net
    section = None
    species_amounts: dict[str, float] = {}
    safe_env = {"__builtins__": {}, "pow": pow, "exp": math.exp, "sqrt": math.sqrt}
    for raw in net_text:
        line = raw.strip()
        if line.startswith("begin "):
            section = line[6:].strip().lower()
            continue
        if line.startswith("end "):
            section = None
            continue
        if section == "parameters" and line and not line.startswith("#"):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    params[parts[1]] = float(eval(parts[2], safe_env, params))
                except Exception:
                    pass
        elif section == "species" and line and not line.startswith("#"):
            parts = line.split(None, 2)
            if len(parts) == 3:
                try:
                    species_amounts[parts[1]] = float(eval(parts[2], safe_env, params))
                except Exception:
                    species_amounts[parts[1]] = 0.0
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        m = re.match(
            r"""^(setConcentration|addConcentration)\s*\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)""",
            line,
        )
        if m:
            act, sp, expr = m.groups()
            val = float(eval(expr, safe_env, params))
            if act == "setConcentration":
                species_amounts[sp] = val
            else:
                species_amounts[sp] = species_amounts.get(sp, 0.0) + val
    return species_amounts


def _patch_net_species(net_in: Path, net_out: Path, updates: dict[str, float]) -> None:
    lines = net_in.read_text(encoding="utf-8").splitlines()
    out = []
    in_species = False
    for raw in lines:
        s = raw.strip()
        if s == "begin species":
            in_species = True
            out.append(raw)
            continue
        if s == "end species":
            in_species = False
            out.append(raw)
            continue
        if in_species and s and not s.startswith("#"):
            parts = raw.split()
            if len(parts) >= 3 and parts[1] in updates:
                out.append(f"    {parts[0]} {parts[1]} {updates[parts[1]]:.15g}")
                continue
        out.append(raw)
    net_out.write_text("\n".join(out) + "\n", encoding="utf-8")


def _run_post_action_case(
    name: str,
    source: Path,
    args,
    directory: Path,
    references: dict,
    env: dict,
    default_model_fn,
) -> list[dict]:
    model_rows = default_model_fn(
        name, source, args, directory, references.get("bionetgen"), env
    )
    rows = list(model_rows)
    if not args.simulate:
        return rows
    non_agg = [r for r in model_rows if not r.get("aggregate")]
    work = directory / "models" / name
    bng2_ref = references.get("bionetgen")
    # Standard net-reload route passes directly against BNG2 + run_network.
    if args.net_reload:
        rows.extend(
            simulation_contract.run_simulation(
                name, work, bng2_ref, args, env, non_agg, route="net-reload"
            )
        )
    # For simulation-bngl, BNG2 drops setConcentration before addConcentration; feed
    # run_network the exact post-action initial concentrations from the authored actions.
    blockers = [r["id"] for r in non_agg if r["status"] != "PASS"]
    if blockers or not bng2_ref or not bng2_ref.get("network_binary_sha256"):
        rows.extend(
            simulation_contract.run_simulation(
                name, work, bng2_ref, args, env, non_agg, route="bngl"
            )
        )
        return rows

    campaign.verify_digest(
        Path(bng2_ref["network_binary"]), bng2_ref["network_binary_sha256"]
    )
    sim_root = work / "simulation-bngl"
    subj_dir = sim_root / "subject"
    ref_dir = sim_root / "reference"
    subj_dir.mkdir(parents=True, exist_ok=True)
    ref_dir.mkdir(parents=True, exist_ok=True)

    for item in (work / "input").iterdir():
        if item.is_dir():
            shutil.copytree(item, subj_dir / item.name)
        else:
            shutil.copy2(item, subj_dir / item.name)
    setup = (work / "input" / f"{name}.bngl").read_text(encoding="utf-8") + "\n"
    subj_proto = subj_dir / "protocol.bngl"
    subj_proto.write_text(
        simulation_contract.simulation_text(setup, args), encoding="utf-8"
    )
    subj_receipt = campaign.run_command(
        [str(args.bng_cpp), str(subj_proto)],
        subj_dir,
        args.case_timeout,
        env=env,
        required=["trajectory.cdat", "trajectory.gdat"],
    )
    updates = _eval_post_action_amounts(source, work / "reference" / f"{name}.net")
    _patch_net_species(
        work / "reference" / f"{name}.net", ref_dir / "post_action.net", updates
    )
    (ref_dir / "context.bngl").write_text(
        simulation_contract.net_reload_context(work / "input" / f"{name}.bngl"),
        encoding="utf-8",
    )
    ref_proto = ref_dir / "protocol.bngl"
    ref_proto.write_text(
        simulation_contract.simulation_text(
            'readFile({file=>"context.bngl"})\nreadFile({file=>"post_action.net"})\n',
            args,
            netfile="post_action.net",
        ),
        encoding="utf-8",
    )
    ref_receipt = campaign.run_command(
        [
            bng2_ref["interpreter"],
            bng2_ref["script"],
            "--outdir",
            str(ref_dir),
            str(ref_proto),
        ],
        ref_dir,
        args.case_timeout,
        env=env,
        required=["trajectory.cdat", "trajectory.gdat"],
    )
    common = dict(
        route="bngl",
        model=name,
        reference="bionetgen",
        question="bounded-deterministic-agreement",
        capabilities=["simulation.ode", "interface.cli-actions"],
    )
    for label, rec, d in (
        ("reference", ref_receipt, ref_dir),
        ("subject", subj_receipt, subj_dir),
    ):
        if rec["status"] != "PASS":
            st, ek = classify_command_status(rec)
            for kind in ("cdat", "gdat"):
                rows.append(
                    _row(
                        f"{name}:simulation-bngl:{kind}",
                        "simulation-preflight",
                        st,
                        rec["detail"],
                        evidence_kind=ek,
                        receipt=str(d / "command.json"),
                        **common,
                    )
                )
            return rows

    times = np.linspace(0, args.simulation_end, args.simulation_steps + 1)
    networks = [ref_dir / "post_action.net", work / "subject" / f"{name}.net"]
    for kind in ("cdat", "gdat"):
        paths = [ref_dir / f"trajectory.{kind}", subj_dir / f"trajectory.{kind}"]
        checked = contracts.trajectory_contracts(
            *paths, kind=kind, networks=networks, expected_times=times
        )
        ok = all(r["status"] == "PASS" for r in checked)
        rows.append(
            dict(
                id=f"{name}:simulation-bngl:{kind}",
                stage="simulation-summary",
                status="PASS" if ok else "FAIL",
                aggregate=True,
                detail=(
                    "matched run_network on post-action initial concentrations"
                    if ok
                    else "see child contracts"
                ),
                **common,
            )
        )
        for r in checked:
            rows.append(
                dict(
                    id=f"{name}:simulation-bngl:{r['check']}",
                    stage=(
                        "species-trajectory"
                        if kind == "cdat"
                        else "observable-trajectory"
                    ),
                    **r,
                    evidence=[str(p) for p in paths],
                    receipts=[
                        str(ref_dir / "command.json"),
                        str(subj_dir / "command.json"),
                    ],
                    **common,
                )
            )
    return rows


def run_case(
    name: str,
    source: Path,
    args,
    directory: Path,
    references: dict,
    env: dict,
    default_model_fn,
) -> list[dict]:
    """Execute one corpus case via its authored entry point and independent oracle."""
    work = directory / "models" / name
    if name in SBML_IMPORT_CASES:
        return _run_sbml_import_case(name, source, args, work, env)
    if name in SCIPY_ODE_CASES:
        return _run_scipy_ode_case(name, source, args, work, env)
    if name in AUTHORED_XML_BNG2_AND_NFSIM_CASES:
        return _run_nfsim_xml_case(
            name,
            source,
            args,
            work,
            references,
            env,
            compare_bng2_xml=True,
            compare_direct_nf=True,
        )
    if name in NFSIM_XML_CASES_DIRECT:
        return _run_nfsim_xml_case(
            name,
            source,
            args,
            work,
            references,
            env,
            compare_bng2_xml=False,
            compare_direct_nf=True,
        )
    if name in NFSIM_XML_ONLY_CASES:
        return _run_nfsim_xml_case(
            name,
            source,
            args,
            work,
            references,
            env,
            compare_bng2_xml=False,
            compare_direct_nf=False,
        )
    if name in REFUSAL_AUTHORED_CASES:
        return _run_refusal_case(name, source, args, work, env)
    if name in POST_ACTION_CONCENTRATION_CASES:
        return _run_post_action_case(
            name, source, args, directory, references, env, default_model_fn
        )

    # Standard network + optional ODE + authored action checks
    model_rows = default_model_fn(
        name, source, args, directory, references.get("bionetgen"), env
    )
    rows = list(model_rows)
    if args.simulate and name not in AUTHORED_XML_AND_NETWORK_CASES:
        non_agg = [r for r in model_rows if not r.get("aggregate")]
        for route in (["bngl", "net-reload"] if args.net_reload else ["bngl"]):
            rows.extend(
                simulation_contract.run_simulation(
                    name,
                    work,
                    references.get("bionetgen"),
                    args,
                    env,
                    non_agg,
                    route=route,
                )
            )
    if name in AUTHORED_XML_AND_NETWORK_CASES or name in ACTION_AND_NETWORK_CASES:
        rows.append(
            _check_authored_action(
                name, source, args, work, env, references.get("bionetgen")
            )
        )
    return rows
