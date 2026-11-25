#!/usr/bin/env python3
"""Emit schema-v2 #471 oracle-consumer receipts for implemented BNG2 probes.

Covers verified implemented matrix rows with self-contained BNGL inputs run
directly through pinned BNG2.pl (external oracle) and bng_cpp (downstream
consumer):
- 24 builtin.* expression functions (.gdat numeric trajectory parity)
- 14 operator.* expression operators (13 .gdat numeric + 1 .net canonical parity)
- 2 additional bngl.* rows (indexed-declarations, null-reactants-and-products)
- 7 action.generate_hybrid_model* rows (hybrid BNGL and BNG XML parity)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import numpy as np

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
from tests.validation import compare  # noqa: E402


@dataclass(frozen=True)
class ProbeSpec:
    """Single pinned-BNG2 vs bng_cpp probe mapped to one capability row."""

    row_id: str
    comparator: str
    output_file: str
    bngl_text: str


def _ode_expr_bngl(expr: str) -> str:
    return (
        "begin model\n"
        "begin parameters\n"
        "  kdec 0.25\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A()\n"
        "end molecule types\n"
        "begin seed species\n"
        "  A() 1.0\n"
        "end seed species\n"
        "begin observables\n"
        "  Molecules A_obs A()\n"
        "end observables\n"
        "begin functions\n"
        f"  probe() = {expr}\n"
        "end functions\n"
        "begin reaction rules\n"
        "  0 -> A() probe()\n"
        "  A() -> 0 kdec\n"
        "end reaction rules\n"
        "end model\n"
        "generate_network({overwrite=>1})\n"
        'simulate({method=>"ode",t_end=>1.0,n_steps=>4})\n'
    )


def _param_net_bngl(expr: str) -> str:
    return (
        "begin model\n"
        "begin parameters\n"
        f"  p1 {expr}\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A()\n"
        "end molecule types\n"
        "begin seed species\n"
        "  A() 1\n"
        "end seed species\n"
        "begin reaction rules\n"
        "  A() -> 0 p1\n"
        "end reaction rules\n"
        "end model\n"
        "generate_network({overwrite=>1})\n"
    )


_ODE_EXPRESSIONS: tuple[tuple[str, str], ...] = (
    ("builtin.exp", "exp(0.5)"),
    ("builtin.ln", "ln(2.5)"),
    ("builtin.log10", "log10(100.0)"),
    ("builtin.log2", "log2(8.0)"),
    ("builtin.abs", "abs(-3.5)"),
    ("builtin.rint", "rint(2.7)"),
    ("builtin.sqrt", "sqrt(9.0)"),
    ("builtin.cos", "cos(0.4)"),
    ("builtin.sin", "sin(0.4)"),
    ("builtin.tan", "tan(0.4)"),
    ("builtin.asin", "asin(0.5)"),
    ("builtin.acos", "acos(0.5)"),
    ("builtin.atan", "atan(0.5)"),
    ("builtin.sinh", "sinh(0.5)"),
    ("builtin.cosh", "cosh(0.5)"),
    ("builtin.tanh", "tanh(0.5)"),
    ("builtin.asinh", "asinh(0.5)"),
    ("builtin.acosh", "acosh(2.0)"),
    ("builtin.atanh", "atanh(0.5)"),
    ("builtin.if", "if(A_obs > 3, 2.0, 0.5)"),
    ("builtin.min", "min(2.0, A_obs)"),
    ("builtin.max", "max(2.0, A_obs)"),
    ("builtin.sum", "sum(1.0, 2.0, 3.0)"),
    ("builtin.avg", "avg(1.0, 2.0, 6.0)"),
    ("operator.352", "1.0 + 2.0"),
    ("operator.353", "5.0 - 2.0"),
    ("operator.354", "2.0 * 3.0"),
    ("operator.355", "6.0 / 2.0"),
    ("operator.356", "2.0 ^ 3.0"),
    ("operator.358", "if(A_obs > 2.0, 2.0, 0.5)"),
    ("operator.359", "if(A_obs < 4.0, 2.0, 0.5)"),
    ("operator.360", "if(A_obs >= 2.0, 2.0, 0.5)"),
    ("operator.361", "if(A_obs <= 4.0, 2.0, 0.5)"),
    ("operator.362", "if(1.0 == 1.0, 2.0, 0.5)"),
    ("operator.363", "if(1.0 != 2.0, 2.0, 0.5)"),
    ("operator.365", "if((1.0 == 1.0) && (2.0 > 1.0), 2.0, 0.5)"),
    ("operator.366", "if((1.0 == 2.0) || (2.0 > 1.0), 2.0, 0.5)"),
)

_STATIC_PROBES: tuple[ProbeSpec, ...] = (
    ProbeSpec(
        row_id="operator.357",
        comparator="release-oracle-net-canonical-v1",
        output_file="probe.net",
        bngl_text=_param_net_bngl("2.0 ** 3.0"),
    ),
    ProbeSpec(
        row_id="bngl.indexed-declarations",
        comparator="release-oracle-net-canonical-v1",
        output_file="probe.net",
        bngl_text=(
            "begin model\n"
            "begin parameters\n"
            "  k 0.5\n"
            "end parameters\n"
            "begin molecule types\n"
            "  A()\n"
            "  B()\n"
            "end molecule types\n"
            "begin seed species\n"
            "  1 A() 10\n"
            "end seed species\n"
            "begin reaction rules\n"
            "  R1: A() -> B() k\n"
            "end reaction rules\n"
            "end model\n"
            "generate_network({overwrite=>1})\n"
        ),
    ),
    ProbeSpec(
        row_id="bngl.null-reactants-and-products",
        comparator="release-oracle-net-canonical-v1",
        output_file="probe.net",
        bngl_text=(
            "begin model\n"
            "begin parameters\n"
            "  ksyn 2.0\n"
            "  kdeg 0.5\n"
            "end parameters\n"
            "begin molecule types\n"
            "  A()\n"
            "end molecule types\n"
            "begin seed species\n"
            "  A() 1\n"
            "end seed species\n"
            "begin reaction rules\n"
            "  R1: 0 -> A() ksyn\n"
            "  R2: A() -> 0 kdeg\n"
            "end reaction rules\n"
            "end model\n"
            "generate_network({overwrite=>1})\n"
        ),
    ),
)


def _hybrid_bngl(action_line: str) -> str:
    return (
        "begin model\n"
        "begin parameters\n"
        "  k 0.5\n"
        "  k_pop 100\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A()\n"
        "  B()\n"
        "end molecule types\n"
        "begin seed species\n"
        "  A() 10\n"
        "end seed species\n"
        "begin observables\n"
        "  Molecules A_obs A()\n"
        "  Molecules B_obs B()\n"
        "end observables\n"
        "begin reaction rules\n"
        "  R1: A() -> B() k\n"
        "end reaction rules\n"
        "begin population maps\n"
        "  A() -> A_pop() k_pop\n"
        "end population maps\n"
        "end model\n"
        f"{action_line}\n"
    )


_HYBRID_PROBES: tuple[ProbeSpec, ...] = (
    ProbeSpec(
        row_id="action.generate_hybrid_model",
        comparator="release-oracle-bngl-hybrid-v1",
        output_file="probe_hpp.bngl",
        bngl_text=_hybrid_bngl("generate_hybrid_model({overwrite=>1})"),
    ),
    ProbeSpec(
        row_id="action.generate_hybrid_model.actions",
        comparator="release-oracle-bngl-xml-v1",
        output_file="probe_hpp.xml",
        bngl_text=_hybrid_bngl(
            'generate_hybrid_model({overwrite=>1,execute=>1,actions=>["writeXML()"]})'
        ),
    ),
    ProbeSpec(
        row_id="action.generate_hybrid_model.execute",
        comparator="release-oracle-bngl-xml-v1",
        output_file="probe_hpp.xml",
        bngl_text=_hybrid_bngl(
            'generate_hybrid_model({overwrite=>1,execute=>1,actions=>["writeXML()"]})'
        ),
    ),
    ProbeSpec(
        row_id="action.generate_hybrid_model.overwrite",
        comparator="release-oracle-bngl-hybrid-v1",
        output_file="probe_hpp.bngl",
        bngl_text=_hybrid_bngl("generate_hybrid_model({overwrite=>1})"),
    ),
    ProbeSpec(
        row_id="action.generate_hybrid_model.prefix",
        comparator="release-oracle-bngl-hybrid-v1",
        output_file="cust_hpp.bngl",
        bngl_text=_hybrid_bngl('generate_hybrid_model({overwrite=>1,prefix=>"cust"})'),
    ),
    ProbeSpec(
        row_id="action.generate_hybrid_model.suffix",
        comparator="release-oracle-bngl-hybrid-v1",
        output_file="probe_hyb.bngl",
        bngl_text=_hybrid_bngl('generate_hybrid_model({overwrite=>1,suffix=>"hyb"})'),
    ),
    ProbeSpec(
        row_id="action.generate_hybrid_model.verbose",
        comparator="release-oracle-bngl-hybrid-v1",
        output_file="probe_hpp.bngl",
        bngl_text=_hybrid_bngl("generate_hybrid_model({overwrite=>1,verbose=>1})"),
    ),
)

PROBE_SPECS: dict[str, ProbeSpec] = {
    **{
        row_id: ProbeSpec(
            row_id=row_id,
            comparator="release-oracle-gdat-numeric-v1",
            output_file="probe.gdat",
            bngl_text=_ode_expr_bngl(expr),
        )
        for row_id, expr in _ODE_EXPRESSIONS
    },
    **{spec.row_id: spec for spec in _STATIC_PROBES},
    **{spec.row_id: spec for spec in _HYBRID_PROBES},
}


def _verify_pair(comparator: str, oracle_path: Path, consumer_path: Path) -> None:
    if comparator == "release-oracle-net-canonical-v1":
        ref_net = compare.parse_net(oracle_path)
        sub_net = compare.parse_net(consumer_path)
        if ref_net is None or sub_net is None:
            raise ValueError(
                f"could not parse .net outputs {oracle_path} / {consumer_path}"
            )
        diff = compare.compare_net(ref_net, sub_net)
        if not diff.ok:
            raise ValueError(f".net parity failed: {diff.summary()}")
        return
    if comparator == "release-oracle-gdat-numeric-v1":
        ref_vals, ref_cols = compare.parse_gdat(oracle_path)
        sub_vals, sub_cols = compare.parse_gdat(consumer_path)
        if ref_vals is None or sub_vals is None or ref_cols != sub_cols:
            raise ValueError(f".gdat parse/column mismatch: {ref_cols} vs {sub_cols}")
        if not (
            np.isfinite(ref_vals).all()
            and np.isfinite(sub_vals).all()
            and ref_vals.shape == sub_vals.shape
            and np.allclose(ref_vals, sub_vals, rtol=1e-6, atol=1e-10, equal_nan=False)
        ):
            raise ValueError(f".gdat numeric mismatch for {oracle_path.name}")
        return
    if comparator == "release-oracle-bngl-hybrid-v1":
        matched, detail = checks._compare_hybrid_bngl_bytes(
            oracle_path.read_bytes(), consumer_path.read_bytes()
        )
        if not matched:
            raise ValueError(f"hybrid BNGL parity failed: {detail}")
        return
    if comparator == "release-oracle-bngl-xml-v1":
        matched, detail = checks._compare_bngl_xml_bytes(
            oracle_path.read_bytes(), consumer_path.read_bytes()
        )
        if not matched:
            raise ValueError(f"BNG XML parity failed: {detail}")
        return
    raise ValueError(f"unsupported probe comparator: {comparator}")


def _verify_hybrid_option_behavior(
    row_id: str,
    ref_dir: Path,
    sub_dir: Path,
    ref_proc: subprocess.CompletedProcess[str],
    sub_proc: subprocess.CompletedProcess[str],
    bng2_pl: Path,
    bng2_env: dict[str, str],
    bng_cpp: Path,
) -> None:
    if row_id == "action.generate_hybrid_model":
        if (ref_dir / "probe_hpp.xml").exists() or (sub_dir / "probe_hpp.xml").exists():
            raise ValueError(f"{row_id}: execute=>0 unexpectedly created probe_hpp.xml")
    elif row_id == "action.generate_hybrid_model.verbose":
        for label, proc in (("oracle", ref_proc), ("consumer", sub_proc)):
            combined = proc.stdout + "\n" + proc.stderr
            if "verbose => 1" not in combined:
                raise ValueError(
                    f"{row_id}: {label} omitted verbose => 1 diagnostic output"
                )
    elif row_id == "action.generate_hybrid_model.overwrite":
        no_ow_bngl = _hybrid_bngl("generate_hybrid_model({overwrite=>0})")
        sentinel = "# existing hybrid model\n"
        for label, cmd, cwd, env in (
            ("oracle", ["perl", str(bng2_pl)], ref_dir / "no_ow", bng2_env),
            ("consumer", [str(bng_cpp)], sub_dir / "no_ow", None),
        ):
            cwd.mkdir(parents=True, exist_ok=True)
            (cwd / "probe.bngl").write_text(no_ow_bngl, encoding="utf-8")
            target = cwd / "probe_hpp.bngl"
            target.write_text(sentinel, encoding="utf-8")
            proc = subprocess.run(
                [*cmd, str(cwd / "probe.bngl")],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0 or target.read_text(encoding="utf-8") != sentinel:
                raise ValueError(
                    f"{row_id}: {label} failed to refuse overwrite=>0 on existing output"
                )


def build_bng2_probe_receipts(
    *,
    root: Path,
    revision: str,
    bng2_root: Path,
    bng_cpp: Path,
    receipts_dir: Path,
    artifacts_dir: Path,
    rows: list[str] | None = None,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    """Execute pinned BNG2 and bng_cpp probes and write schema-v2 receipts."""
    head = _git_head(root)
    dirty = _git_dirty(root)
    if head != revision or (dirty and not allow_dirty):
        raise ValueError(
            "issue #471 BNG2 probe receipts require the requested clean revision"
        )
    matrix = json.loads(
        (root / "provenance/capability-matrix.yml").read_text(encoding="utf-8")
    )
    matrix_by_id = {entry["id"]: entry for entry in matrix.get("rows", [])}
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
    bng2_env = {
        **dict(__import__("os").environ),
        "BNGPATH": str((bng2_root / "bng2").resolve()),
    }

    selected = rows if rows else list(PROBE_SPECS)
    unknown = [row_id for row_id in selected if row_id not in PROBE_SPECS]
    if unknown:
        raise ValueError(f"unmapped #471 BNG2 probe row(s): {unknown}")

    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    emitted: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        work_root = Path(tmp_dir)
        for row_id in selected:
            matrix_row = matrix_by_id.get(row_id)
            if matrix_row is None or matrix_row.get("status") != "implemented":
                raise ValueError(f"{row_id} is not an implemented matrix row")
            spec = PROBE_SPECS[row_id]
            inp_bytes = spec.bngl_text.encode("utf-8")
            ref_dir = work_root / row_id / "oracle"
            sub_dir = work_root / row_id / "consumer"
            ref_dir.mkdir(parents=True, exist_ok=True)
            sub_dir.mkdir(parents=True, exist_ok=True)
            ref_bngl = ref_dir / "probe.bngl"
            sub_bngl = sub_dir / "probe.bngl"
            ref_bngl.write_bytes(inp_bytes)
            sub_bngl.write_bytes(inp_bytes)
            if row_id == "action.generate_hybrid_model.overwrite":
                for target_dir in (ref_dir, sub_dir):
                    (target_dir / spec.output_file).write_text(
                        "# stale pre-existing target\n", encoding="utf-8"
                    )

            ref_cmd = ["perl", str(bng2_pl), str(ref_bngl)]
            sub_cmd = [str(bng_cpp), str(sub_bngl)]
            ref_proc = subprocess.run(
                ref_cmd,
                cwd=ref_dir,
                env=bng2_env,
                capture_output=True,
                text=True,
                check=False,
            )
            if ref_proc.returncode != 0:
                raise ValueError(
                    f"{row_id}: pinned BNG2 probe failed: {ref_proc.stdout}\n{ref_proc.stderr}"
                )
            sub_proc = subprocess.run(
                sub_cmd,
                cwd=sub_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if sub_proc.returncode != 0:
                raise ValueError(
                    f"{row_id}: bng_cpp probe failed: {sub_proc.stdout}\n{sub_proc.stderr}"
                )
            ref_out = ref_dir / spec.output_file
            sub_out = sub_dir / spec.output_file
            if not ref_out.is_file() or not sub_out.is_file():
                raise ValueError(
                    f"{row_id}: missing output {spec.output_file} (oracle={ref_out.is_file()}, consumer={sub_out.is_file()})"
                )
            _verify_pair(spec.comparator, ref_out, sub_out)
            _verify_hybrid_option_behavior(
                row_id,
                ref_dir,
                sub_dir,
                ref_proc,
                sub_proc,
                bng2_pl,
                bng2_env,
                bng_cpp,
            )

            ref_bytes = ref_out.read_bytes()
            sub_bytes = sub_out.read_bytes()
            ext = Path(spec.output_file).suffix
            row_art_dir = artifacts_dir / row_id
            row_art_dir.mkdir(parents=True, exist_ok=True)
            producer_rel = f"{row_id}/producer.bngl"
            oracle_rel = f"{row_id}/oracle{ext}"
            consumer_rel = f"{row_id}/consumer{ext}"
            (artifacts_dir / producer_rel).write_bytes(inp_bytes)
            (artifacts_dir / oracle_rel).write_bytes(ref_bytes)
            (artifacts_dir / consumer_rel).write_bytes(sub_bytes)

            producer_sha = _sha256_bytes(inp_bytes)
            oracle_sha = _sha256_bytes(ref_bytes)
            consumer_sha = _sha256_bytes(sub_bytes)
            receipt = {
                "schema_version": 2,
                "kind": "release-oracle-consumer-receipt",
                "capability_id": row_id,
                "check_id": f"release-capability[{row_id}]",
                "comparator": spec.comparator,
                "source_revision": revision,
                "product_revision": revision,
                "oracle": {
                    "name": f"Pinned BNG2 ({row_id})",
                    "source_id": "bng2",
                    "revision": pinned_rev,
                    "build_platform": build_platform,
                    "source_clean": True,
                    "path": oracle_rel,
                    "artifact_sha256": oracle_sha,
                    "script_sha256": script_sha256,
                    "executable_sha256": run_network_sha256,
                    "command": f"perl BNG2.pl {row_id}.bngl",
                    "expected_origin": "external-source",
                    "execution": {
                        "executable": "BNG2.pl",
                        "version": bng2_version,
                        "command": f"perl BNG2.pl {row_id}.bngl",
                        "exit_code": int(ref_proc.returncode),
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
                        "command": f"bng_cpp {row_id}.bngl",
                        "exit_code": int(sub_proc.returncode),
                    },
                },
            }
            (receipts_dir / f"{row_id}.json").write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )
            emitted.append(row_id)

    return {
        "schema_version": 1,
        "revision": revision,
        "oracle_revision": pinned_rev,
        "emitted_rows": emitted,
        "count": len(emitted),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--bng2-root", type=Path, required=True)
    parser.add_argument("--bng-cpp", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--row", action="append", dest="rows")
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    summary = build_bng2_probe_receipts(
        root=args.root.resolve(),
        revision=args.revision,
        bng2_root=args.bng2_root.resolve(),
        bng_cpp=args.bng_cpp.resolve(),
        receipts_dir=args.receipts_dir.resolve(),
        artifacts_dir=args.artifacts_dir.resolve(),
        rows=args.rows,
        allow_dirty=args.allow_dirty,
    )
    if args.summary_out is not None:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    print(f"emitted {summary['count']} #471 BNG2 probe consumer receipts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
