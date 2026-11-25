#!/usr/bin/env python3
"""Emit schema-version-2 #471 oracle-consumer receipts from BNG2 conformance outputs.

This script packages exact-revision producer inputs, pinned BNG2 oracle .net
outputs, and downstream BNG3 .net outputs already produced by the bng2-parity
conformance run so issue471_checks.py can independently verify byte digests and
run its owned canonical .net comparator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.validation import compare  # noqa: E402

ROW_MODELS: dict[str, str] = {
    "bngl.model-blocks": "egfr_net",
    "bngl.parameters": "egfr_net",
    "bngl.molecule-types": "egfr_net",
    "bngl.species-and-seed-species": "egfr_net",
    "bngl.reaction-rules": "egfr_net",
    "bngl.comments-and-line-continuations": "egfr_net",
    "bngl.molecule-names": "egfr_net",
    "bngl.site-names": "egfr_net",
    "bngl.internal-states": "egfr_net",
    "bngl.numeric-bonds": "egfr_net",
    "bngl.wildcard-bonds": "egfr_net",
    "bngl.unbound-sites": "egfr_net",
    "bngl.omitted-sites": "egfr_net",
    "bngl.disconnected-patterns": "egfr_net",
    "bngl.symmetric-identical-sites": "egfr_net",
    "bngl.irreversible-rules": "egfr_net",
    "bngl.reversible-rules": "egfr_net",
    "bngl.binding": "egfr_net",
    "bngl.unbinding": "egfr_net",
    "bngl.state-changes": "egfr_net",
    "bngl.reaction-center-symmetry": "egfr_net",
    "bngl.connected-context-preservation": "egfr_net",
    "bngl.multiple-pattern-terms": "egfr_net",
    "bngl.mass-action": "egfr_net",
    "bngl.reverse-rates": "egfr_net",
    "bngl.statistical-rate-factors": "egfr_net",
    "bngl.compartments": "Motivating_example_cBNGL",
    "bngl.compartment-annotations": "Motivating_example_cBNGL",
    "bngl.deletemolecules": "Motivating_example_cBNGL",
    "bngl.molecule-creation": "Motivating_example_cBNGL",
    "bngl.molecule-deletion": "Motivating_example_cBNGL",
    "bngl.functions": "localfunc",
    "bngl.molecule-and-pattern-labels": "localfunc",
    "bngl.ele": "egfr_net",
    "bngl.matchonce": "localfunc",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()


def _git_dirty(repo: Path, *, ignore_untracked: bool = False) -> bool:
    cmd = ["git", "-C", str(repo), "status", "--porcelain"]
    if ignore_untracked:
        cmd.append("--untracked-files=no")
    return bool(subprocess.check_output(cmd, text=True).strip())


def _build_platform() -> str:
    system = sys.platform
    machine = platform.machine().lower()
    if system == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    if system.startswith("linux"):
        return f"linux-{machine or 'x86_64'}"
    return f"{system}-{machine or 'unknown'}"


def _version_line(command: list[str], fallback: str) -> str:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        return fallback
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0] if text else fallback


def _verify_pinned_bng2(root: Path, bng2_root: Path) -> tuple[str, str, str]:
    lock = json.loads((root / "provenance/upstreams.lock.yml").read_text("utf-8"))
    expected = str(lock["sources"]["bionetgen"]["revision"])
    actual = _git_head(bng2_root)
    if actual != expected:
        raise ValueError(f"BNG2 oracle revision {actual} != locked {expected}")
    if _git_dirty(bng2_root, ignore_untracked=True):
        raise ValueError("BNG2 oracle source checkout has tracked modifications")
    bng2_pl = bng2_root / "bng2" / "BNG2.pl"
    run_network = bng2_root / "bng2" / "bin" / "run_network"
    if not bng2_pl.is_file():
        raise ValueError(f"missing pinned BNG2.pl: {bng2_pl}")
    if not run_network.is_file():
        raise ValueError(f"missing pinned BNG2 run_network: {run_network}")
    return (
        expected,
        _sha256_bytes(bng2_pl.read_bytes()),
        _sha256_bytes(run_network.read_bytes()),
    )


def _format_cmd(cmd: Any, fallback: str) -> str:
    if isinstance(cmd, list) and cmd:
        return " ".join(str(part) for part in cmd)
    if isinstance(cmd, str) and cmd.strip():
        return cmd.strip()
    return fallback


def build_bng2_receipts(
    *,
    root: Path,
    revision: str,
    conformance_dir: Path,
    bng2_root: Path,
    receipts_dir: Path,
    artifacts_dir: Path,
    bng_cpp: Path | None = None,
    rows: list[str] | None = None,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    head = _git_head(root)
    dirty = _git_dirty(root)
    if head != revision or (dirty and not allow_dirty):
        raise ValueError(
            "issue #471 BNG2 receipts require the requested clean revision"
        )

    report_path = conformance_dir / "report.json"
    if not report_path.is_file():
        raise ValueError(f"missing conformance report: {report_path}")
    conf_report = json.loads(report_path.read_text(encoding="utf-8"))
    conf_source = conf_report.get("source", {})
    if conf_source.get("revision") != revision or conf_source.get("dirty") is not False:
        raise ValueError("conformance report revision or cleanliness mismatch")

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
    bng_cpp_version = (
        _version_line([str(bng_cpp), "--version"], "bng_cpp")
        if bng_cpp is not None
        else "bng_cpp"
    )

    selected_rows = rows if rows else list(ROW_MODELS)
    unknown = [row_id for row_id in selected_rows if row_id not in ROW_MODELS]
    if unknown:
        raise ValueError(f"unmapped #471 BNG2 conformance row(s): {unknown}")

    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    emitted: list[str] = []
    model_cache: dict[
        str, tuple[bytes, bytes, bytes, dict[str, Any], dict[str, Any]]
    ] = {}

    for row_id in selected_rows:
        matrix_row = matrix_by_id.get(row_id)
        if matrix_row is None or matrix_row.get("status") != "implemented":
            raise ValueError(f"{row_id} is not an implemented matrix row")
        model_name = ROW_MODELS[row_id]
        if model_name not in model_cache:
            model_dir = conformance_dir / "models" / model_name
            inp_path = model_dir / "input" / f"{model_name}.bngl"
            ref_path = model_dir / "reference" / f"{model_name}.net"
            sub_path = model_dir / "subject" / f"{model_name}.net"
            sub_bngl_path = model_dir / "subject" / f"{model_name}.bngl"
            ref_cmd_path = model_dir / "reference" / "command.json"
            sub_cmd_path = model_dir / "subject" / "command.json"
            for req in (
                inp_path,
                ref_path,
                sub_path,
                sub_bngl_path,
                ref_cmd_path,
                sub_cmd_path,
            ):
                if not req.is_file():
                    raise ValueError(f"missing conformance artifact {req}")
            ref_cmd = json.loads(ref_cmd_path.read_text(encoding="utf-8"))
            sub_cmd = json.loads(sub_cmd_path.read_text(encoding="utf-8"))
            if ref_cmd.get("status") != "PASS" or ref_cmd.get("returncode") != 0:
                raise ValueError(f"{model_name} reference oracle command failed")
            if sub_cmd.get("status") != "PASS" or sub_cmd.get("returncode") != 0:
                raise ValueError(f"{model_name} consumer subject command failed")
            inp_bytes = inp_path.read_bytes()
            if sub_bngl_path.read_bytes() != inp_bytes:
                raise ValueError(
                    f"{model_name} subject input does not match producer bytes"
                )
            ref_net = compare.parse_net(ref_path)
            sub_net = compare.parse_net(sub_path)
            if ref_net is None or sub_net is None:
                raise ValueError(f"{model_name} .net output failed to parse")
            diff = compare.compare_net(ref_net, sub_net)
            if not diff.ok:
                raise ValueError(f"{model_name} .net parity failed: {diff.summary()}")
            model_cache[model_name] = (
                inp_bytes,
                ref_path.read_bytes(),
                sub_path.read_bytes(),
                ref_cmd,
                sub_cmd,
            )

        inp_bytes, ref_bytes, sub_bytes, ref_cmd, sub_cmd = model_cache[model_name]
        row_art_dir = artifacts_dir / row_id
        row_art_dir.mkdir(parents=True, exist_ok=True)
        producer_rel = f"{row_id}/producer.bngl"
        oracle_rel = f"{row_id}/oracle.net"
        consumer_rel = f"{row_id}/consumer.net"
        (artifacts_dir / producer_rel).write_bytes(inp_bytes)
        (artifacts_dir / oracle_rel).write_bytes(ref_bytes)
        (artifacts_dir / consumer_rel).write_bytes(sub_bytes)

        producer_sha = _sha256_bytes(inp_bytes)
        oracle_sha = _sha256_bytes(ref_bytes)
        consumer_sha = _sha256_bytes(sub_bytes)
        ref_cmd_str = _format_cmd(
            ref_cmd.get("command"), f"perl BNG2.pl {model_name}.bngl"
        )
        sub_cmd_str = _format_cmd(sub_cmd.get("command"), f"bng_cpp {model_name}.bngl")

        receipt = {
            "schema_version": 2,
            "kind": "release-oracle-consumer-receipt",
            "capability_id": row_id,
            "check_id": f"release-capability[{row_id}]",
            "comparator": "release-oracle-net-canonical-v1",
            "source_revision": revision,
            "product_revision": revision,
            "oracle": {
                "name": f"Pinned BNG2 ({model_name})",
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
                    "exit_code": int(ref_cmd["returncode"]),
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
                    "exit_code": int(sub_cmd["returncode"]),
                },
            },
        }
        (receipts_dir / f"{row_id}.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        emitted.append(row_id)

    return {
        "schema_version": 1,
        "source": {"revision": revision, "dirty": bool(dirty)},
        "oracle_revision": pinned_rev,
        "build_platform": build_platform,
        "emitted_rows": emitted,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--conformance-dir", type=Path, required=True)
    parser.add_argument("--bng2-root", type=Path, required=True)
    parser.add_argument("--bng-cpp", type=Path)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--row", action="append", default=[])
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    summary = build_bng2_receipts(
        root=args.root.resolve(),
        revision=args.revision,
        conformance_dir=args.conformance_dir.resolve(),
        bng2_root=args.bng2_root.resolve(),
        receipts_dir=args.receipts_dir.resolve(),
        artifacts_dir=args.artifacts_dir.resolve(),
        bng_cpp=args.bng_cpp.resolve() if args.bng_cpp else None,
        rows=args.row or None,
        allow_dirty=args.allow_dirty,
    )
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"Emitted {len(summary['emitted_rows'])} #471 BNG2 receipt(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
