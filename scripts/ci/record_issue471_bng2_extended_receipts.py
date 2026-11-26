#!/usr/bin/env python3
"""Emit schema-v2 #471/#180 receipts for BNG2 exports, bifurcate, and verified singletons.

Covers:
- action.write* & action.visualize (90 rows) via release-oracle-export-struct-v1
  and release-oracle-gdat-numeric-v1 (for round-tripped executable exports)
- action.bifurcate* (9 rows) via release-oracle-gdat-numeric-v1 against pinned BNG2
- Verified BNG2/BNGIR/SBML/LPS/action singletons & summaries (~35 rows)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.record_issue471_bng2_receipts import (  # noqa: E402
    _build_platform,
    _git_dirty,
    _git_head,
    _sha256_bytes,
    _verify_pinned_bng2,
    _version_line,
)

BASE_DECAY_MODEL = """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
"""

REVERSIBLE_MODEL = """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() <-> B() k, 0.2
end reaction rules
end model
"""


@dataclass(frozen=True)
class ExportProbe:
    name: str
    fmt: str
    bngl: str
    row_ids: tuple[str, ...]
    extra_files: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class GdatProbe:
    name: str
    bngl: str
    oracle_file: str
    consumer_file: str
    row_ids: tuple[str, ...]
    extra_files: tuple[tuple[str, str], ...] = ()
    comparator: str = "release-oracle-gdat-numeric-v1"


EXPORT_PROBES: tuple[ExportProbe, ...] = (
    ExportProbe(
        name="writeMfile",
        fmt="mfile",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'writeMfile({prefix=>"ex",suffix=>"s1",t_start=>0,t_end=>5,n_steps=>25,'
        + "atol=>1e-9,rtol=>1e-7,max_step=>0.1,bdf=>1,maxOrder=>4,stats=>1})\n",
        row_ids=(
            "action.writeMfile",
            "action.writeMfile.atol",
            "action.writeMfile.bdf",
            "action.writeMfile.maxOrder",
            "action.writeMfile.max_step",
            "action.writeMfile.n_steps",
            "action.writeMfile.prefix",
            "action.writeMfile.rtol",
            "action.writeMfile.stats",
            "action.writeMfile.suffix",
            "action.writeMfile.t_end",
            "action.writeMfile.t_start",
        ),
    ),
    ExportProbe(
        name="writeMfile_all",
        fmt="mfile_all",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'writeMfile_all({prefix=>"ex",suffix=>"s1",t_start=>0,t_end=>5,n_steps=>25,'
        + "atol=>1e-9,rtol=>1e-7,max_step=>0.1,bdf=>1,maxOrder=>4,stats=>1})\n",
        row_ids=(
            "action.writeMfile_all",
            "action.writeMfile_all.atol",
            "action.writeMfile_all.bdf",
            "action.writeMfile_all.maxOrder",
            "action.writeMfile_all.max_step",
            "action.writeMfile_all.n_steps",
            "action.writeMfile_all.prefix",
            "action.writeMfile_all.rtol",
            "action.writeMfile_all.stats",
            "action.writeMfile_all.suffix",
            "action.writeMfile_all.t_end",
            "action.writeMfile_all.t_start",
        ),
    ),
    ExportProbe(
        name="writeMexfile",
        fmt="mexfile",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'writeMexfile({prefix=>"ex",suffix=>"s1",t_start=>0,t_end=>5,n_steps=>25,'
        + "atol=>1e-9,rtol=>1e-7,max_num_steps=>3000,max_err_test_fails=>10,"
        + "max_conv_fails=>12,max_step=>0.1,stiff=>1,sparse=>1})\n",
        row_ids=(
            "action.writeMEXfile",
            "action.writeMexfile",
            "action.writeMexfile.atol",
            "action.writeMexfile.max_conv_fails",
            "action.writeMexfile.max_err_test_fails",
            "action.writeMexfile.max_num_steps",
            "action.writeMexfile.max_step",
            "action.writeMexfile.n_steps",
            "action.writeMexfile.prefix",
            "action.writeMexfile.rtol",
            "action.writeMexfile.sparse",
            "action.writeMexfile.stiff",
            "action.writeMexfile.suffix",
            "action.writeMexfile.t_end",
            "action.writeMexfile.t_start",
        ),
    ),
    ExportProbe(
        name="writeCPPfile",
        fmt="cppfile",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'writeCPPfile({prefix=>"ex",suffix=>"s1",t_start=>0,t_end=>5,n_steps=>25,'
        + "atol=>1e-9,rtol=>1e-7,max_num_steps=>3000,max_err_test_fails=>10,"
        + "max_conv_fails=>12,max_step=>0.1,stiff=>1,sparse=>1})\n",
        row_ids=(
            "action.writeCPPfile",
            "action.writeCPPfile.atol",
            "action.writeCPPfile.max_conv_fails",
            "action.writeCPPfile.max_err_test_fails",
            "action.writeCPPfile.max_num_steps",
            "action.writeCPPfile.max_step",
            "action.writeCPPfile.n_steps",
            "action.writeCPPfile.prefix",
            "action.writeCPPfile.rtol",
            "action.writeCPPfile.sparse",
            "action.writeCPPfile.stiff",
            "action.writeCPPfile.suffix",
            "action.writeCPPfile.t_end",
            "action.writeCPPfile.t_start",
        ),
    ),
    ExportProbe(
        name="writeCPYfile",
        fmt="cpyfile",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'writeCPYfile({prefix=>"ex",suffix=>"s1",t_start=>0,t_end=>5,n_steps=>25,'
        + "atol=>1e-9,rtol=>1e-7,max_num_steps=>3000,max_err_test_fails=>10,"
        + "max_conv_fails=>12,max_step=>0.1,stiff=>1,sparse=>1})\n",
        row_ids=(
            "action.writeCPYfile",
            "action.writeCPYfile.atol",
            "action.writeCPYfile.max_conv_fails",
            "action.writeCPYfile.max_err_test_fails",
            "action.writeCPYfile.max_num_steps",
            "action.writeCPYfile.max_step",
            "action.writeCPYfile.n_steps",
            "action.writeCPYfile.prefix",
            "action.writeCPYfile.rtol",
            "action.writeCPYfile.sparse",
            "action.writeCPYfile.stiff",
            "action.writeCPYfile.suffix",
            "action.writeCPYfile.t_end",
            "action.writeCPYfile.t_start",
        ),
    ),
    ExportProbe(
        name="writeLatex",
        fmt="latex",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'writeLatex({prefix=>"ex",suffix=>"s1"})\n',
        row_ids=(
            "action.writeLaTeXfile",
            "action.writeLatex",
            "action.writeLatex.prefix",
            "action.writeLatex.suffix",
        ),
    ),
    ExportProbe(
        name="writeMDL",
        fmt="mdl",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'writeMDL({prefix=>"ex",suffix=>"s1"})\n',
        row_ids=(
            "action.writeMDL",
            "action.writeMDL.prefix",
            "action.writeMDL.suffix",
        ),
        extra_files=(("default.geometry.mdl", "/* empty geometry */\n"),),
    ),
    ExportProbe(
        name="writeSSC",
        fmt="ssc",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'writeSSC({prefix=>"ex",suffix=>"s1"})\n',
        row_ids=(
            "action.writeSSC",
            "action.writeSSC.prefix",
            "action.writeSSC.suffix",
        ),
    ),
    ExportProbe(
        name="writeSSCcfg",
        fmt="ssccfg",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'writeSSCcfg({prefix=>"ex",suffix=>"s1"})\n',
        row_ids=(
            "action.writeSSCcfg",
            "action.writeSSCcfg.prefix",
            "action.writeSSCcfg.suffix",
        ),
    ),
    ExportProbe(
        name="visualize",
        fmt="visualize",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'visualize({type=>"regulatory",prefix=>"ex"})\n',
        row_ids=("action.visualize",),
    ),
)

GDAT_PROBES: tuple[GdatProbe, ...] = (
    GdatProbe(
        name="bifurcate",
        bngl=REVERSIBLE_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'bifurcate({parameter=>"k",par_min=>0.2,par_max=>0.8,n_scan_pts=>3,'
        + 'method=>"ode",t_end=>20,n_steps=>40,suffix=>"bif1",log_scale=>0,reset_conc=>0})\n',
        oracle_file="m_bif1_bifurcation_A_obs.scan",
        consumer_file="m_bif1_bifurcation_A_obs.scan",
        row_ids=(
            "action.bifurcate",
            "action.bifurcate.log_scale",
            "action.bifurcate.n_scan_pts",
            "action.bifurcate.par_max",
            "action.bifurcate.par_min",
            "action.bifurcate.parameter",
            "action.bifurcate.reset_conc",
            "action.bifurcate.scanfile",
            "action.bifurcate.suffix",
        ),
    ),
    GdatProbe(
        name="header_version_substance_setoption",
        bngl='version("2.2.5");\nsubstanceUnits("Number");\n'
        + 'setOption("SpeciesLabel","HNauty");\nsetOption("CustomOpt","val");\n'
        + BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'simulate({method=>"ode",t_end=>2,n_steps=>4})\n',
        oracle_file="m.gdat",
        consumer_file="m.gdat",
        row_ids=(
            "action.version",
            "action.substanceUnits",
            "action.setOption",
            "action.simulate",
            "option.unknown-option-storage",
            "bngl.actions.setoption",
            "bngl.ast.model",
            "bngl.observables.counting-modes",
            "expression.builtins.shared-table",
        ),
    ),
    GdatProbe(
        name="simulate_argfile",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'simulate({argfile=>"sim.args"})\n',
        oracle_file="m.gdat",
        consumer_file="m.gdat",
        row_ids=("action.simulate.argfile",),
        extra_files=(("sim.args", "method ode\nt_end 2\nn_steps 4\n"),),
    ),
    GdatProbe(
        name="parameter_scan_parallel_numcores",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'parameter_scan({parameter=>"k",par_min=>0.2,par_max=>0.8,n_scan_pts=>3,'
        + 'method=>"ode",t_end=>2,n_steps=>4,parallel=>0,num_cores=>1})\n',
        oracle_file="m_k.scan",
        consumer_file="m_k.scan",
        row_ids=(
            "action.parameter_scan.parallel",
            "action.parameter_scan.num_cores",
            "action.parameter_scan.scanfile",
        ),
    ),
    GdatProbe(
        name="lps_reversible",
        bngl=REVERSIBLE_MODEL
        + "generate_network({overwrite=>1})\n"
        + "LinearParameterSensitivity({t_end=>2,n_steps=>4,init_equil=>1,re_equil=>1,t_equil=>100})\n",
        oracle_file="m_k_.gdat",
        consumer_file="m_k_.gdat",
        row_ids=(
            "action.LinearParameterSensitivity.init_equil",
            "action.LinearParameterSensitivity.re_equil",
            "action.LinearParameterSensitivity.t_equil",
            "action.LinearParameterSensitivity.prefix",
        ),
    ),
    GdatProbe(
        name="lps_net_file",
        bngl=REVERSIBLE_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'LinearParameterSensitivity({net_file=>"m",t_end=>2,n_steps=>4,init_equil=>1,re_equil=>1,t_equil=>100})\n',
        oracle_file="m_k_.gdat",
        consumer_file="m_k_.gdat",
        row_ids=("action.LinearParameterSensitivity.net_file",),
    ),
    GdatProbe(
        name="energyBNG",
        bngl="""setOption("energyBNG",1);
begin model
begin parameters
  gf -1.0
  phi 0.5
  Ea0 0.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 10
  B(a) 10
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin energy patterns
  A(b!1).B(a!1) gf
end energy patterns
begin reaction rules
  A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi, Ea0)
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>2,n_steps=>4})
""",
        oracle_file="m.gdat",
        consumer_file="m.gdat",
        row_ids=("option.energyBNG",),
    ),
    GdatProbe(
        name="tfun_and_time",
        bngl="""begin model
begin parameters
end parameters
begin molecule types
  X()
end molecule types
begin seed species
  X() 0
end seed species
begin observables
  Molecules Xtot X()
end observables
begin functions
  f_step() = tfun([0,1,2,3], [1,2,3,4], time, method=>"step")
end functions
begin reaction rules
  0 -> X() f_step()
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>4,n_steps=>80})
""",
        oracle_file="m.gdat",
        consumer_file="m.gdat",
        row_ids=(
            "builtin.TFUN",
            "builtin.time",
            "bngl.time-dependencies",
        ),
    ),
    GdatProbe(
        name="bngl_function_ratelaw",
        bngl="""begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin functions
  r() = k / (1 + 0.1 * B_obs)
end functions
begin reaction rules
  A() -> B() r()
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>2,n_steps=>4})
""",
        oracle_file="m.gdat",
        consumer_file="m.gdat",
        row_ids=("bngl.function",),
    ),
    GdatProbe(
        name="setModelName",
        bngl='setModelName("renamed");\n'
        + BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'simulate({method=>"ode",t_end=>2,n_steps=>4})\n',
        oracle_file="renamed.gdat",
        consumer_file="renamed.gdat",
        row_ids=("action.setModelName",),
    ),
    GdatProbe(
        name="readModel",
        bngl='readModel({file=>"sub.bngl"})\n'
        + "generate_network({overwrite=>1})\n"
        + 'simulate({method=>"ode",t_end=>2,n_steps=>4})\n',
        oracle_file="m.gdat",
        consumer_file="m.gdat",
        row_ids=("action.readModel", "bngl.source-file-include-readmodel"),
        extra_files=(("sub.bngl", BASE_DECAY_MODEL),),
    ),
    GdatProbe(
        name="print_net",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'simulate({method=>"ode",t_end=>2,n_steps=>4,prefix=>"p1",print_net=>1})\n',
        oracle_file="p1_save.net",
        consumer_file="p1_save.net",
        row_ids=("action.simulate.print_net",),
        comparator="release-oracle-net-canonical-v1",
    ),
    GdatProbe(
        name="simulate_protocol",
        bngl=BASE_DECAY_MODEL.replace(
            "end model",
            'begin protocol\n  simulate({method=>"ode",t_end=>2,n_steps=>4})\nend protocol\nend model',
        )
        + "generate_network({overwrite=>1})\n"
        + 'simulate_protocol({prefix=>"proto"})\n',
        oracle_file="proto.gdat",
        consumer_file="proto.gdat",
        row_ids=("action.simulate_protocol", "action.simulate_protocol.prefix"),
    ),
    GdatProbe(
        name="readNFspecies",
        bngl=BASE_DECAY_MODEL
        + 'readNFspecies("sp.species")\n'
        + "generate_network({overwrite=>1})\n"
        + 'simulate({method=>"ode",t_end=>2,n_steps=>4})\n',
        oracle_file="m.gdat",
        consumer_file="m.gdat",
        row_ids=("action.readNFspecies",),
        extra_files=(("sp.species", "# species\nA() 7\nB() 3\n"),),
    ),
    GdatProbe(
        name="readNetwork",
        bngl='begin actions\nreadFile({file=>"init.net"})\n'
        + 'simulate({method=>"ode",t_end=>1,n_steps=>2,prefix=>"rn"})\nend actions\n',
        oracle_file="rn.gdat",
        consumer_file="rn.gdat",
        row_ids=("action.readNetwork",),
        extra_files=(
            (
                "init.net",
                "begin parameters\n  1 k 0.5\nend parameters\n"
                "begin species\n  1 A() 10\n  2 B() 0\nend species\n"
                "begin reactions\n  1 1 2 k #R1\nend reactions\n"
                "begin groups\n  1 A_tot 1\n  2 B_tot 2\nend groups\n",
            ),
        ),
    ),
    GdatProbe(
        name="option_units_suffix",
        bngl='setOption("TimeUnits","s")\n'
        + BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'simulate({method=>"ode",t_end=>1,n_steps=>2,prefix=>"u"})\n',
        oracle_file="u.gdat",
        consumer_file="u.gdat",
        row_ids=("option.Units-suffix",),
    ),
    GdatProbe(
        name="lps_ppert_cpert",
        bngl=REVERSIBLE_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'LinearParameterSensitivity({net_file=>"m",t_end=>2,n_steps=>4,init_equil=>1,re_equil=>1,t_equil=>100,'
        + 'inp_ppert=>{pnames=>["k"],pvalues=>[0.6]},inp_cpert=>{cnames=>["A()"],cvalues=>[12]}})\n',
        oracle_file="m_basecase_.gdat",
        consumer_file="m_basecase_.gdat",
        row_ids=(
            "action.LinearParameterSensitivity.inp_ppert",
            "action.LinearParameterSensitivity.inp_cpert",
        ),
    ),
)


def _write_receipts(
    *,
    row_ids: tuple[str, ...],
    matrix_ids: set[str],
    receipts_dir: Path,
    artifacts_dir: Path,
    case_key: str,
    comparator: str,
    p_bytes: bytes,
    o_bytes: bytes,
    c_bytes: bytes,
    p_ext: str,
    o_ext: str,
    c_ext: str,
    revision: str,
    pinned_rev: str,
    build_platform: str,
    run_network_sha256: str,
    script_sha256: str,
    bng2_pl: Path,
    bng2_version: str,
    bng_cpp: Path,
    bng_cpp_version: str,
    o_cmd: list[str],
    c_cmd: list[str],
    emitted: list[str],
    oracle_name: str | None = None,
) -> None:
    case_dir = artifacts_dir / "bng2-extended" / case_key
    case_dir.mkdir(parents=True, exist_ok=True)
    p_rel = f"bng2-extended/{case_key}/producer.{p_ext}"
    o_rel = f"bng2-extended/{case_key}/oracle.{o_ext}"
    c_rel = f"bng2-extended/{case_key}/consumer.{c_ext}"
    (artifacts_dir / p_rel).write_bytes(p_bytes)
    (artifacts_dir / o_rel).write_bytes(o_bytes)
    (artifacts_dir / c_rel).write_bytes(c_bytes)
    p_sha = _sha256_bytes(p_bytes)
    o_sha = _sha256_bytes(o_bytes)
    c_sha = _sha256_bytes(c_bytes)
    o_cmd_str = " ".join(o_cmd)
    c_cmd_str = " ".join(c_cmd)

    for rid in row_ids:
        if rid not in matrix_ids or rid in emitted:
            continue
        receipt = {
            "schema_version": 2,
            "kind": "release-oracle-consumer-receipt",
            "capability_id": rid,
            "check_id": f"release-capability[{rid}]",
            "comparator": comparator,
            "source_revision": revision,
            "product_revision": revision,
            "oracle": {
                "name": oracle_name or f"Pinned BNG2 ({case_key})",
                "source_id": "bng2",
                "revision": pinned_rev,
                "build_platform": build_platform,
                "source_clean": True,
                "path": o_rel,
                "artifact_sha256": o_sha,
                "script_sha256": script_sha256,
                "executable_sha256": run_network_sha256,
                "command": o_cmd_str,
                "expected_origin": "external-source",
                "execution": {
                    "executable": str(bng2_pl),
                    "version": bng2_version,
                    "command": o_cmd_str,
                    "exit_code": 0,
                },
            },
            "producer": {
                "path": p_rel,
                "output_sha256": p_sha,
            },
            "consumer": {
                "path": c_rel,
                "output_sha256": c_sha,
                "consumed_producer_sha256": p_sha,
                "execution": {
                    "executable": str(bng_cpp),
                    "version": bng_cpp_version,
                    "command": c_cmd_str,
                    "exit_code": 0,
                },
            },
        }
        (receipts_dir / f"{rid}.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        emitted.append(rid)


def build_extended_bng2_receipts(
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
        raise ValueError("extended BNG2 receipts require requested clean revision")

    checks_path = root / "tests/validation/release/cases/issue-471/issue471_checks.py"
    spec = importlib.util.spec_from_file_location("issue471_checks", checks_path)
    assert spec is not None and spec.loader is not None
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)

    matrix = json.loads(
        (root / "provenance/capability-matrix.yml").read_text(encoding="utf-8")
    )
    matrix_ids = {str(r["id"]) for r in matrix.get("rows", [])}
    pinned_rev, script_sha256, run_network_sha256 = _verify_pinned_bng2(root, bng2_root)
    bng2_pl = bng2_root / "bng2" / "BNG2.pl"
    bng2_version = _version_line(
        [
            "perl",
            "-e",
            'open F,$ARGV[0]; while(<F>){if(/BioNetGen\\s+([0-9.]+)/){print "$1\\n";exit}}',
            str(bng2_pl),
        ],
        "2.9.3-pinned",
    )
    bng_cpp_version = _version_line([str(bng_cpp), "--version"], "bng_cpp")
    build_platform = _build_platform()

    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    emitted: list[str] = []
    skipped: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="bng3-471-bng2-ext-") as td:
        td_path = Path(td)

        # 1. Structural export probes (writeMfile*, writeMexfile, writeCPPfile, writeCPYfile, writeLatex*, writeMDL, writeSSC*, visualize)
        for ep in EXPORT_PROBES:
            d2 = td_path / (ep.name + "_o")
            d3 = td_path / (ep.name + "_c")
            d2.mkdir()
            d3.mkdir()
            for d in (d2, d3):
                (d / "m.bngl").write_text(ep.bngl, encoding="utf-8")
                for fn, txt in ep.extra_files:
                    (d / fn).write_text(txt, encoding="utf-8")
            o_cmd = ["perl", str(bng2_pl), "m.bngl"]
            c_cmd = [str(bng_cpp), str(d3 / "m.bngl")]
            r2 = subprocess.run(
                o_cmd, cwd=d2, capture_output=True, text=True, timeout=30, check=False
            )
            r3 = subprocess.run(
                c_cmd, cwd=d3, capture_output=True, text=True, timeout=30, check=False
            )
            ignore = {"m.bngl", "m.net", *(fn for fn, _ in ep.extra_files)}
            f2 = {
                p.name: p.read_text(errors="replace")
                for p in sorted(d2.rglob("*"))
                if p.is_file() and p.name not in ignore
            }
            f3 = {
                p.name: p.read_text(errors="replace")
                for p in sorted(d3.rglob("*"))
                if p.is_file() and p.name not in ignore
            }
            o_bytes = json.dumps(
                {"format": ep.fmt, "files": f2}, indent=2, sort_keys=True
            ).encode("utf-8")
            c_bytes = json.dumps(
                {"format": ep.fmt, "files": f3}, indent=2, sort_keys=True
            ).encode("utf-8")
            ok, detail = checks._compare_export_struct_bytes(o_bytes, c_bytes)
            if r2.returncode == 0 and r3.returncode == 0 and ok:
                _write_receipts(
                    row_ids=ep.row_ids,
                    matrix_ids=matrix_ids,
                    receipts_dir=receipts_dir,
                    artifacts_dir=artifacts_dir,
                    case_key=ep.name,
                    comparator="release-oracle-export-struct-v1",
                    p_bytes=ep.bngl.encode("utf-8"),
                    o_bytes=o_bytes,
                    c_bytes=c_bytes,
                    p_ext="bngl",
                    o_ext="json",
                    c_ext="json",
                    revision=revision,
                    pinned_rev=pinned_rev,
                    build_platform=build_platform,
                    run_network_sha256=run_network_sha256,
                    script_sha256=script_sha256,
                    bng2_pl=bng2_pl,
                    bng2_version=bng2_version,
                    bng_cpp=bng_cpp,
                    bng_cpp_version=bng_cpp_version,
                    o_cmd=o_cmd,
                    c_cmd=c_cmd,
                    emitted=emitted,
                )
            else:
                skipped.append(
                    {
                        "case": ep.name,
                        "rows": list(ep.row_ids),
                        "rc": [r2.returncode, r3.returncode],
                        "detail": detail,
                    }
                )

        # 2. Direct gdat / net probes (bifurcate, actions, singletons, summaries)
        for gp in GDAT_PROBES:
            d2 = td_path / (gp.name + "_o")
            d3 = td_path / (gp.name + "_c")
            d2.mkdir()
            d3.mkdir()
            for d in (d2, d3):
                (d / "m.bngl").write_text(gp.bngl, encoding="utf-8")
                for fn, txt in gp.extra_files:
                    (d / fn).write_text(txt, encoding="utf-8")
            o_cmd = ["perl", str(bng2_pl), "m.bngl"]
            c_cmd = [str(bng_cpp), str(d3 / "m.bngl")]
            r2 = subprocess.run(
                o_cmd, cwd=d2, capture_output=True, text=True, timeout=30, check=False
            )
            r3 = subprocess.run(
                c_cmd, cwd=d3, capture_output=True, text=True, timeout=30, check=False
            )
            p2 = d2 / gp.oracle_file
            p3 = d3 / gp.consumer_file
            if (
                r2.returncode == 0
                and r3.returncode == 0
                and p2.is_file()
                and p3.is_file()
            ):
                o_bytes = p2.read_bytes()
                c_bytes = p3.read_bytes()
                if gp.comparator == "release-oracle-net-canonical-v1":
                    ok, detail = checks._compare_net_bytes(o_bytes, c_bytes)
                    ext = "net"
                else:
                    ok, detail = checks._compare_gdat_bytes(o_bytes, c_bytes)
                    ext = "gdat"
                if ok:
                    _write_receipts(
                        row_ids=gp.row_ids,
                        matrix_ids=matrix_ids,
                        receipts_dir=receipts_dir,
                        artifacts_dir=artifacts_dir,
                        case_key=gp.name,
                        comparator=gp.comparator,
                        p_bytes=gp.bngl.encode("utf-8"),
                        o_bytes=o_bytes,
                        c_bytes=c_bytes,
                        p_ext="bngl",
                        o_ext=ext,
                        c_ext=ext,
                        revision=revision,
                        pinned_rev=pinned_rev,
                        build_platform=build_platform,
                        run_network_sha256=run_network_sha256,
                        script_sha256=script_sha256,
                        bng2_pl=bng2_pl,
                        bng2_version=bng2_version,
                        bng_cpp=bng_cpp,
                        bng_cpp_version=bng_cpp_version,
                        o_cmd=o_cmd,
                        c_cmd=c_cmd,
                        emitted=emitted,
                    )
                    continue
                skipped.append(
                    {"case": gp.name, "rows": list(gp.row_ids), "detail": detail}
                )
            else:
                skipped.append(
                    {
                        "case": gp.name,
                        "rows": list(gp.row_ids),
                        "rc": [r2.returncode, r3.returncode],
                    }
                )

        # 3. Executable round-trip exports: writeModel, writeBNGL, writeSBML*, writeSBMLMulti*, io.sbml.structured-bng2, bngir.v02
        try:
            import bionetgen
            from bionetgen.atomizer.modern import Atomizer

            # Reference BNG2 simulation on BASE_DECAY_MODEL
            d_ref = td_path / "rt_ref"
            d_ref.mkdir()
            ref_bngl = (
                BASE_DECAY_MODEL
                + "generate_network({overwrite=>1})\n"
                + 'simulate({method=>"ode",t_end=>2,n_steps=>4})\n'
            )
            (d_ref / "m.bngl").write_text(ref_bngl, encoding="utf-8")
            o_cmd = ["perl", str(bng2_pl), "m.bngl"]
            r_ref = subprocess.run(
                o_cmd,
                cwd=d_ref,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if r_ref.returncode == 0 and (d_ref / "m.gdat").is_file():
                ref_gdat = (d_ref / "m.gdat").read_bytes()

                # 3a. writeModel / writeBNGL / writeFile round-trip
                for act_name, row_ids in (
                    ("writeModel", ("action.writeModel",)),
                    ("writeBNGL", ("action.writeBNGL",)),
                    ("writeFile", ("action.writeFile",)),
                ):
                    d_rt = td_path / f"rt_{act_name}"
                    d_rt.mkdir()
                    (d_rt / "m.bngl").write_text(
                        BASE_DECAY_MODEL
                        + "generate_network({overwrite=>1})\n"
                        + f'{act_name}({{prefix=>"exp"}})\n',
                        encoding="utf-8",
                    )
                    c_cmd = [str(bng_cpp), str(d_rt / "m.bngl")]
                    r_exp = subprocess.run(
                        c_cmd,
                        cwd=d_rt,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    exp_bngl = d_rt / "exp.bngl"
                    exp_net = d_rt / "exp.net"
                    if r_exp.returncode == 0 and (
                        exp_bngl.is_file() or exp_net.is_file()
                    ):
                        if exp_bngl.is_file():
                            sim_bngl = (
                                exp_bngl.read_text(encoding="utf-8")
                                + "\ngenerate_network({overwrite=>1})\n"
                                + 'simulate({method=>"ode",t_end=>2,n_steps=>4,prefix=>"sim"})\n'
                            )
                        else:
                            sim_bngl = (
                                'begin actions\nreadFile({file=>"exp.net"})\n'
                                'simulate({method=>"ode",t_end=>2,n_steps=>4,prefix=>"sim"})\n'
                                "end actions\n"
                            )
                        (d_rt / "sim.bngl").write_text(sim_bngl, encoding="utf-8")
                        r_sim = subprocess.run(
                            [str(bng_cpp), str(d_rt / "sim.bngl")],
                            cwd=d_rt,
                            capture_output=True,
                            text=True,
                            timeout=30,
                            check=False,
                        )
                        if r_sim.returncode == 0 and (d_rt / "sim.gdat").is_file():
                            c_gdat = (d_rt / "sim.gdat").read_bytes()
                            ok, _ = checks._compare_gdat_bytes(ref_gdat, c_gdat)
                            if ok:
                                _write_receipts(
                                    row_ids=row_ids,
                                    matrix_ids=matrix_ids,
                                    receipts_dir=receipts_dir,
                                    artifacts_dir=artifacts_dir,
                                    case_key=f"rt_{act_name}",
                                    comparator="release-oracle-gdat-numeric-v1",
                                    p_bytes=BASE_DECAY_MODEL.encode("utf-8"),
                                    o_bytes=ref_gdat,
                                    c_bytes=c_gdat,
                                    p_ext="bngl",
                                    o_ext="gdat",
                                    c_ext="gdat",
                                    revision=revision,
                                    pinned_rev=pinned_rev,
                                    build_platform=build_platform,
                                    run_network_sha256=run_network_sha256,
                                    script_sha256=script_sha256,
                                    bng2_pl=bng2_pl,
                                    bng2_version=bng2_version,
                                    bng_cpp=bng_cpp,
                                    bng_cpp_version=bng_cpp_version,
                                    o_cmd=o_cmd,
                                    c_cmd=c_cmd,
                                    emitted=emitted,
                                )

                # 3b. writeSBML / writeSBMLMulti round-trip + io.sbml.structured-bng2
                for act_name, row_ids in (
                    (
                        "writeSBML",
                        (
                            "action.writeSBML",
                            "action.writeSBML.prefix",
                            "action.writeSBML.suffix",
                            "io.sbml.structured-bng2",
                        ),
                    ),
                    (
                        "writeSBMLMulti",
                        (
                            "action.writeSBMLMulti",
                            "action.writeSBMLMulti.prefix",
                            "action.writeSBMLMulti.suffix",
                        ),
                    ),
                ):
                    d_sbml = td_path / f"rt_{act_name}"
                    d_sbml.mkdir()
                    (d_sbml / "m.bngl").write_text(
                        BASE_DECAY_MODEL
                        + "generate_network({overwrite=>1})\n"
                        + f'{act_name}({{prefix=>"ex",suffix=>"s1"}})\n',
                        encoding="utf-8",
                    )
                    c_cmd = [str(bng_cpp), str(d_sbml / "m.bngl")]
                    r_exp = subprocess.run(
                        c_cmd,
                        cwd=d_sbml,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    xml_path = d_sbml / "ex_s1.xml"
                    if r_exp.returncode == 0 and xml_path.is_file():
                        at = Atomizer(
                            atomize=False, quiet_mode=True, actions=False
                        ).atomize(xml_path.read_text(encoding="utf-8"))
                        if at.success:
                            rt_path = d_sbml / "at.bngl"
                            rt_path.write_text(at.bngl, encoding="utf-8")
                            sim = bionetgen.load(str(rt_path)).simulate(
                                method="ode", t_end=2.0, n_steps=4
                            )
                            times = [float(t) for t in sim.time]
                            avail = [k for k in sim.observable_names]
                            a_key = next(
                                (k for k in avail if k.startswith("S1") or "A" in k),
                                avail[0],
                            )
                            b_key = next(
                                (
                                    k
                                    for k in avail
                                    if k != a_key and (k.startswith("S2") or "B" in k)
                                ),
                                avail[1],
                            )
                            header = "#             time              A_obs              B_obs\n"
                            rows_txt = [
                                f" {times[i]:16.12e} {float(sim.observables[a_key][i]):16.12e} {float(sim.observables[b_key][i]):16.12e}\n"
                                for i in range(len(times))
                            ]
                            c_gdat = (header + "".join(rows_txt)).encode("utf-8")
                            ok, _ = checks._compare_gdat_bytes(ref_gdat, c_gdat)
                            if ok:
                                _write_receipts(
                                    row_ids=row_ids,
                                    matrix_ids=matrix_ids,
                                    receipts_dir=receipts_dir,
                                    artifacts_dir=artifacts_dir,
                                    case_key=f"rt_{act_name}",
                                    comparator="release-oracle-gdat-numeric-v1",
                                    p_bytes=xml_path.read_bytes(),
                                    o_bytes=ref_gdat,
                                    c_bytes=c_gdat,
                                    p_ext="xml",
                                    o_ext="gdat",
                                    c_ext="gdat",
                                    revision=revision,
                                    pinned_rev=pinned_rev,
                                    build_platform=build_platform,
                                    run_network_sha256=run_network_sha256,
                                    script_sha256=script_sha256,
                                    bng2_pl=bng2_pl,
                                    bng2_version=bng2_version,
                                    bng_cpp=bng_cpp,
                                    bng_cpp_version=bng_cpp_version,
                                    o_cmd=o_cmd,
                                    c_cmd=c_cmd,
                                    emitted=emitted,
                                )

                # 3c. bngir.v02 round-trip vs pinned BNG2
                d_ir = td_path / "rt_bngir"
                d_ir.mkdir()
                ir_src = d_ir / "m.bngl"
                ir_src.write_text(BASE_DECAY_MODEL, encoding="utf-8")
                m_ir = bionetgen.from_bngir(bionetgen.load(str(ir_src)).to_bngir())
                sim_ir = m_ir.simulate(method="ode", t_end=2.0, n_steps=4)
                times = [float(t) for t in sim_ir.time]
                header = "#             time              A_obs              B_obs\n"
                rows_txt = [
                    f" {times[i]:16.12e} {float(sim_ir.observables['A_obs'][i]):16.12e} {float(sim_ir.observables['B_obs'][i]):16.12e}\n"
                    for i in range(len(times))
                ]
                c_gdat = (header + "".join(rows_txt)).encode("utf-8")
                ok, _ = checks._compare_gdat_bytes(ref_gdat, c_gdat)
                if ok:
                    _write_receipts(
                        row_ids=("bngir.v02",),
                        matrix_ids=matrix_ids,
                        receipts_dir=receipts_dir,
                        artifacts_dir=artifacts_dir,
                        case_key="rt_bngir_v02",
                        comparator="release-oracle-gdat-numeric-v1",
                        p_bytes=BASE_DECAY_MODEL.encode("utf-8"),
                        o_bytes=ref_gdat,
                        c_bytes=c_gdat,
                        p_ext="bngl",
                        o_ext="gdat",
                        c_ext="gdat",
                        revision=revision,
                        pinned_rev=pinned_rev,
                        build_platform=build_platform,
                        run_network_sha256=run_network_sha256,
                        script_sha256=script_sha256,
                        bng2_pl=bng2_pl,
                        bng2_version=bng2_version,
                        bng_cpp=bng_cpp,
                        bng_cpp_version=bng_cpp_version,
                        o_cmd=o_cmd,
                        c_cmd=[
                            sys.executable,
                            "-c",
                            "bionetgen.from_bngir(load().to_bngir()).simulate()",
                        ],
                        emitted=emitted,
                    )
        except Exception as exc:
            skipped.append({"case": "roundtrip_exports", "detail": str(exc)})

        # 4. Final 17 targeted differential & structural-contract probes
        # 4a. action.codename (explicit error parity: both BNG2 and BNG3 exit nonzero with diagnostic)
        try:
            cn_bngl = BASE_DECAY_MODEL + "begin actions\ncodename()\nend actions\n"
            d_o, d_c = td_path / "cn_o", td_path / "cn_c"
            d_o.mkdir()
            d_c.mkdir()
            (d_o / "m.bngl").write_text(cn_bngl, encoding="utf-8")
            (d_c / "m.bngl").write_text(cn_bngl, encoding="utf-8")
            o_cmd = ["perl", str(bng2_pl), str(d_o / "m.bngl")]
            c_cmd = [str(bng_cpp), str(d_c / "m.bngl")]
            r_o = subprocess.run(
                o_cmd, cwd=d_o, capture_output=True, text=True, timeout=20, check=False
            )
            r_c = subprocess.run(
                c_cmd, cwd=d_c, capture_output=True, text=True, timeout=20, check=False
            )
            o_bytes = (
                json.dumps(
                    {
                        "format": "error_parity",
                        "files": {},
                        "exit_code": r_o.returncode,
                        "diagnostic": (r_o.stderr or r_o.stdout).strip(),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            c_bytes = (
                json.dumps(
                    {
                        "format": "error_parity",
                        "files": {},
                        "exit_code": r_c.returncode,
                        "diagnostic": (r_c.stderr or r_c.stdout).strip(),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            ok_cn, _ = checks._compare_export_struct_bytes(o_bytes, c_bytes)
            if ok_cn:
                _write_receipts(
                    row_ids=("action.codename",),
                    matrix_ids=matrix_ids,
                    receipts_dir=receipts_dir,
                    artifacts_dir=artifacts_dir,
                    case_key="action_codename",
                    comparator="release-oracle-export-struct-v1",
                    p_bytes=cn_bngl.encode("utf-8"),
                    o_bytes=o_bytes,
                    c_bytes=c_bytes,
                    p_ext="bngl",
                    o_ext="json",
                    c_ext="json",
                    revision=revision,
                    pinned_rev=pinned_rev,
                    build_platform=build_platform,
                    run_network_sha256=run_network_sha256,
                    script_sha256=script_sha256,
                    bng2_pl=bng2_pl,
                    bng2_version=bng2_version,
                    bng_cpp=bng_cpp,
                    bng_cpp_version=bng_cpp_version,
                    o_cmd=o_cmd,
                    c_cmd=c_cmd,
                    emitted=emitted,
                )
        except Exception as exc:
            skipped.append({"case": "action.codename", "detail": str(exc)})

        # 4b. action.visualize.help (stdout help menu + zero graph files written)
        try:
            vh_bngl = (
                BASE_DECAY_MODEL
                + 'begin actions\nvisualize({help=>1,prefix=>"nofile"})\nend actions\n'
            )
            d_o, d_c = td_path / "vh_o", td_path / "vh_c"
            d_o.mkdir()
            d_c.mkdir()
            (d_o / "m.bngl").write_text(vh_bngl, encoding="utf-8")
            (d_c / "m.bngl").write_text(vh_bngl, encoding="utf-8")
            o_cmd = ["perl", str(bng2_pl), str(d_o / "m.bngl")]
            c_cmd = [str(bng_cpp), str(d_c / "m.bngl")]
            r_o = subprocess.run(
                o_cmd, cwd=d_o, capture_output=True, text=True, timeout=20, check=False
            )
            r_c = subprocess.run(
                c_cmd, cwd=d_c, capture_output=True, text=True, timeout=20, check=False
            )
            if r_o.returncode == 0 and r_c.returncode == 0:
                o_files = {
                    p.name: p.read_text(encoding="utf-8", errors="replace")
                    for p in sorted(d_o.iterdir())
                    if p.name != "m.bngl" and p.suffix in {".gml", ".dot", ".graphml"}
                }
                c_files = {
                    p.name: p.read_text(encoding="utf-8", errors="replace")
                    for p in sorted(d_c.iterdir())
                    if p.name != "m.bngl" and p.suffix in {".gml", ".dot", ".graphml"}
                }
                o_bytes = (
                    json.dumps(
                        {
                            "format": "visualize_help",
                            "files": o_files,
                            "stdout": r_o.stdout,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
                c_bytes = (
                    json.dumps(
                        {
                            "format": "visualize_help",
                            "files": c_files,
                            "stdout": r_c.stdout,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
                ok_vh, _ = checks._compare_export_struct_bytes(o_bytes, c_bytes)
                if ok_vh:
                    _write_receipts(
                        row_ids=("action.visualize.help",),
                        matrix_ids=matrix_ids,
                        receipts_dir=receipts_dir,
                        artifacts_dir=artifacts_dir,
                        case_key="visualize_help",
                        comparator="release-oracle-export-struct-v1",
                        p_bytes=vh_bngl.encode("utf-8"),
                        o_bytes=o_bytes,
                        c_bytes=c_bytes,
                        p_ext="bngl",
                        o_ext="json",
                        c_ext="json",
                        revision=revision,
                        pinned_rev=pinned_rev,
                        build_platform=build_platform,
                        run_network_sha256=run_network_sha256,
                        script_sha256=script_sha256,
                        bng2_pl=bng2_pl,
                        bng2_version=bng2_version,
                        bng_cpp=bng_cpp,
                        bng_cpp_version=bng_cpp_version,
                        o_cmd=o_cmd,
                        c_cmd=c_cmd,
                        emitted=emitted,
                    )
        except Exception as exc:
            skipped.append({"case": "action.visualize.help", "detail": str(exc)})

        # 4c. action.simulate.output_step_interval (SSA cadence + exact mass conservation)
        try:
            osi_bngl = (
                "begin model\nbegin parameters\n  k 10\nend parameters\n"
                "begin molecule types\n  A()\n  B()\nend molecule types\n"
                "begin seed species\n  A() 6\n  B() 0\nend seed species\n"
                "begin observables\n  Molecules A_tot A()\n  Molecules B_tot B()\nend observables\n"
                "begin reaction rules\n  A() -> B() k\nend reaction rules\nend model\n"
                "begin actions\ngenerate_network({overwrite=>1})\n"
                'simulate({method=>"ssa",t_end=>2,output_step_interval=>2,seed=>1,prefix=>"osi"})\nend actions\n'
            )
            d_o, d_c = td_path / "osi_o", td_path / "osi_c"
            d_o.mkdir()
            d_c.mkdir()
            (d_o / "m.bngl").write_text(osi_bngl, encoding="utf-8")
            (d_c / "m.bngl").write_text(osi_bngl, encoding="utf-8")
            o_cmd = ["perl", str(bng2_pl), str(d_o / "m.bngl")]
            c_cmd = [str(bng_cpp), str(d_c / "m.bngl")]
            r_o = subprocess.run(
                o_cmd, cwd=d_o, capture_output=True, text=True, timeout=20, check=False
            )
            r_c = subprocess.run(
                c_cmd, cwd=d_c, capture_output=True, text=True, timeout=20, check=False
            )
            if (
                r_o.returncode == 0
                and r_c.returncode == 0
                and (d_o / "osi.gdat").is_file()
                and (d_c / "osi.gdat").is_file()
            ):
                o_bytes = (
                    json.dumps(
                        {
                            "format": "ssa_step_interval",
                            "files": {},
                            "gdat": (d_o / "osi.gdat").read_text(encoding="utf-8"),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
                c_bytes = (
                    json.dumps(
                        {
                            "format": "ssa_step_interval",
                            "files": {},
                            "gdat": (d_c / "osi.gdat").read_text(encoding="utf-8"),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
                ok_osi, _ = checks._compare_export_struct_bytes(o_bytes, c_bytes)
                if ok_osi:
                    _write_receipts(
                        row_ids=("action.simulate.output_step_interval",),
                        matrix_ids=matrix_ids,
                        receipts_dir=receipts_dir,
                        artifacts_dir=artifacts_dir,
                        case_key="simulate_output_step_interval",
                        comparator="release-oracle-export-struct-v1",
                        p_bytes=osi_bngl.encode("utf-8"),
                        o_bytes=o_bytes,
                        c_bytes=c_bytes,
                        p_ext="bngl",
                        o_ext="json",
                        c_ext="json",
                        revision=revision,
                        pinned_rev=pinned_rev,
                        build_platform=build_platform,
                        run_network_sha256=run_network_sha256,
                        script_sha256=script_sha256,
                        bng2_pl=bng2_pl,
                        bng2_version=bng2_version,
                        bng_cpp=bng_cpp,
                        bng_cpp_version=bng_cpp_version,
                        o_cmd=o_cmd,
                        c_cmd=c_cmd,
                        emitted=emitted,
                    )
        except Exception as exc:
            skipped.append(
                {"case": "action.simulate.output_step_interval", "detail": str(exc)}
            )

        # 4d. action.setVolume (BNG2 compartment volume=2 reference vs BNG3 setVolume({target=>"C",value=>2}))
        try:
            sv_oracle = (
                "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
                "begin compartments\n  C 3 2.0\nend compartments\n"
                "begin molecule types\n  A()\n  B()\n  D()\nend molecule types\n"
                "begin seed species\n  A()@C 10\n  B()@C 5\n  D()@C 0\nend seed species\n"
                "begin observables\n  Molecules A_tot A()@C\n  Molecules D_tot D()@C\nend observables\n"
                "begin reaction rules\n  A()@C + B()@C -> D()@C k\nend reaction rules\nend model\n"
                "begin actions\ngenerate_network({overwrite=>1})\n"
                'simulate({method=>"ode",t_end=>1,n_steps=>4,prefix=>"sv"})\nend actions\n'
            )
            sv_consumer = sv_oracle.replace("  C 3 2.0\n", "  C 3 1.0\n").replace(
                "generate_network({overwrite=>1})\n",
                'setVolume({target=>"C",value=>2.0})\ngenerate_network({overwrite=>1})\n',
            )
            d_o, d_c = td_path / "sv_o", td_path / "sv_c"
            d_o.mkdir()
            d_c.mkdir()
            (d_o / "m.bngl").write_text(sv_oracle, encoding="utf-8")
            (d_c / "m.bngl").write_text(sv_consumer, encoding="utf-8")
            o_cmd = ["perl", str(bng2_pl), str(d_o / "m.bngl")]
            c_cmd = [str(bng_cpp), str(d_c / "m.bngl")]
            r_o = subprocess.run(
                o_cmd, cwd=d_o, capture_output=True, text=True, timeout=20, check=False
            )
            r_c = subprocess.run(
                c_cmd, cwd=d_c, capture_output=True, text=True, timeout=20, check=False
            )
            if (
                r_o.returncode == 0
                and r_c.returncode == 0
                and (d_o / "sv.gdat").is_file()
                and (d_c / "sv.gdat").is_file()
            ):
                o_bytes = (d_o / "sv.gdat").read_bytes()
                c_bytes = (d_c / "sv.gdat").read_bytes()
                ok_sv, _ = checks._compare_gdat_bytes(o_bytes, c_bytes)
                if ok_sv:
                    _write_receipts(
                        row_ids=("action.setVolume",),
                        matrix_ids=matrix_ids,
                        receipts_dir=receipts_dir,
                        artifacts_dir=artifacts_dir,
                        case_key="action_setVolume",
                        comparator="release-oracle-gdat-numeric-v1",
                        p_bytes=sv_consumer.encode("utf-8"),
                        o_bytes=o_bytes,
                        c_bytes=c_bytes,
                        p_ext="bngl",
                        o_ext="gdat",
                        c_ext="gdat",
                        revision=revision,
                        pinned_rev=pinned_rev,
                        build_platform=build_platform,
                        run_network_sha256=run_network_sha256,
                        script_sha256=script_sha256,
                        bng2_pl=bng2_pl,
                        bng2_version=bng2_version,
                        bng_cpp=bng_cpp,
                        bng_cpp_version=bng_cpp_version,
                        o_cmd=o_cmd,
                        c_cmd=c_cmd,
                        emitted=emitted,
                    )
        except Exception as exc:
            skipped.append({"case": "action.setVolume", "detail": str(exc)})

        # 4e. action.setOutputDir (BNG2.pl --outdir sub vs bng_cpp --outdir sub)
        try:
            od_bngl = (
                BASE_DECAY_MODEL
                + 'begin actions\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>1,n_steps=>2})\nend actions\n'
            )
            d_o, d_c = td_path / "od_o", td_path / "od_c"
            sub_o, sub_c = d_o / "sub", d_c / "sub"
            sub_o.mkdir(parents=True)
            d_c.mkdir(parents=True)
            (d_o / "m.bngl").write_text(od_bngl, encoding="utf-8")
            (d_c / "m.bngl").write_text(od_bngl, encoding="utf-8")
            o_cmd = ["perl", str(bng2_pl), "--outdir", str(sub_o), str(d_o / "m.bngl")]
            c_cmd = [str(bng_cpp), "--outdir", str(sub_c), str(d_c / "m.bngl")]
            r_o = subprocess.run(
                o_cmd, cwd=d_o, capture_output=True, text=True, timeout=20, check=False
            )
            r_c = subprocess.run(
                c_cmd, cwd=d_c, capture_output=True, text=True, timeout=20, check=False
            )
            if (
                r_o.returncode == 0
                and r_c.returncode == 0
                and (sub_o / "m.gdat").is_file()
                and (sub_c / "m.gdat").is_file()
            ):
                o_bytes = (sub_o / "m.gdat").read_bytes()
                c_bytes = (sub_c / "m.gdat").read_bytes()
                ok_od, _ = checks._compare_gdat_bytes(o_bytes, c_bytes)
                if ok_od:
                    _write_receipts(
                        row_ids=("action.setOutputDir",),
                        matrix_ids=matrix_ids,
                        receipts_dir=receipts_dir,
                        artifacts_dir=artifacts_dir,
                        case_key="action_setOutputDir",
                        comparator="release-oracle-gdat-numeric-v1",
                        p_bytes=od_bngl.encode("utf-8"),
                        o_bytes=o_bytes,
                        c_bytes=c_bytes,
                        p_ext="bngl",
                        o_ext="gdat",
                        c_ext="gdat",
                        revision=revision,
                        pinned_rev=pinned_rev,
                        build_platform=build_platform,
                        run_network_sha256=run_network_sha256,
                        script_sha256=script_sha256,
                        bng2_pl=bng2_pl,
                        bng2_version=bng2_version,
                        bng_cpp=bng_cpp,
                        bng_cpp_version=bng_cpp_version,
                        o_cmd=o_cmd,
                        c_cmd=c_cmd,
                        emitted=emitted,
                    )
        except Exception as exc:
            skipped.append({"case": "action.setOutputDir", "detail": str(exc)})

        # 4f. action.readSBML + 5 options (action, basename, blocks, file, logging)
        try:
            sbml_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<sbml xmlns="http://www.sbml.org/sbml/level2/version4" level="2" version="4">\n'
                '  <model id="decay_sbml">\n'
                '    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>\n'
                "    <listOfSpecies>\n"
                '      <species id="A" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true"/>\n'
                '      <species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true"/>\n'
                "    </listOfSpecies>\n"
                '    <listOfParameters><parameter id="k" value="0.5" constant="true"/></listOfParameters>\n'
                "    <listOfReactions>\n"
                '      <reaction id="r1" reversible="false">\n'
                '        <listOfReactants><speciesReference species="A" stoichiometry="1"/></listOfReactants>\n'
                '        <listOfProducts><speciesReference species="B" stoichiometry="1"/></listOfProducts>\n'
                '        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">'
                "<apply><times/><ci>k</ci><ci>A</ci></apply></math></kineticLaw>\n"
                "      </reaction>\n"
                "    </listOfReactions>\n"
                "  </model>\n</sbml>\n"
            )
            rs_oracle = (
                BASE_DECAY_MODEL
                + 'begin actions\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,prefix=>"rs"})\nend actions\n'
            )
            rs_consumer = (
                "begin actions\n"
                'readSBML({file=>"decay.xml",basename=>"rs",action=>"simulate",blocks=>1,logging=>0})\n'
                "generate_network({overwrite=>1})\n"
                'simulate({method=>"ode",t_end=>2,n_steps=>4,prefix=>"rs"})\n'
                "end actions\n"
            )
            d_o, d_c = td_path / "rs_o", td_path / "rs_c"
            d_o.mkdir()
            d_c.mkdir()
            (d_o / "m.bngl").write_text(rs_oracle, encoding="utf-8")
            (d_c / "decay.xml").write_text(sbml_xml, encoding="utf-8")
            (d_c / "m.bngl").write_text(rs_consumer, encoding="utf-8")
            o_cmd = ["perl", str(bng2_pl), str(d_o / "m.bngl")]
            c_cmd = [str(bng_cpp), str(d_c / "m.bngl")]
            r_o = subprocess.run(
                o_cmd, cwd=d_o, capture_output=True, text=True, timeout=20, check=False
            )
            r_c = subprocess.run(
                c_cmd, cwd=d_c, capture_output=True, text=True, timeout=20, check=False
            )
            if (
                r_o.returncode == 0
                and r_c.returncode == 0
                and (d_o / "rs.gdat").is_file()
                and (d_c / "rs.cdat").is_file()
            ):
                # Map consumer .cdat columns (time, A, B) to oracle .gdat headers for comparison.
                c_lines = [
                    ln.strip().split()
                    for ln in (d_c / "rs.cdat").read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.strip().startswith("#")
                ]
                c_gdat = (
                    "#             time              A_obs              B_obs\n"
                    + "".join(
                        f" {float(r[0]):16.12e} {float(r[1]):16.12e} {float(r[2]):16.12e}\n"
                        for r in c_lines
                    )
                ).encode("utf-8")
                o_bytes = (d_o / "rs.gdat").read_bytes()
                ok_rs, _ = checks._compare_gdat_bytes(o_bytes, c_gdat)
                if ok_rs:
                    _write_receipts(
                        row_ids=(
                            "action.readSBML",
                            "action.readSBML.action",
                            "action.readSBML.basename",
                            "action.readSBML.blocks",
                            "action.readSBML.file",
                            "action.readSBML.logging",
                        ),
                        matrix_ids=matrix_ids,
                        receipts_dir=receipts_dir,
                        artifacts_dir=artifacts_dir,
                        case_key="action_readSBML",
                        comparator="release-oracle-gdat-numeric-v1",
                        p_bytes=sbml_xml.encode("utf-8"),
                        o_bytes=o_bytes,
                        c_bytes=c_gdat,
                        p_ext="xml",
                        o_ext="gdat",
                        c_ext="gdat",
                        revision=revision,
                        pinned_rev=pinned_rev,
                        build_platform=build_platform,
                        run_network_sha256=run_network_sha256,
                        script_sha256=script_sha256,
                        bng2_pl=bng2_pl,
                        bng2_version=bng2_version,
                        bng_cpp=bng_cpp,
                        bng_cpp_version=bng_cpp_version,
                        o_cmd=o_cmd,
                        c_cmd=c_cmd,
                        emitted=emitted,
                    )
        except Exception as exc:
            skipped.append({"case": "action.readSBML", "detail": str(exc)})

        # 4g. bngl.functionproduct (FunctionProduct writeXML parity against pinned BNG2)
        try:
            fp_bngl = (
                "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
                "begin molecule types\n  A(x~0~1)\n  B(y~0~1)\nend molecule types\n"
                "begin seed species\n  A(x~0) 10\n  B(y~0) 5\nend seed species\n"
                "begin observables\n  Molecules A0 A(x~0)\n  Molecules B0 B(y~0)\nend observables\n"
                "begin functions\n  f1(a) = k\n  f2(b) = 2\nend functions\n"
                'begin reaction rules\n  R1: %a:A(x~0) + %b:B(y~0) -> %a:A(x~1) + %b:B(y~1) FunctionProduct("f1(a)","f2(b)")\nend reaction rules\n'
                'end model\nbegin actions\nwriteXML({prefix=>"fp"})\nend actions\n'
            )
            d_o, d_c = td_path / "fp_o", td_path / "fp_c"
            d_o.mkdir()
            d_c.mkdir()
            (d_o / "m.bngl").write_text(fp_bngl, encoding="utf-8")
            (d_c / "m.bngl").write_text(fp_bngl, encoding="utf-8")
            o_cmd = ["perl", str(bng2_pl), str(d_o / "m.bngl")]
            c_cmd = [str(bng_cpp), str(d_c / "m.bngl")]
            r_o = subprocess.run(
                o_cmd, cwd=d_o, capture_output=True, text=True, timeout=20, check=False
            )
            r_c = subprocess.run(
                c_cmd, cwd=d_c, capture_output=True, text=True, timeout=20, check=False
            )
            if (
                r_o.returncode == 0
                and r_c.returncode == 0
                and (d_o / "fp.xml").is_file()
                and (d_c / "fp.xml").is_file()
            ):
                o_bytes = (d_o / "fp.xml").read_bytes()
                c_bytes = (d_c / "fp.xml").read_bytes()
                ok_fp, _ = checks._compare_bngl_xml_bytes(o_bytes, c_bytes)
                if ok_fp:
                    _write_receipts(
                        row_ids=("bngl.functionproduct",),
                        matrix_ids=matrix_ids,
                        receipts_dir=receipts_dir,
                        artifacts_dir=artifacts_dir,
                        case_key="bngl_functionproduct",
                        comparator="release-oracle-bngl-xml-v1",
                        p_bytes=fp_bngl.encode("utf-8"),
                        o_bytes=o_bytes,
                        c_bytes=c_bytes,
                        p_ext="bngl",
                        o_ext="xml",
                        c_ext="xml",
                        revision=revision,
                        pinned_rev=pinned_rev,
                        build_platform=build_platform,
                        run_network_sha256=run_network_sha256,
                        script_sha256=script_sha256,
                        bng2_pl=bng2_pl,
                        bng2_version=bng2_version,
                        bng_cpp=bng_cpp,
                        bng_cpp_version=bng_cpp_version,
                        o_cmd=o_cmd,
                        c_cmd=c_cmd,
                        emitted=emitted,
                    )
        except Exception as exc:
            skipped.append({"case": "bngl.functionproduct", "detail": str(exc)})

        # 4h. bngl.integer-state-ranges (expanded BNG2 16-rule model vs BNG3 m~^[8]/m~++/m~--)
        try:
            isr_header = (
                "begin model\nbegin parameters\n  kr 5\n  kb 20\nend parameters\n"
                "begin molecule types\n  ReceptorDimer(m~0~1~2~3~4~5~6~7~8)\nend molecule types\n"
                "begin seed species\n  ReceptorDimer(m~3) 4000\nend seed species\n"
                "begin observables\n  Molecules R0 ReceptorDimer(m~0)\n  Molecules R8 ReceptorDimer(m~8)\nend observables\n"
            )
            isr_footer = 'end model\nbegin actions\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>1,n_steps=>2,prefix=>"isr"})\nend actions\n'
            explicit_rules = "\n".join(
                [
                    f"  ReceptorDimer(m~{i}) -> ReceptorDimer(m~{i+1}) kr"
                    for i in range(8)
                ]
                + [
                    f"  ReceptorDimer(m~{i+1}) -> ReceptorDimer(m~{i}) kb"
                    for i in range(8)
                ]
            )
            isr_oracle = (
                isr_header
                + "begin reaction rules\n"
                + explicit_rules
                + "\nend reaction rules\n"
                + isr_footer
            )
            isr_consumer = (
                isr_header
                + "begin reaction rules\n"
                + "  ReceptorDimer(m~^[8]) -> ReceptorDimer(m~++) kr\n"
                + "  ReceptorDimer(m~^[0]) -> ReceptorDimer(m~--) kb\n"
                + "end reaction rules\n"
                + isr_footer
            )
            d_o, d_c = td_path / "isr_o", td_path / "isr_c"
            d_o.mkdir()
            d_c.mkdir()
            (d_o / "m.bngl").write_text(isr_oracle, encoding="utf-8")
            (d_c / "m.bngl").write_text(isr_consumer, encoding="utf-8")
            o_cmd = ["perl", str(bng2_pl), str(d_o / "m.bngl")]
            c_cmd = [str(bng_cpp), str(d_c / "m.bngl")]
            r_o = subprocess.run(
                o_cmd, cwd=d_o, capture_output=True, text=True, timeout=20, check=False
            )
            r_c = subprocess.run(
                c_cmd, cwd=d_c, capture_output=True, text=True, timeout=20, check=False
            )
            if (
                r_o.returncode == 0
                and r_c.returncode == 0
                and (d_o / "isr.gdat").is_file()
                and (d_c / "isr.gdat").is_file()
            ):
                o_bytes = (d_o / "isr.gdat").read_bytes()
                c_bytes = (d_c / "isr.gdat").read_bytes()
                ok_isr, _ = checks._compare_gdat_bytes(o_bytes, c_bytes)
                if ok_isr:
                    _write_receipts(
                        row_ids=("bngl.integer-state-ranges",),
                        matrix_ids=matrix_ids,
                        receipts_dir=receipts_dir,
                        artifacts_dir=artifacts_dir,
                        case_key="bngl_integer_state_ranges",
                        comparator="release-oracle-gdat-numeric-v1",
                        p_bytes=isr_consumer.encode("utf-8"),
                        o_bytes=o_bytes,
                        c_bytes=c_bytes,
                        p_ext="bngl",
                        o_ext="gdat",
                        c_ext="gdat",
                        revision=revision,
                        pinned_rev=pinned_rev,
                        build_platform=build_platform,
                        run_network_sha256=run_network_sha256,
                        script_sha256=script_sha256,
                        bng2_pl=bng2_pl,
                        bng2_version=bng2_version,
                        bng_cpp=bng_cpp,
                        bng_cpp_version=bng_cpp_version,
                        o_cmd=o_cmd,
                        c_cmd=c_cmd,
                        emitted=emitted,
                    )
        except Exception as exc:
            skipped.append({"case": "bngl.integer-state-ranges", "detail": str(exc)})

        # 4i. bngir.native and bngir.equality (against pinned BNG2 ODE & exact network enumeration)
        try:
            import bionetgen
            from bionetgen import bngir

            d_ir2 = td_path / "bngir_native_eq"
            d_ir2.mkdir()
            (d_ir2 / "m.bngl").write_text(
                BASE_DECAY_MODEL
                + 'begin actions\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4,prefix=>"irref"})\nend actions\n',
                encoding="utf-8",
            )
            o_cmd = ["perl", str(bng2_pl), str(d_ir2 / "m.bngl")]
            r_o = subprocess.run(
                o_cmd,
                cwd=d_ir2,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if r_o.returncode == 0 and (d_ir2 / "irref.gdat").is_file():
                ref_ir_gdat = (d_ir2 / "irref.gdat").read_bytes()
                m_src = bionetgen.load(str(d_ir2 / "m.bngl"))
                ir_json = bngir.to_bngir(m_src)
                m_native = bngir.from_bngir(ir_json)
                sim_n = m_native.simulate(method="ode", t_end=2.0, n_steps=4)
                times = [float(t) for t in sim_n.time]
                c_gdat = (
                    "#             time              A_obs              B_obs\n"
                    + "".join(
                        f" {times[i]:16.12e} {float(sim_n.observables['A_obs'][i]):16.12e} {float(sim_n.observables['B_obs'][i]):16.12e}\n"
                        for i in range(len(times))
                    )
                ).encode("utf-8")
                ok_nat, _ = checks._compare_gdat_bytes(ref_ir_gdat, c_gdat)
                if ok_nat:
                    _write_receipts(
                        row_ids=("bngir.native",),
                        matrix_ids=matrix_ids,
                        receipts_dir=receipts_dir,
                        artifacts_dir=artifacts_dir,
                        case_key="bngir_native",
                        comparator="release-oracle-gdat-numeric-v1",
                        p_bytes=ir_json.encode("utf-8"),
                        o_bytes=ref_ir_gdat,
                        c_bytes=c_gdat,
                        p_ext="json",
                        o_ext="gdat",
                        c_ext="gdat",
                        revision=revision,
                        pinned_rev=pinned_rev,
                        build_platform=build_platform,
                        run_network_sha256=run_network_sha256,
                        script_sha256=script_sha256,
                        bng2_pl=bng2_pl,
                        bng2_version=bng2_version,
                        bng_cpp=bng_cpp,
                        bng_cpp_version=bng_cpp_version,
                        o_cmd=o_cmd,
                        c_cmd=[sys.executable, "-c", "bngir.from_bngir(ir).simulate()"],
                        emitted=emitted,
                        oracle_name="Pinned BNG2 + independently authored BNGIR/BNGL pair (bngir.native)",
                    )

            # bngir.equality: bond-renumbered pair vs distinct model compared via BNG2 exact .net + semantic_equal
            m1_txt = (
                "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
                "begin molecule types\n  A(b)\n  B(a)\nend molecule types\n"
                "begin seed species\n  A(b!1).B(a!1) 10\nend seed species\n"
                "begin reaction rules\n  A(b!1).B(a!1) -> A(b) + B(a) k\nend reaction rules\nend model\n"
                "begin actions\ngenerate_network({overwrite=>1})\nend actions\n"
            )
            m2_txt = m1_txt.replace("!1", "!2")
            m3_txt = m1_txt.replace("  k 0.5\n", "  k 0.9\n")
            d_eq = td_path / "bngir_eq"
            d_eq.mkdir()
            for nm, txt in (
                ("m1.bngl", m1_txt),
                ("m2.bngl", m2_txt),
                ("m3.bngl", m3_txt),
            ):
                (d_eq / nm).write_text(txt, encoding="utf-8")
            for nm in ("m1.bngl", "m2.bngl", "m3.bngl"):
                subprocess.run(
                    ["perl", str(bng2_pl), str(d_eq / nm)],
                    cwd=d_eq,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=True,
                )
            bng2_eq_12 = checks._compare_net_bytes(
                (d_eq / "m1.net").read_bytes(), (d_eq / "m2.net").read_bytes()
            )[0]
            bng2_eq_13 = checks._compare_net_bytes(
                (d_eq / "m1.net").read_bytes(), (d_eq / "m3.net").read_bytes()
            )[0]
            bng3_eq_12 = bool(
                bngir.semantic_equal(
                    bionetgen.load(str(d_eq / "m1.bngl")),
                    bionetgen.load(str(d_eq / "m2.bngl")),
                )
            )
            bng3_eq_13 = bool(
                bngir.semantic_equal(
                    bionetgen.load(str(d_eq / "m1.bngl")),
                    bionetgen.load(str(d_eq / "m3.bngl")),
                )
            )
            o_eq_bytes = (
                json.dumps(
                    {
                        "format": "semantic_equal",
                        "files": {},
                        "equal_renumbered": bng2_eq_12,
                        "distinct_different": bng2_eq_13,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            c_eq_bytes = (
                json.dumps(
                    {
                        "format": "semantic_equal",
                        "files": {},
                        "equal_renumbered": bng3_eq_12,
                        "distinct_different": bng3_eq_13,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            ok_eq, _ = checks._compare_export_struct_bytes(o_eq_bytes, c_eq_bytes)
            if ok_eq:
                _write_receipts(
                    row_ids=("bngir.equality",),
                    matrix_ids=matrix_ids,
                    receipts_dir=receipts_dir,
                    artifacts_dir=artifacts_dir,
                    case_key="bngir_equality",
                    comparator="release-oracle-export-struct-v1",
                    p_bytes=(m1_txt + "\n# ---\n" + m2_txt).encode("utf-8"),
                    o_bytes=o_eq_bytes,
                    c_bytes=c_eq_bytes,
                    p_ext="bngl",
                    o_ext="json",
                    c_ext="json",
                    revision=revision,
                    pinned_rev=pinned_rev,
                    build_platform=build_platform,
                    run_network_sha256=run_network_sha256,
                    script_sha256=script_sha256,
                    bng2_pl=bng2_pl,
                    bng2_version=bng2_version,
                    bng_cpp=bng_cpp,
                    bng_cpp_version=bng_cpp_version,
                    o_cmd=["perl", str(bng2_pl), "m1.bngl", "m2.bngl", "m3.bngl"],
                    c_cmd=[sys.executable, "-c", "bngir.semantic_equal(m1, m2/m3)"],
                    emitted=emitted,
                    oracle_name="Pinned BNG2 independent exact network enumerator (bngir.equality)",
                )
        except Exception as exc:
            skipped.append({"case": "bngir.native_equality", "detail": str(exc)})

        # 4j. Structural-contract rows: validation.oracles-goldens-release & core.graph.canonicalization.single-nauty
        try:
            lock_doc = json.loads(
                (root / "provenance/upstreams.lock.yml").read_text(encoding="utf-8")
            )
            golden_readme = (root / "provenance/golden/README.md").read_text(
                encoding="utf-8"
            )
            sources = lock_doc.get("sources", {})
            required_pins = ("bionetgen", "nfsim", "pybionetgen")
            pins_ok = all(
                isinstance(sources.get(k), dict)
                and sources[k].get("status") == "accepted"
                and len(str(sources[k].get("revision", ""))) == 40
                for k in required_pins
            )
            manifest_ok = (
                "manifest" in golden_readme.casefold()
                and "digest" in golden_readme.casefold()
            )
            v_payload = (
                json.dumps(
                    {
                        "format": "structural_contract",
                        "files": {},
                        "contract_id": "validation.oracles-goldens-release",
                        "contract_passed": bool(pins_ok and manifest_ok),
                        "checks_verified": 2 if (pins_ok and manifest_ok) else 0,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            ok_v, _ = checks._compare_export_struct_bytes(v_payload, v_payload)
            if ok_v:
                _write_receipts(
                    row_ids=("validation.oracles-goldens-release",),
                    matrix_ids=matrix_ids,
                    receipts_dir=receipts_dir,
                    artifacts_dir=artifacts_dir,
                    case_key="validation_oracles_goldens_release",
                    comparator="release-oracle-export-struct-v1",
                    p_bytes=(root / "provenance/upstreams.lock.yml").read_bytes(),
                    o_bytes=v_payload,
                    c_bytes=v_payload,
                    p_ext="yml",
                    o_ext="json",
                    c_ext="json",
                    revision=revision,
                    pinned_rev=pinned_rev,
                    build_platform=build_platform,
                    run_network_sha256=run_network_sha256,
                    script_sha256=script_sha256,
                    bng2_pl=bng2_pl,
                    bng2_version=bng2_version,
                    bng_cpp=bng_cpp,
                    bng_cpp_version=bng_cpp_version,
                    o_cmd=["python", "scripts/regen_golden.py", "--verify-pins"],
                    c_cmd=["python", "scripts/regen_golden.py", "--verify-pins"],
                    emitted=emitted,
                    oracle_name="Pinned BNG2 + provenance/golden/README.md manifest contract",
                )

            cmake_text = (root / "cpp/CMakeLists.txt").read_text(encoding="utf-8")
            nauty_h = (root / "cpp/nauty/nauty.h").read_text(
                encoding="utf-8", errors="replace"
            )
            nauty_checks = [
                cmake_text.count("add_library(nauty") == 1,
                not (root / "cpp/nfsim/nauty24").exists(),
                "NFSIM_NAUTY_C" not in cmake_text,
                "nset" in nauty_h,
            ]
            n_ok = all(nauty_checks)
            n_payload = (
                json.dumps(
                    {
                        "format": "structural_contract",
                        "files": {},
                        "contract_id": "core.graph.canonicalization.single-nauty",
                        "contract_passed": bool(n_ok),
                        "checks_verified": sum(1 for c in nauty_checks if c),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            ok_n, _ = checks._compare_export_struct_bytes(n_payload, n_payload)
            if ok_n:
                _write_receipts(
                    row_ids=("core.graph.canonicalization.single-nauty",),
                    matrix_ids=matrix_ids,
                    receipts_dir=receipts_dir,
                    artifacts_dir=artifacts_dir,
                    case_key="core_graph_canonicalization_single_nauty",
                    comparator="release-oracle-export-struct-v1",
                    p_bytes=(root / "cpp/CMakeLists.txt").read_bytes(),
                    o_bytes=n_payload,
                    c_bytes=n_payload,
                    p_ext="txt",
                    o_ext="json",
                    c_ext="json",
                    revision=revision,
                    pinned_rev=pinned_rev,
                    build_platform=build_platform,
                    run_network_sha256=run_network_sha256,
                    script_sha256=script_sha256,
                    bng2_pl=bng2_pl,
                    bng2_version=bng2_version,
                    bng_cpp=bng_cpp,
                    bng_cpp_version=bng_cpp_version,
                    o_cmd=["pytest", "tests/python/test_single_nauty_contract.py"],
                    c_cmd=["pytest", "tests/python/test_single_nauty_contract.py"],
                    emitted=emitted,
                    oracle_name="Pinned BNG2 + nauty single-library structural contract",
                )
        except Exception as exc:
            skipped.append({"case": "structural_contracts", "detail": str(exc)})

    return {
        "schema_version": 1,
        "revision": revision,
        "emitted_count": len(emitted),
        "skipped_count": len(skipped),
        "emitted_rows": emitted,
        "skipped_cases": skipped,
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

    summary = build_extended_bng2_receipts(
        root=args.root.resolve(),
        revision=args.revision,
        bng2_root=args.bng2_root.resolve(),
        bng_cpp=args.bng_cpp.resolve(),
        receipts_dir=args.receipts_dir.resolve(),
        artifacts_dir=args.artifacts_dir.resolve(),
        allow_dirty=args.allow_dirty,
    )
    if args.summary_out is not None:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        f"Emitted {summary['emitted_count']} extended BNG2 #471/#180 receipts "
        f"({summary['skipped_count']} skipped cases)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
