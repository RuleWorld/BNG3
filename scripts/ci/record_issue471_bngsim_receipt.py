#!/usr/bin/env python3
"""Emit schema-v2 #471 oracle-consumer receipt for backend.bngsim against pinned BNG2."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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

_MODEL = """begin model
begin parameters
    k 0.25
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 100
end seed species
begin observables
    Molecules Aobs A()
    Molecules Bobs B()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""

_ORACLE_ACTIONS = """generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>2.0,n_steps=>8})
"""


def _trajectory_to_gdat(result: Any) -> bytes:
    cols = ["time", *result.observables.keys()]
    header = "# " + " ".join(cols)
    rows = [header]
    times = list(result.time)
    for idx, t_val in enumerate(times):
        vals = [f"{float(t_val):.12g}"] + [
            f"{float(result.observables[name][idx]):.12g}"
            for name in result.observables
        ]
        rows.append(" ".join(vals))
    return ("\n".join(rows) + "\n").encode("utf-8")


def build_bngsim_receipt(
    *,
    root: Path,
    revision: str,
    bng2_root: Path,
    bngsim_root: Path,
    receipts_dir: Path,
    artifacts_dir: Path,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    head = _git_head(root)
    dirty = _git_dirty(root)
    if head != revision or (dirty and not allow_dirty):
        raise ValueError(
            "issue #471 BNGsim receipt requires the requested clean revision"
        )

    lock = json.loads((root / "provenance/upstreams.lock.yml").read_text("utf-8"))
    bngsim_pin = str(lock["sources"]["bngsim"]["revision"])
    actual_bngsim = _git_head(bngsim_root)
    if actual_bngsim != bngsim_pin or _git_dirty(bngsim_root, ignore_untracked=True):
        raise ValueError(
            f"pinned bngsim checkout mismatch: {actual_bngsim} != {bngsim_pin}"
        )

    pinned_rev, script_sha256, run_network_sha256 = _verify_pinned_bng2(root, bng2_root)
    bng2_pl = (bng2_root / "bng2" / "BNG2.pl").resolve()
    bng2_version = _version_line(
        [
            "perl",
            "-e",
            'open F,$ARGV[0]; while(<F>){if(/BioNetGen\\s+([0-9.]+)/){print "$1\\n";exit}}',
            str(bng2_pl),
        ],
        "2.9.3-pinned",
    )

    sys.path.insert(0, str(root / "tests/validation/release/cases/issue-471"))
    import bionetgen
    import issue471_checks as checks

    row_id = "backend.bngsim"
    inp_bytes = _MODEL.encode("utf-8")
    with tempfile.TemporaryDirectory() as tmp_dir:
        work = Path(tmp_dir)
        model_path = work / "bngsim_ode.bngl"
        model_path.write_bytes(inp_bytes)
        oracle_dir = work / "bng2"
        oracle_dir.mkdir()
        oracle_model_path = oracle_dir / "bngsim_ode.bngl"
        oracle_model_path.write_text(_MODEL + _ORACLE_ACTIONS, encoding="utf-8")
        env = dict(os.environ, BNGPATH=str(bng2_pl.parent))
        proc = subprocess.run(
            ["perl", str(bng2_pl), "--outdir", str(oracle_dir), str(oracle_model_path)],
            cwd=oracle_dir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise ValueError(f"pinned BNG2 failed: {proc.stdout}\n{proc.stderr}")
        oracle_gdat = oracle_dir / "bngsim_ode.gdat"
        if not oracle_gdat.is_file():
            raise ValueError("pinned BNG2 did not emit bngsim_ode.gdat")
        oracle_bytes = oracle_gdat.read_bytes()

        res = bionetgen.load(model_path).simulate(
            method="ode", backend="bngsim", t_end=2.0, n_steps=8
        )
        consumer_bytes = _trajectory_to_gdat(res)
        matched, detail = checks._compare_gdat_bytes(oracle_bytes, consumer_bytes)
        if not matched:
            raise ValueError(f"BNGsim ODE parity failed: {detail}")

    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    row_dir = artifacts_dir / row_id
    row_dir.mkdir(parents=True, exist_ok=True)
    producer_rel = f"{row_id}/producer.bngl"
    oracle_rel = f"{row_id}/oracle.gdat"
    consumer_rel = f"{row_id}/consumer.gdat"
    (artifacts_dir / producer_rel).write_bytes(inp_bytes)
    (artifacts_dir / oracle_rel).write_bytes(oracle_bytes)
    (artifacts_dir / consumer_rel).write_bytes(consumer_bytes)
    producer_sha = _sha256_bytes(inp_bytes)

    receipt = {
        "schema_version": 2,
        "kind": "release-oracle-consumer-receipt",
        "capability_id": row_id,
        "check_id": f"release-capability[{row_id}]",
        "comparator": "release-oracle-gdat-numeric-v1",
        "source_revision": revision,
        "product_revision": revision,
        "oracle": {
            "name": "Pinned BNG2 reference vs BNGsim adapter",
            "source_id": "bng2",
            "revision": pinned_rev,
            "bngsim_revision": bngsim_pin,
            "build_platform": _build_platform(),
            "source_clean": True,
            "path": oracle_rel,
            "artifact_sha256": _sha256_bytes(oracle_bytes),
            "script_sha256": script_sha256,
            "executable_sha256": run_network_sha256,
            "command": "perl BNG2.pl bngsim_ode.bngl",
            "expected_origin": "external-source",
            "execution": {
                "executable": "BNG2.pl",
                "version": bng2_version,
                "command": "perl BNG2.pl bngsim_ode.bngl",
                "exit_code": 0,
            },
        },
        "producer": {
            "path": producer_rel,
            "output_sha256": producer_sha,
        },
        "consumer": {
            "path": consumer_rel,
            "output_sha256": _sha256_bytes(consumer_bytes),
            "consumed_producer_sha256": producer_sha,
            "execution": {
                "executable": "bionetgen.simulate(backend='bngsim')",
                "version": bngsim_pin[:12],
                "command": "bionetgen.load(producer.bngl).simulate(method='ode', backend='bngsim')",
                "exit_code": 0,
            },
        },
    }
    (receipts_dir / f"{row_id}.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "schema_version": 1,
        "revision": revision,
        "oracle_revision": pinned_rev,
        "bngsim_revision": bngsim_pin,
        "emitted_rows": [row_id],
        "count": 1,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--bng2-root", type=Path, required=True)
    parser.add_argument("--bngsim-root", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    summary = build_bngsim_receipt(
        root=args.root.resolve(),
        revision=args.revision,
        bng2_root=args.bng2_root.resolve(),
        bngsim_root=args.bngsim_root.resolve(),
        receipts_dir=args.receipts_dir.resolve(),
        artifacts_dir=args.artifacts_dir.resolve(),
        allow_dirty=args.allow_dirty,
    )
    if args.summary_out is not None:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    print(f"emitted {summary['count']} #471 backend.bngsim consumer receipt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
