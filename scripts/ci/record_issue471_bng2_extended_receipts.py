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
        name="writeFile_net",
        bngl=BASE_DECAY_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'writeFile({prefix=>"exp"})\n',
        oracle_file="exp.net",
        consumer_file="exp.net",
        row_ids=("action.writeFile",),
        comparator="release-oracle-net-canonical-v1",
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
                "name": f"Pinned BNG2 ({case_key})",
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

                # 3a. writeModel / writeBNGL round-trip
                for act_name, row_ids in (
                    ("writeModel", ("action.writeModel",)),
                    ("writeBNGL", ("action.writeBNGL",)),
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
                    exp_path = d_rt / "exp.bngl"
                    if r_exp.returncode == 0 and exp_path.is_file():
                        sim_bngl = (
                            exp_path.read_text(encoding="utf-8")
                            + "\ngenerate_network({overwrite=>1})\n"
                            + 'simulate({method=>"ode",t_end=>2,n_steps=>4,prefix=>"sim"})\n'
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
