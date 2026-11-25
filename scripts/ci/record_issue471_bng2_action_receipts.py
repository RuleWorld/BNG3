#!/usr/bin/env python3
"""Emit schema-v2 #471/#180 differential receipts for BNG2 action and option rows.

Runs pinned ``BNG2.pl`` (external oracle) and ``bng_cpp`` (downstream consumer)
on self-contained BNGL probes covering verified ``action.*`` and ``option.*``
matrix rows (``simulate*``, ``setParameter``, ``setConcentration``,
``addConcentration``, ``saveConcentrations``, ``resetConcentrations``,
``generate_network``, ``writeNetwork``, ``writeNET``, ``writeXML``,
``parameter_scan*``, and ``setOption``), emitting byte/numeric-verified
schema-v2 receipts ONLY where oracle and consumer agree.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = ROOT / "tests/validation/release/cases/issue-471"
for entry in (str(ROOT), str(CASE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import issue471_checks as checks  # noqa: E402
from scripts.ci.record_issue471_bng2_receipts import (  # noqa: E402
    _build_platform,
    _git_dirty,
    _git_head,
    _sha256_bytes,
    _verify_pinned_bng2,
    _version_line,
)


@dataclass(frozen=True)
class ActionProbeSpec:
    """Single pinned-BNG2 vs bng_cpp action/option probe."""

    row_id: str
    comparator: str
    output_file: str
    bngl_text: str


BASE_MODEL = (
    "begin model\n"
    "begin parameters\n"
    "  kf 0.5\n"
    "  kr 0.1\n"
    "  A0 100\n"
    "  B0 50\n"
    "end parameters\n"
    "begin molecule types\n"
    "  A(b)\n"
    "  B(a)\n"
    "end molecule types\n"
    "begin seed species\n"
    "  A(b) A0\n"
    "  B(a) B0\n"
    "end seed species\n"
    "begin observables\n"
    "  Molecules A_free A(b)\n"
    "  Molecules AB A(b!1).B(a!1)\n"
    "end observables\n"
    "begin functions\n"
    "  ratio_ab() = AB / (A_free + 1)\n"
    "end functions\n"
    "begin reaction rules\n"
    "  R1: A(b) + B(a) <-> A(b!1).B(a!1) kf, kr\n"
    "end reaction rules\n"
    "end model\n"
)

SIMPLE_XML_MODEL = (
    "begin model\n"
    "begin parameters\n"
    "  k 0.5\n"
    "end parameters\n"
    "begin molecule types\n"
    "  A()\n"
    "end molecule types\n"
    "begin seed species\n"
    "  A() 10\n"
    "end seed species\n"
    "begin observables\n"
    "  Molecules A_obs A()\n"
    "end observables\n"
    "begin reaction rules\n"
    "  R1: A() -> 0 k\n"
    "end reaction rules\n"
    "end model\n"
)

_GDAT = "release-oracle-gdat-numeric-v1"
_NET = "release-oracle-net-canonical-v1"
_XML = "release-oracle-bngl-xml-v1"

ACTION_PROBES: tuple[ActionProbeSpec, ...] = (
    # simulate / simulate_ode + options
    ActionProbeSpec(
        "action.simulate_ode",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + "generate_network({overwrite=>1})\nsimulate_ode({t_end=>2,n_steps=>4})\n",
    ),
    ActionProbeSpec(
        "action.simulate_ode.method",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + "generate_network({overwrite=>1})\nsimulate_ode({t_end=>2,n_steps=>4})\n",
    ),
    ActionProbeSpec(
        "action.simulate.method",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    ActionProbeSpec(
        "action.simulate.t_end",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>1.5,n_steps=>3})\n',
    ),
    ActionProbeSpec(
        "action.simulate.t_start",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_start=>0.5,t_end=>2.5,n_steps=>4})\n',
    ),
    ActionProbeSpec(
        "action.simulate.n_steps",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>8})\n',
    ),
    ActionProbeSpec(
        "action.simulate.n_output_steps",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_output_steps=>5})\n',
    ),
    ActionProbeSpec(
        "action.simulate.atol",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,atol=>1e-9})\n',
    ),
    ActionProbeSpec(
        "action.simulate.rtol",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,rtol=>1e-9})\n',
    ),
    ActionProbeSpec(
        "action.simulate.sparse",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,sparse=>1})\n',
    ),
    ActionProbeSpec(
        "action.simulate.prefix",
        _GDAT,
        "custom_pref.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,prefix=>"custom_pref"})\n',
    ),
    ActionProbeSpec(
        "action.simulate.suffix",
        _GDAT,
        "probe_mysuf.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,suffix=>"mysuf"})\n',
    ),
    ActionProbeSpec(
        "action.simulate.sample_times",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",sample_times=>[0,0.5,1.0,2.0]})\n',
    ),
    ActionProbeSpec(
        "action.simulate.print_functions",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,print_functions=>1})\n',
    ),
    ActionProbeSpec(
        "action.simulate.print_end",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,print_end=>1})\n',
    ),
    ActionProbeSpec(
        "action.simulate.print_CDAT",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,print_CDAT=>0})\n',
    ),
    ActionProbeSpec(
        "action.simulate.steady_state",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>50,n_steps=>5,steady_state=>1})\n',
    ),
    ActionProbeSpec(
        "action.simulate.stop_if",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>10,n_steps=>20,stop_if=>"AB>45"})\n',
    ),
    ActionProbeSpec(
        "action.simulate.print_on_stop",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>10,n_steps=>20,stop_if=>"AB>45",print_on_stop=>1})\n',
    ),
    ActionProbeSpec(
        "action.simulate.save_progress",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,save_progress=>1})\n',
    ),
    ActionProbeSpec(
        "action.simulate.print_n_species_active",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,print_n_species_active=>1})\n',
    ),
    ActionProbeSpec(
        "action.simulate.check_product_scale",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,check_product_scale=>1})\n',
    ),
    ActionProbeSpec(
        "action.simulate.verbose",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,verbose=>1})\n',
    ),
    ActionProbeSpec(
        "action.simulate.netfile",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",netfile=>"probe.net",t_end=>2,n_steps=>4})\n',
    ),
    ActionProbeSpec(
        "action.simulate.expand",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsimulate({method=>"ode",expand=>"lazy",t_end=>2,n_steps=>4})\n',
    ),
    # Parameter & concentration mutation actions
    ActionProbeSpec(
        "action.setParameter",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsetParameter("kf",1.0)\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    ActionProbeSpec(
        "action.setConcentration",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsetConcentration("A(b)",200)\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    ActionProbeSpec(
        "action.addConcentration",
        _GDAT,
        "probe.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\naddConcentration("A(b)",50)\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    ActionProbeSpec(
        "action.saveConcentrations",
        _GDAT,
        "probe_after.gdat",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nsaveConcentrations("init")\n'
        + 'simulate({method=>"ode",t_end=>2,n_steps=>2})\nresetConcentrations("init")\n'
        + 'simulate({method=>"ode",t_end=>2,n_steps=>4,suffix=>"after"})\n',
    ),
    ActionProbeSpec(
        "action.resetConcentrations",
        _GDAT,
        "probe_after.gdat",
        BASE_MODEL
        + "generate_network({overwrite=>1})\nsaveConcentrations()\n"
        + 'simulate({method=>"ode",t_end=>2,n_steps=>2})\nresetConcentrations()\n'
        + 'simulate({method=>"ode",t_end=>2,n_steps=>4,suffix=>"after"})\n',
    ),
    # Network generation & export
    ActionProbeSpec(
        "action.generate_network",
        _NET,
        "probe.net",
        BASE_MODEL + "generate_network({overwrite=>1})\n",
    ),
    ActionProbeSpec(
        "action.writeNetwork",
        _NET,
        "probe_out.net",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nwriteNetwork({suffix=>"out"})\n',
    ),
    ActionProbeSpec(
        "action.writeNET",
        _NET,
        "probe_out.net",
        BASE_MODEL + 'generate_network({overwrite=>1})\nwriteNET({suffix=>"out"})\n',
    ),
    ActionProbeSpec(
        "action.writeXML",
        _XML,
        "probe.xml",
        SIMPLE_XML_MODEL + "writeXML()\n",
    ),
    # parameter_scan + options
    ActionProbeSpec(
        "action.parameter_scan",
        _GDAT,
        "probe_kf.scan",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nparameter_scan({parameter=>"kf",par_min=>0.2,par_max=>1.0,n_scan_pts=>5,method=>"ode",t_end=>1,n_steps=>2})\n',
    ),
    ActionProbeSpec(
        "action.parameter_scan.parameter",
        _GDAT,
        "probe_kf.scan",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nparameter_scan({parameter=>"kf",par_min=>0.2,par_max=>1.0,n_scan_pts=>5,method=>"ode",t_end=>1,n_steps=>2})\n',
    ),
    ActionProbeSpec(
        "action.parameter_scan.par_min",
        _GDAT,
        "probe_kf.scan",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nparameter_scan({parameter=>"kf",par_min=>0.1,par_max=>1.0,n_scan_pts=>3,method=>"ode",t_end=>1,n_steps=>2})\n',
    ),
    ActionProbeSpec(
        "action.parameter_scan.par_max",
        _GDAT,
        "probe_kf.scan",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nparameter_scan({parameter=>"kf",par_min=>0.2,par_max=>2.0,n_scan_pts=>3,method=>"ode",t_end=>1,n_steps=>2})\n',
    ),
    ActionProbeSpec(
        "action.parameter_scan.n_scan_pts",
        _GDAT,
        "probe_kf.scan",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nparameter_scan({parameter=>"kf",par_min=>0.2,par_max=>1.0,n_scan_pts=>4,method=>"ode",t_end=>1,n_steps=>2})\n',
    ),
    ActionProbeSpec(
        "action.parameter_scan.method",
        _GDAT,
        "probe_kf.scan",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nparameter_scan({parameter=>"kf",par_min=>0.2,par_max=>1.0,n_scan_pts=>3,method=>"ode",t_end=>1,n_steps=>2})\n',
    ),
    ActionProbeSpec(
        "action.parameter_scan.par_scan_vals",
        _GDAT,
        "probe_kf.scan",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nparameter_scan({parameter=>"kf",par_scan_vals=>[0.1,0.5,1.0],method=>"ode",t_end=>1,n_steps=>2})\n',
    ),
    ActionProbeSpec(
        "action.parameter_scan.log_scale",
        _GDAT,
        "probe_kf.scan",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nparameter_scan({parameter=>"kf",par_min=>0.1,par_max=>10.0,n_scan_pts=>3,log_scale=>1,method=>"ode",t_end=>1,n_steps=>2})\n',
    ),
    ActionProbeSpec(
        "action.parameter_scan.suffix",
        _GDAT,
        "probe_sc.scan",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nparameter_scan({parameter=>"kf",par_min=>0.2,par_max=>1.0,n_scan_pts=>3,method=>"ode",t_end=>1,n_steps=>2,suffix=>"sc"})\n',
    ),
    ActionProbeSpec(
        "action.parameter_scan.prefix",
        _GDAT,
        "myscan_kf.scan",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nparameter_scan({parameter=>"kf",par_min=>0.2,par_max=>1.0,n_scan_pts=>3,method=>"ode",t_end=>1,n_steps=>2,prefix=>"myscan"})\n',
    ),
    ActionProbeSpec(
        "action.parameter_scan.reset_conc",
        _GDAT,
        "probe_kf.scan",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nparameter_scan({parameter=>"kf",par_min=>0.2,par_max=>1.0,n_scan_pts=>3,method=>"ode",t_end=>1,n_steps=>2,reset_conc=>1})\n',
    ),
    ActionProbeSpec(
        "action.parameter_scan.get_final_state",
        _GDAT,
        "probe_kf.scan",
        BASE_MODEL
        + 'generate_network({overwrite=>1})\nparameter_scan({parameter=>"kf",par_min=>0.2,par_max=>1.0,n_scan_pts=>3,method=>"ode",t_end=>1,n_steps=>2,get_final_state=>1})\n',
    ),
    # setOption options
    ActionProbeSpec(
        "option.SpeciesLabel",
        _NET,
        "probe.net",
        'setOption("SpeciesLabel","HNauty")\n'
        + BASE_MODEL
        + "generate_network({overwrite=>1})\n",
    ),
    ActionProbeSpec(
        "option.SpeciesLabel.Auto",
        _NET,
        "probe.net",
        'setOption("SpeciesLabel","Auto")\n'
        + BASE_MODEL
        + "generate_network({overwrite=>1})\n",
    ),
    ActionProbeSpec(
        "option.SpeciesLabel.HNauty",
        _NET,
        "probe.net",
        'setOption("SpeciesLabel","HNauty")\n'
        + BASE_MODEL
        + "generate_network({overwrite=>1})\n",
    ),
    ActionProbeSpec(
        "option.SpeciesLabel.Quasi",
        _NET,
        "probe.net",
        'setOption("SpeciesLabel","Quasi")\n'
        + BASE_MODEL
        + "generate_network({overwrite=>1})\n",
    ),
    ActionProbeSpec(
        "option.NumberPerQuantityUnit",
        _NET,
        "probe.net",
        'setOption("NumberPerQuantityUnit",6.022e23)\n'
        + BASE_MODEL
        + "generate_network({overwrite=>1})\n",
    ),
    ActionProbeSpec(
        "option.MoleculesObservables",
        _NET,
        "probe.net",
        'setOption("MoleculesObservables","CountAll")\n'
        + BASE_MODEL
        + "generate_network({overwrite=>1})\n",
    ),
    ActionProbeSpec(
        "option.MoleculesObservables.CountAll",
        _NET,
        "probe.net",
        'setOption("MoleculesObservables","CountAll")\n'
        + BASE_MODEL
        + "generate_network({overwrite=>1})\n",
    ),
    ActionProbeSpec(
        "option.MoleculesObservables.CountUnique",
        _NET,
        "probe.net",
        'setOption("MoleculesObservables","CountUnique")\n'
        + BASE_MODEL
        + "generate_network({overwrite=>1})\n",
    ),
    ActionProbeSpec(
        "option.SpeciesObservables",
        _NET,
        "probe.net",
        'setOption("SpeciesObservables","CountAll")\n'
        + BASE_MODEL
        + "generate_network({overwrite=>1})\n",
    ),
    ActionProbeSpec(
        "option.SpeciesObservables.CountAll",
        _NET,
        "probe.net",
        'setOption("SpeciesObservables","CountAll")\n'
        + BASE_MODEL
        + "generate_network({overwrite=>1})\n",
    ),
    ActionProbeSpec(
        "option.SpeciesObservables.CountUnique",
        _NET,
        "probe.net",
        'setOption("SpeciesObservables","CountUnique")\n'
        + BASE_MODEL
        + "generate_network({overwrite=>1})\n",
    ),
)


def _compare(
    comparator: str, oracle_bytes: bytes, consumer_bytes: bytes
) -> tuple[bool, str]:
    if comparator == _GDAT:
        return checks._compare_gdat_bytes(oracle_bytes, consumer_bytes)
    if comparator == _NET:
        return checks._compare_net_bytes(oracle_bytes, consumer_bytes)
    if comparator == _XML:
        return checks._compare_bngl_xml_bytes(oracle_bytes, consumer_bytes)
    return False, f"unsupported comparator {comparator}"


def build_bng2_action_receipts(
    *,
    root: Path,
    revision: str,
    bng2_root: Path,
    bng_cpp: Path,
    receipts_dir: Path,
    artifacts_dir: Path,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    head = _git_head(root)
    dirty = _git_dirty(root)
    if head != revision or (dirty and not allow_dirty):
        raise ValueError(
            "issue #471 BNG2 action receipts require the requested clean revision"
        )
    matrix = json.loads(
        (root / "provenance/capability-matrix.yml").read_text(encoding="utf-8")
    )
    matrix_ids = {
        str(entry["id"])
        for entry in matrix.get("rows", [])
        if str(entry.get("upstream", "")).startswith("bionetgen:")
    }
    pinned_rev, script_sha256, run_network_sha256 = _verify_pinned_bng2(root, bng2_root)
    build_platform = _build_platform()
    bng2_version = _version_line(
        [
            "perl",
            "-e",
            'open F,$ARGV[0]; while(<F>){if(/BioNetGen\\s+([0-9.]+)/){print "$1\\n";exit}}',
            str(bng2_root / "bng2" / "BNG2.pl"),
        ],
        "2.9.3-pinned",
    )
    bng_cpp_version = _version_line([str(bng_cpp), "--version"], "bng_cpp")
    bng2_pl = (bng2_root / "bng2" / "BNG2.pl").resolve()
    bng2_env = {**dict(os.environ), "BNGPATH": str((bng2_root / "bng2").resolve())}

    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    emitted: list[str] = []
    skipped: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="bng3-471-bng2-actions-") as td:
        work_root = Path(td)
        for spec in ACTION_PROBES:
            if spec.row_id not in matrix_ids:
                continue
            inp_bytes = spec.bngl_text.encode("utf-8")
            ref_dir = work_root / spec.row_id / "oracle"
            sub_dir = work_root / spec.row_id / "consumer"
            ref_dir.mkdir(parents=True, exist_ok=True)
            sub_dir.mkdir(parents=True, exist_ok=True)
            ref_bngl = ref_dir / "probe.bngl"
            sub_bngl = sub_dir / "probe.bngl"
            ref_bngl.write_bytes(inp_bytes)
            sub_bngl.write_bytes(inp_bytes)

            ref_cmd = ["perl", str(bng2_pl), str(ref_bngl)]
            sub_cmd = [str(bng_cpp), str(sub_bngl)]
            ref_proc = subprocess.run(
                ref_cmd,
                cwd=ref_dir,
                env=bng2_env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            sub_proc = subprocess.run(
                sub_cmd,
                cwd=sub_dir,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            ref_out = ref_dir / spec.output_file
            sub_out = sub_dir / spec.output_file
            if (
                ref_proc.returncode != 0
                or sub_proc.returncode != 0
                or not ref_out.is_file()
                or not sub_out.is_file()
            ):
                skipped.append(
                    {
                        "id": spec.row_id,
                        "reason": "execution_or_output_missing",
                        "oracle_rc": ref_proc.returncode,
                        "consumer_rc": sub_proc.returncode,
                    }
                )
                continue

            o_bytes = ref_out.read_bytes()
            c_bytes = sub_out.read_bytes()
            ok, detail = _compare(spec.comparator, o_bytes, c_bytes)
            if not ok:
                skipped.append(
                    {
                        "id": spec.row_id,
                        "reason": "comparator_mismatch",
                        "detail": detail,
                    }
                )
                continue

            ext = Path(spec.output_file).suffix or ".out"
            row_art = artifacts_dir / spec.row_id
            row_art.mkdir(parents=True, exist_ok=True)
            producer_rel = f"{spec.row_id}/producer.bngl"
            oracle_rel = f"{spec.row_id}/oracle{ext}"
            consumer_rel = f"{spec.row_id}/consumer{ext}"
            (artifacts_dir / producer_rel).write_bytes(inp_bytes)
            (artifacts_dir / oracle_rel).write_bytes(o_bytes)
            (artifacts_dir / consumer_rel).write_bytes(c_bytes)

            producer_sha = _sha256_bytes(inp_bytes)
            oracle_sha = _sha256_bytes(o_bytes)
            consumer_sha = _sha256_bytes(c_bytes)
            ref_cmd_str = " ".join(ref_cmd)
            sub_cmd_str = " ".join(sub_cmd)

            receipt = {
                "schema_version": 2,
                "kind": "release-oracle-consumer-receipt",
                "capability_id": spec.row_id,
                "check_id": f"release-capability[{spec.row_id}]",
                "comparator": spec.comparator,
                "source_revision": revision,
                "product_revision": revision,
                "oracle": {
                    "name": f"Pinned BNG2.pl ({spec.row_id})",
                    "source_id": "bng2",
                    "revision": pinned_rev,
                    "build_platform": build_platform,
                    "source_clean": True,
                    "path": oracle_rel,
                    "artifact_sha256": oracle_sha,
                    "script_sha256": script_sha256,
                    "executable_sha256": run_network_sha256,
                    "command": ref_cmd_str,
                    "expected_origin": "external-source",
                    "execution": {
                        "executable": "BNG2.pl",
                        "version": bng2_version,
                        "command": ref_cmd_str,
                        "exit_code": ref_proc.returncode,
                    },
                },
                "producer": {
                    "path": producer_rel,
                    "output_sha256": producer_sha,
                },
                "consumer": {
                    "path": consumer_rel,
                    "output_sha256": consumer_sha,
                    "consumed_producer_sha256": producer_sha,
                    "execution": {
                        "executable": "bng_cpp",
                        "version": bng_cpp_version,
                        "command": sub_cmd_str,
                        "exit_code": sub_proc.returncode,
                    },
                },
            }
            (receipts_dir / f"{spec.row_id}.json").write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            emitted.append(spec.row_id)

    return {
        "schema_version": 1,
        "source_revision": revision,
        "oracle_revision": pinned_rev,
        "emitted_count": len(emitted),
        "skipped_count": len(skipped),
        "emitted_rows": emitted,
        "skipped_rows": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--bng2-root", type=Path, required=True)
    parser.add_argument("--bng-cpp", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    summary = build_bng2_action_receipts(
        root=args.root.resolve(),
        revision=args.revision,
        bng2_root=args.bng2_root.resolve(),
        bng_cpp=args.bng_cpp.resolve(),
        receipts_dir=args.receipts_dir.resolve(),
        artifacts_dir=args.artifacts_dir.resolve(),
        allow_dirty=args.allow_dirty,
    )
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        f"Emitted {summary['emitted_count']} BNG2 action/option #471/#180 receipts "
        f"({summary['skipped_count']} skipped) for {summary['source_revision'][:8]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
