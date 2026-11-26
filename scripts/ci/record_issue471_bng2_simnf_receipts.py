#!/usr/bin/env python3
"""Emit schema-v2 #471/#180 differential receipts for ``action.simulate_nf.*``.

Runs pinned ``BNG2.pl`` backed by pinned native ``NFsim`` via a read-only
``BNGPATH`` symlink wrapper (without modifying either pinned checkout) against
``bng_cpp`` on deterministic ``Issue51`` probes, emitting schema-v2 receipts
ONLY where oracle and consumer outputs agree under ``issue471_checks``.
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

_GDAT = "release-oracle-gdat-numeric-v1"
_BYTES = "release-oracle-byte-equality-v1"


@dataclass(frozen=True)
class SimNfProbeSpec:
    """Single pinned-BNG2+NFsim vs bng_cpp simulate_nf option probe."""

    row_id: str
    action_line: str
    output_file: str = "probe.gdat"
    comparator: str = _GDAT


SIMNF_PROBES: tuple[SimNfProbeSpec, ...] = (
    SimNfProbeSpec("action.simulate_nf", "simulate_nf({t_end=>1,n_steps=>1,seed=>1})"),
    SimNfProbeSpec(
        "action.simulate_nf.t_start",
        "simulate_nf({t_start=>0,t_end=>1,n_steps=>1,seed=>1})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.t_end",
        "simulate_nf({t_end=>2,n_steps=>1,seed=>1})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.n_steps",
        "simulate_nf({t_end=>1,n_steps=>2,seed=>1})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.seed",
        "simulate_nf({t_end=>1,n_steps=>1,seed=>7})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.complex",
        "simulate_nf({t_end=>1,n_steps=>1,seed=>1,complex=>1})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.utl",
        "simulate_nf({t_end=>1,n_steps=>1,seed=>1,utl=>3})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.gml",
        "simulate_nf({t_end=>1,n_steps=>1,seed=>1,gml=>1000})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.prefix",
        'simulate_nf({t_end=>1,n_steps=>1,seed=>1,prefix=>"p1"})',
        output_file="p1.gdat",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.suffix",
        'simulate_nf({t_end=>1,n_steps=>1,seed=>1,suffix=>"s1"})',
        output_file="probe_s1.gdat",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.param",
        'simulate_nf({t_end=>1,n_steps=>1,seed=>1,param=>"-utl 3"})',
    ),
    SimNfProbeSpec(
        "action.simulate_nf.equil",
        "simulate_nf({t_end=>1,n_steps=>1,seed=>1,equil=>0.5})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.nocslf",
        "simulate_nf({t_end=>1,n_steps=>1,seed=>1,nocslf=>1})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.notf",
        "simulate_nf({t_end=>1,n_steps=>1,seed=>1,notf=>1})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.verbose",
        "simulate_nf({t_end=>1,n_steps=>1,seed=>1,verbose=>1})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.get_final_state",
        "simulate_nf({t_end=>1,n_steps=>1,seed=>1,get_final_state=>1})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.print_functions",
        "simulate_nf({t_end=>1,n_steps=>1,seed=>1,print_functions=>1})",
    ),
    SimNfProbeSpec(
        "action.simulate_nf.binary_output",
        "simulate_nf({t_end=>1,n_steps=>1,seed=>1,binary_output=>1})",
        comparator=_BYTES,
    ),
)


def _compare(comparator: str, oracle_bytes: bytes, consumer_bytes: bytes) -> bool:
    if comparator == _GDAT:
        ok, _ = checks._compare_gdat_bytes(oracle_bytes, consumer_bytes)
        return ok
    if comparator == _BYTES:
        return oracle_bytes == consumer_bytes
    raise ValueError(f"unsupported comparator: {comparator}")


def build_bng2_simnf_receipts(
    *,
    root: Path,
    revision: str,
    bng2_root: Path,
    nfsim_source: Path,
    nfsim_oracle: Path,
    bng_cpp: Path,
    receipts_dir: Path,
    artifacts_dir: Path,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    head = _git_head(root)
    if head != revision or (_git_dirty(root) and not allow_dirty):
        raise ValueError(
            "issue #471 BNG2 simulate_nf receipts require the requested clean revision"
        )
    pinned_rev, script_sha256, run_network_sha256 = _verify_pinned_bng2(root, bng2_root)
    bng2_pl = (bng2_root / "bng2" / "BNG2.pl").resolve()
    run_network = (bng2_root / "bng2" / "bin" / "run_network").resolve()
    lock = json.loads((root / "provenance/upstreams.lock.yml").read_text("utf-8"))
    pinned_nfsim_rev = str(lock["sources"]["nfsim"]["revision"])
    actual_nfsim_rev = _git_head(nfsim_source)
    if actual_nfsim_rev != pinned_nfsim_rev:
        raise ValueError(
            f"NFsim oracle revision {actual_nfsim_rev} != locked {pinned_nfsim_rev}"
        )
    if _git_dirty(nfsim_source, ignore_untracked=True):
        raise ValueError("NFsim oracle source checkout has tracked modifications")
    if not nfsim_oracle.is_file() or not os.access(nfsim_oracle, os.X_OK):
        raise ValueError(f"NFsim oracle executable missing: {nfsim_oracle}")
    if not bng_cpp.is_file() or not os.access(bng_cpp, os.X_OK):
        raise ValueError(f"bng_cpp executable missing: {bng_cpp}")

    issue51_bngl = nfsim_source / "test/Issue51/issue51.bngl"
    model_part = (
        issue51_bngl.read_text(encoding="utf-8").split("end model")[0] + "end model\n"
    )

    build_platform = _build_platform()
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
    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    emitted: list[str] = []
    skipped: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        bng_wrap = td_path / "bng_wrap"
        bng_wrap.mkdir()
        (bng_wrap / "Perl2").symlink_to((bng2_root / "bng2/Perl2").resolve())
        (bng_wrap / "BNG2.pl").symlink_to(bng2_pl)
        (bng_wrap / "bin").mkdir()
        (bng_wrap / "bin/run_network").symlink_to(run_network)
        (bng_wrap / "bin/NFsim").symlink_to(nfsim_oracle.resolve())

        oracle_env = os.environ.copy()
        oracle_env["BNGPATH"] = str(bng_wrap)

        for idx, spec in enumerate(SIMNF_PROBES):
            bngl_text = model_part + spec.action_line + "\n"
            oracle_dir = td_path / f"{idx:03d}_{spec.row_id}_oracle"
            consumer_dir = td_path / f"{idx:03d}_{spec.row_id}_consumer"
            oracle_dir.mkdir(parents=True, exist_ok=True)
            consumer_dir.mkdir(parents=True, exist_ok=True)

            o_in = oracle_dir / "probe.bngl"
            c_in = consumer_dir / "probe.bngl"
            o_in.write_text(bngl_text, encoding="utf-8")
            c_in.write_text(bngl_text, encoding="utf-8")

            o_cmd = ["perl", str(bng_wrap / "BNG2.pl"), str(o_in)]
            c_cmd = [str(bng_cpp), str(c_in)]

            o_proc = subprocess.run(
                o_cmd,
                cwd=oracle_dir,
                env=oracle_env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            c_proc = subprocess.run(
                c_cmd,
                cwd=consumer_dir,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            o_out = oracle_dir / spec.output_file
            c_out = consumer_dir / spec.output_file
            if (
                o_proc.returncode != 0
                or c_proc.returncode != 0
                or not o_out.is_file()
                or not c_out.is_file()
            ):
                skipped.append(
                    {
                        "id": spec.row_id,
                        "reason": "execution_failed",
                        "oracle_rc": o_proc.returncode,
                        "consumer_rc": c_proc.returncode,
                    }
                )
                continue

            o_bytes = o_out.read_bytes()
            c_bytes = c_out.read_bytes()
            if not _compare(spec.comparator, o_bytes, c_bytes):
                skipped.append(
                    {
                        "id": spec.row_id,
                        "reason": "comparator_mismatch",
                        "comparator": spec.comparator,
                    }
                )
                continue

            row_art = artifacts_dir / spec.row_id
            row_art.mkdir(parents=True, exist_ok=True)
            producer_bytes = bngl_text.encode("utf-8")
            producer_rel = f"{spec.row_id}/producer.bngl"
            oracle_rel = f"{spec.row_id}/oracle.gdat"
            consumer_rel = f"{spec.row_id}/consumer.gdat"
            (artifacts_dir / producer_rel).write_bytes(producer_bytes)
            (artifacts_dir / oracle_rel).write_bytes(o_bytes)
            (artifacts_dir / consumer_rel).write_bytes(c_bytes)

            producer_sha = _sha256_bytes(producer_bytes)
            oracle_sha = _sha256_bytes(o_bytes)
            consumer_sha = _sha256_bytes(c_bytes)
            o_cmd_str = f"perl BNG2.pl {spec.row_id}.bngl"
            c_cmd_str = f"bng_cpp {spec.row_id}.bngl"

            receipt = {
                "schema_version": 2,
                "kind": "release-oracle-consumer-receipt",
                "capability_id": spec.row_id,
                "check_id": f"release-capability[{spec.row_id}]",
                "comparator": spec.comparator,
                "source_revision": revision,
                "product_revision": revision,
                "oracle": {
                    "name": f"Pinned BNG2.pl + NFsim ({spec.row_id})",
                    "source_id": "bng2",
                    "revision": pinned_rev,
                    "build_platform": build_platform,
                    "source_clean": True,
                    "path": oracle_rel,
                    "artifact_sha256": oracle_sha,
                    "script_sha256": script_sha256,
                    "executable_sha256": run_network_sha256,
                    "command": o_cmd_str,
                    "expected_origin": "external-source",
                    "execution": {
                        "executable": "perl",
                        "version": bng2_version,
                        "command": o_cmd_str,
                        "exit_code": 0,
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
                        "command": c_cmd_str,
                        "exit_code": 0,
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
        "nfsim_oracle_revision": pinned_nfsim_rev,
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
    parser.add_argument("--nfsim-source", type=Path, required=True)
    parser.add_argument("--nfsim-oracle", type=Path, required=True)
    parser.add_argument("--bng-cpp", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    summary = build_bng2_simnf_receipts(
        root=args.root.resolve(),
        revision=args.revision,
        bng2_root=args.bng2_root.resolve(),
        nfsim_source=args.nfsim_source.resolve(),
        nfsim_oracle=args.nfsim_oracle.resolve(),
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
        f"Emitted {summary['emitted_count']} BNG2 simulate_nf #471/#180 receipts "
        f"({summary['skipped_count']} skipped) for {summary['source_revision'][:8]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
