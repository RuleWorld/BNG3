#!/usr/bin/env python3
"""Emit schema-v2 #471/#180 differential receipts against pinned native NFsim.

Runs pinned native ``NFsim`` (external oracle) and BNG3 ``NFsim`` (downstream
consumer) on deterministic CLI option probes using the pinned NFsim
``test/Issue51/issue51.xml`` input, and emits byte-verified schema-v2 receipts
ONLY for ``nf.option.*`` rows where oracle and consumer outputs agree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class NfsimOptionProbe:
    row_id: str
    kind: str  # "gdat" or "cli"
    flags: tuple[str, ...]
    sim_time: str = "1"
    o_steps: str = "1"
    seed: str = "1"
    extra_check: str = ""


# Deterministic probes on test/Issue51/issue51.xml (1 molecule of A(b1,b2) with
# intramolecular binding blocked under -cb/-bscb and allowed under -no-bscb).
OPTION_PROBES: tuple[NfsimOptionProbe, ...] = (
    NfsimOptionProbe("nf.option.xml", "gdat", ()),
    NfsimOptionProbe("nf.option.o", "gdat", ()),
    NfsimOptionProbe("nf.option.sim", "gdat", ()),
    NfsimOptionProbe("nf.option.oSteps", "gdat", (), o_steps="2"),
    NfsimOptionProbe("nf.option.seed", "gdat", (), seed="7"),
    NfsimOptionProbe("nf.option.cb", "gdat", ("-cb",)),
    NfsimOptionProbe("nf.option.bscb", "gdat", ("-bscb",)),
    NfsimOptionProbe("nf.option.no-bscb", "gdat", ("-no-bscb",)),
    NfsimOptionProbe("nf.option.nocslf", "gdat", ("-nocslf",)),
    NfsimOptionProbe("nf.option.notf", "gdat", ("-notf",)),
    NfsimOptionProbe("nf.option.utl", "gdat", ("-utl", "3")),
    NfsimOptionProbe("nf.option.gml", "gdat", ("-gml", "1000")),
    NfsimOptionProbe("nf.option.eq", "gdat", ("-eq", "0.5")),
    NfsimOptionProbe("nf.option.v", "gdat", ("-v",)),
    NfsimOptionProbe("nf.option.b", "gdat", ("-b",)),
    NfsimOptionProbe("nf.option.oec", "gdat", ("-oec",)),
    NfsimOptionProbe("nf.option.ogf", "gdat", ("-ogf",)),
    NfsimOptionProbe("nf.option.connect", "gdat", ("-connect",)),
    NfsimOptionProbe("nf.option.csv", "gdat", ("-csv",)),
    NfsimOptionProbe("nf.option.oTimes", "gdat", ("-oTimes", "0,0.5,1"), o_steps=""),
    NfsimOptionProbe("nf.option.h", "cli", ("-h",), extra_check="help"),
    NfsimOptionProbe("nf.option.help", "cli", ("-help",), extra_check="help"),
    NfsimOptionProbe("nf.option.version", "cli", ("-version",), extra_check="version"),
    NfsimOptionProbe("nf.option.logo", "cli", ("-logo",), extra_check="logo"),
    NfsimOptionProbe("nf.option.ss", "cli", ("-ss", "final.species"), extra_check="ss"),
)


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


def _version_line(binary: Path) -> str:
    proc = subprocess.run(
        [str(binary), "-version"], capture_output=True, text=True, check=False
    )
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0] if text else "NFsim"


def _run_probe(
    binary: Path, probe: NfsimOptionProbe, xml_path: Path, work_dir: Path
) -> tuple[int, list[str], bytes | None]:
    work_dir.mkdir(parents=True, exist_ok=True)
    if probe.kind == "cli" and probe.extra_check in {"help", "version", "logo"}:
        cmd = [str(binary), *probe.flags]
        proc = subprocess.run(
            cmd, cwd=work_dir, capture_output=True, text=True, timeout=30, check=False
        )
        combined = proc.stdout + proc.stderr
        if probe.extra_check == "help":
            marker_ok = "To run NFsim" in combined or "usage" in combined.lower()
        elif probe.extra_check == "version":
            marker_ok = "nfsim" in combined.lower() or "version" in combined.lower()
        else:
            marker_ok = len(combined.strip()) > 0
        payload = {
            "row_id": probe.row_id,
            "returncode": proc.returncode,
            "marker_ok": marker_ok,
        }
        return (
            proc.returncode,
            cmd,
            (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )

    out_gdat = work_dir / "out.gdat"
    cmd = [str(binary), "-xml", str(xml_path), "-o", str(out_gdat)]
    if probe.sim_time:
        cmd.extend(["-sim", probe.sim_time])
    if probe.o_steps:
        cmd.extend(["-oSteps", probe.o_steps])
    if probe.seed:
        cmd.extend(["-seed", probe.seed])
    cmd.extend(probe.flags)
    proc = subprocess.run(
        cmd, cwd=work_dir, capture_output=True, text=True, timeout=30, check=False
    )
    if proc.returncode != 0 or not out_gdat.is_file():
        return proc.returncode, cmd, None

    if probe.extra_check == "ss":
        ss_file = work_dir / "final.species"
        payload = {
            "row_id": probe.row_id,
            "returncode": proc.returncode,
            "gdat_exists": out_gdat.is_file(),
            "species_exists": ss_file.is_file() and ss_file.stat().st_size > 0,
        }
        return (
            proc.returncode,
            cmd,
            (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )

    return proc.returncode, cmd, out_gdat.read_bytes()


def build_nfsim_receipts(
    *,
    root: Path,
    revision: str,
    nfsim_source: Path,
    nfsim_oracle: Path,
    nfsim_candidate: Path,
    receipts_dir: Path,
    artifacts_dir: Path,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    head = _git_head(root)
    if head != revision or (_git_dirty(root) and not allow_dirty):
        raise ValueError(
            "issue #471 NFsim receipts require the requested clean revision"
        )
    lock = json.loads((root / "provenance/upstreams.lock.yml").read_text("utf-8"))
    pinned_rev = str(lock["sources"]["nfsim"]["revision"])
    actual_rev = _git_head(nfsim_source)
    if actual_rev != pinned_rev:
        raise ValueError(f"NFsim oracle revision {actual_rev} != locked {pinned_rev}")
    if _git_dirty(nfsim_source, ignore_untracked=True):
        raise ValueError("NFsim oracle source checkout has tracked modifications")
    if not nfsim_oracle.is_file():
        raise ValueError(f"missing pinned NFsim oracle binary: {nfsim_oracle}")
    if not nfsim_candidate.is_file():
        raise ValueError(f"missing BNG3 NFsim candidate binary: {nfsim_candidate}")

    xml_src = nfsim_source / "test" / "Issue51" / "issue51.xml"
    if not xml_src.is_file():
        raise ValueError(f"missing pinned NFsim fixture: {xml_src}")
    xml_bytes = xml_src.read_bytes()

    matrix = json.loads((root / "provenance/capability-matrix.yml").read_text("utf-8"))
    matrix_ids = {row["id"] for row in matrix.get("rows", [])}

    case_dir = root / "tests/validation/release/cases/issue-471"
    for entry in (str(root), str(case_dir)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    import issue471_checks as checks  # noqa: E402

    oracle_exe_sha = _sha256_bytes(nfsim_oracle.read_bytes())
    oracle_version = _version_line(nfsim_oracle)
    candidate_version = _version_line(nfsim_candidate)
    build_platform = _build_platform()

    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    emitted: list[str] = []
    skipped: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        xml_copy = td_path / "issue51.xml"
        xml_copy.write_bytes(xml_bytes)

        for probe in OPTION_PROBES:
            if probe.row_id not in matrix_ids:
                continue
            o_rc, o_cmd, o_bytes = _run_probe(
                nfsim_oracle, probe, xml_copy, td_path / probe.row_id / "oracle"
            )
            c_rc, c_cmd, c_bytes = _run_probe(
                nfsim_candidate, probe, xml_copy, td_path / probe.row_id / "consumer"
            )
            if o_rc != 0 or c_rc != 0 or o_bytes is None or c_bytes is None:
                skipped.append(
                    {
                        "id": probe.row_id,
                        "reason": "nonzero_exit_or_missing_output",
                        "oracle_rc": o_rc,
                        "consumer_rc": c_rc,
                    }
                )
                continue

            if probe.kind == "gdat" and probe.row_id != "nf.option.csv":
                comparator = "release-oracle-gdat-numeric-v1"
                ok, detail = checks._compare_gdat_bytes(o_bytes, c_bytes)
                ext = "gdat"
            else:
                comparator = "release-oracle-byte-equality-v1"
                ok = o_bytes == c_bytes
                detail = "" if ok else "byte output differs"
                ext = "csv" if probe.row_id == "nf.option.csv" else "json"

            if not ok:
                skipped.append(
                    {
                        "id": probe.row_id,
                        "reason": "comparator_mismatch",
                        "detail": detail,
                    }
                )
                continue

            row_art_dir = artifacts_dir / probe.row_id
            row_art_dir.mkdir(parents=True, exist_ok=True)
            producer_rel = f"{probe.row_id}/producer.xml"
            oracle_rel = f"{probe.row_id}/oracle.{ext}"
            consumer_rel = f"{probe.row_id}/consumer.{ext}"
            (artifacts_dir / producer_rel).write_bytes(xml_bytes)
            (artifacts_dir / oracle_rel).write_bytes(o_bytes)
            (artifacts_dir / consumer_rel).write_bytes(c_bytes)

            producer_sha = _sha256_bytes(xml_bytes)
            oracle_sha = _sha256_bytes(o_bytes)
            consumer_sha = _sha256_bytes(c_bytes)
            o_cmd_str = " ".join(o_cmd)
            c_cmd_str = " ".join(c_cmd)

            receipt = {
                "schema_version": 2,
                "kind": "release-oracle-consumer-receipt",
                "capability_id": probe.row_id,
                "check_id": f"release-capability[{probe.row_id}]",
                "comparator": comparator,
                "source_revision": revision,
                "product_revision": revision,
                "oracle": {
                    "name": f"Pinned native NFsim ({probe.row_id})",
                    "source_id": "nfsim",
                    "revision": pinned_rev,
                    "build_platform": build_platform,
                    "source_clean": True,
                    "path": oracle_rel,
                    "artifact_sha256": oracle_sha,
                    "executable_sha256": oracle_exe_sha,
                    "command": o_cmd_str,
                    "expected_origin": "external-source",
                    "execution": {
                        "executable": "NFsim",
                        "version": oracle_version,
                        "command": o_cmd_str,
                        "exit_code": o_rc,
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
                        "executable": "NFsim",
                        "version": candidate_version,
                        "command": c_cmd_str,
                        "exit_code": c_rc,
                    },
                },
            }
            (receipts_dir / f"{probe.row_id}.json").write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            emitted.append(probe.row_id)

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
    parser.add_argument("--nfsim-source", type=Path, required=True)
    parser.add_argument("--nfsim-oracle", type=Path, required=True)
    parser.add_argument("--nfsim-candidate", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    summary = build_nfsim_receipts(
        root=args.root.resolve(),
        revision=args.revision,
        nfsim_source=args.nfsim_source.resolve(),
        nfsim_oracle=args.nfsim_oracle.resolve(),
        nfsim_candidate=args.nfsim_candidate.resolve(),
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
        f"Emitted {summary['emitted_count']} NFsim #471/#180 receipts "
        f"({summary['skipped_count']} skipped) for {summary['source_revision'][:8]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
