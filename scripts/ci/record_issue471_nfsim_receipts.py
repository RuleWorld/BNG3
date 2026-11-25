#!/usr/bin/env python3
"""Emit schema-v2 #471/#180 differential receipts against pinned native NFsim.

Runs pinned native ``NFsim`` (external oracle) and the installed ``bionetgen``
package (``simulate_nf`` direct/compiled NFsim path, downstream consumer) on
deterministic option probes using the pinned NFsim ``test/Issue51/issue51``
input, and emits verified schema-v2 receipts ONLY for ``nf.option.*`` rows
where oracle and consumer outputs agree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
    oracle_flags: tuple[str, ...]
    bngl_options: str = ""
    n_steps: str = "1"
    seed: str = "1"
    binary_output: bool = False


# Deterministic probes on pinned test/Issue51/issue51.{bngl,xml} (1 molecule
# complex A(x,z!1).B(y,w!1) where intramolecular binding is blocked under
# -cb/-bscb and allowed under -no-bscb).
OPTION_PROBES: tuple[NfsimOptionProbe, ...] = (
    NfsimOptionProbe("nf.option.o", ()),
    NfsimOptionProbe("nf.option.sim", ()),
    NfsimOptionProbe("nf.option.oSteps", (), n_steps="2"),
    NfsimOptionProbe("nf.option.seed", (), seed="7"),
    NfsimOptionProbe("nf.option.cb", ("-cb",), ",complex=>1"),
    NfsimOptionProbe("nf.option.bscb", ("-bscb",), ',param=>"-bscb"'),
    NfsimOptionProbe("nf.option.no-bscb", ("-no-bscb",), ',param=>"-no-bscb"'),
    NfsimOptionProbe("nf.option.nocslf", ("-nocslf",), ',param=>"-nocslf"'),
    NfsimOptionProbe("nf.option.notf", ("-notf",), ',param=>"-notf"'),
    NfsimOptionProbe("nf.option.utl", ("-utl", "3"), ",utl=>3"),
    NfsimOptionProbe("nf.option.gml", ("-gml", "1000"), ",gml=>1000"),
    NfsimOptionProbe("nf.option.eq", ("-eq", "0.5"), ',param=>"-eq 0.5"'),
    NfsimOptionProbe("nf.option.v", ("-v",), ',param=>"-v"'),
    NfsimOptionProbe("nf.option.b", ("-b",), ',param=>"-b"', binary_output=True),
    NfsimOptionProbe("nf.option.ogf", ("-ogf",), ',param=>"-ogf"'),
    NfsimOptionProbe("nf.option.connect", ("-connect",), ',param=>"-connect"'),
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


def _run_oracle(
    binary: Path, probe: NfsimOptionProbe, xml_path: Path, work_dir: Path
) -> tuple[int, list[str], bytes | None]:
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / "oracle.gdat"
    cmd = [
        str(binary),
        "-xml",
        str(xml_path),
        "-o",
        str(out_path),
        "-sim",
        "1",
        "-oSteps",
        probe.n_steps,
        "-seed",
        probe.seed,
        *probe.oracle_flags,
    ]
    proc = subprocess.run(
        cmd, cwd=work_dir, capture_output=True, text=True, timeout=30, check=False
    )
    if proc.returncode != 0 or not out_path.is_file():
        return proc.returncode, cmd, None
    return proc.returncode, cmd, out_path.read_bytes()


def _run_consumer(
    probe: NfsimOptionProbe, model_part: str, work_dir: Path
) -> tuple[int, list[str], bytes | None, str]:
    work_dir.mkdir(parents=True, exist_ok=True)
    src = work_dir / "consumer.bngl"
    src.write_text(
        model_part
        + "begin actions\n"
        + f'simulate_nf({{prefix=>"consumer",t_end=>1,n_steps=>{probe.n_steps},'
        + f"seed=>{probe.seed}{probe.bngl_options}}})\n"
        + "end actions\n",
        encoding="utf-8",
    )
    code = "import sys, bionetgen; " "bionetgen.load(sys.argv[1]).execute()"
    cmd = [sys.executable, "-c", code, str(src)]
    env = dict(os.environ)
    env["BNG_NFSIM_REQUIRE_DIRECT"] = "1"
    proc = subprocess.run(
        cmd,
        cwd=work_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    out_path = work_dir / "consumer.gdat"
    if proc.returncode != 0 or not out_path.is_file():
        return proc.returncode, cmd, None, (proc.stderr or proc.stdout).strip()
    return proc.returncode, cmd, out_path.read_bytes(), ""


def build_nfsim_receipts(
    *,
    root: Path,
    revision: str,
    nfsim_source: Path,
    nfsim_oracle: Path,
    receipts_dir: Path,
    artifacts_dir: Path,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.ci.oracle_sources import load_lock, load_oracle_source
    import importlib.util

    checks_path = root / "tests/validation/release/cases/issue-471/issue471_checks.py"
    spec = importlib.util.spec_from_file_location("issue471_checks", checks_path)
    assert spec is not None and spec.loader is not None
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)

    lock = load_lock()
    pinned = load_oracle_source(lock, "nfsim")
    pinned_rev = str(pinned["revision"])
    actual_rev = _git_head(nfsim_source)
    if actual_rev != pinned_rev:
        raise RuntimeError(
            f"NFsim checkout revision mismatch: {actual_rev} != {pinned_rev}"
        )
    if not allow_dirty and _git_dirty(nfsim_source, ignore_untracked=True):
        raise RuntimeError(f"NFsim checkout has tracked modifications: {nfsim_source}")
    if not nfsim_oracle.is_file():
        raise RuntimeError(f"NFsim oracle binary missing: {nfsim_oracle}")

    bng_version = subprocess.check_output(
        [sys.executable, "-c", "import bionetgen; print(bionetgen.__version__)"],
        text=True,
    ).strip()

    xml_src = nfsim_source / "test/Issue51/issue51.xml"
    bngl_src = nfsim_source / "test/Issue51/issue51.bngl"
    if not xml_src.is_file() or not bngl_src.is_file():
        raise RuntimeError(f"Pinned NFsim probe fixtures missing under {nfsim_source}")
    xml_bytes = xml_src.read_bytes()
    bngl_text = bngl_src.read_text(encoding="utf-8")
    model_part, actions_marker, _ = bngl_text.partition("begin actions")
    if not actions_marker:
        raise RuntimeError("Pinned issue51.bngl missing actions block")

    matrix = json.loads(
        (root / "provenance/capability-matrix.yml").read_text(encoding="utf-8")
    )
    matrix_ids = {
        str(row["id"])
        for row in matrix.get("rows", [])
        if str(row.get("upstream", "")).startswith("nfsim:")
    }

    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    build_platform = _build_platform()
    oracle_exe_sha = _sha256_bytes(nfsim_oracle.read_bytes())
    oracle_version = _version_line(nfsim_oracle)

    emitted: list[str] = []
    skipped: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="bng3-471-nfsim-") as td:
        td_path = Path(td)
        xml_copy = td_path / "issue51.xml"
        xml_copy.write_bytes(xml_bytes)

        for probe in OPTION_PROBES:
            if probe.row_id not in matrix_ids:
                continue
            o_rc, o_cmd, o_bytes = _run_oracle(
                nfsim_oracle, probe, xml_copy, td_path / probe.row_id / "oracle"
            )
            c_rc, c_cmd, c_bytes, c_err = _run_consumer(
                probe, model_part, td_path / probe.row_id / "consumer"
            )
            if o_rc != 0 or c_rc != 0 or o_bytes is None or c_bytes is None:
                skipped.append(
                    {
                        "id": probe.row_id,
                        "reason": "nonzero_exit_or_missing_output",
                        "oracle_rc": o_rc,
                        "consumer_rc": c_rc,
                        "detail": c_err[:200],
                    }
                )
                continue

            if probe.binary_output:
                comparator = "release-oracle-byte-equality-v1"
                ok = o_bytes == c_bytes
                detail = "" if ok else "binary gdat output differs"
                ext = "bin"
            else:
                comparator = "release-oracle-gdat-numeric-v1"
                ok, detail = checks._compare_gdat_bytes(o_bytes, c_bytes)
                ext = "gdat"

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
                        "executable": "bionetgen",
                        "version": bng_version,
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
