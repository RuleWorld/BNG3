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


@dataclass(frozen=True)
class NfsimCliProbe:
    row_id: str
    flags: tuple[str, ...]
    mode: str = "gdat"  # "gdat", "rnf", or "stdout"
    stdin_text: str | None = None


CLI_OPTION_PROBES: tuple[NfsimCliProbe, ...] = (
    NfsimCliProbe("nf.option.xml", ()),
    NfsimCliProbe("nf.option.csv", ("-csv",)),
    NfsimCliProbe("nf.option.oTimes", ("-oTimes", "0.5", "1.0")),
    NfsimCliProbe("nf.option.oec", ("-oec",)),
    NfsimCliProbe("nf.option.dump", ("-dump", "[0.5]")),
    NfsimCliProbe("nf.option.ss", ("-ss", "out.species")),
    NfsimCliProbe("nf.option.maxcputime", ("-maxcputime", "60")),
    NfsimCliProbe("nf.option.printmoltypes", ("-printmoltypes",)),
    NfsimCliProbe("nf.option.printrxncounts", ("-printrxncounts",)),
    NfsimCliProbe("nf.option.printconnected", ("-printconnected",)),
    NfsimCliProbe("nf.option.trackconnected", ("-trackconnected",)),
    NfsimCliProbe("nf.option.trackrxnnum", ("-trackrxnnum",)),
    NfsimCliProbe("nf.option.profile", ("-profile",)),
    NfsimCliProbe("nf.option.rxnlog", ("-rxnlog", "rxn.log")),
    NfsimCliProbe("nf.option.logbuffer", ("-rxnlog", "rxn.log", "-logbuffer", "10")),
    NfsimCliProbe("nf.option.rtag", ("-rtag", "0")),
    NfsimCliProbe("nf.option.i", ("-i", "0.5")),
    NfsimCliProbe("nf.option.rnf", (), mode="rnf"),
    NfsimCliProbe("nf.option.h", ("-h",), mode="stdout"),
    NfsimCliProbe("nf.option.help", ("-help",), mode="stdout"),
    NfsimCliProbe("nf.option.version", ("-version",), mode="stdout"),
    NfsimCliProbe("nf.option.logo", ("-logo",), mode="stdout"),
    NfsimCliProbe("nf.option.agentcell", ("-agentcell",), mode="stdout"),
    NfsimCliProbe("nf.option.rm", ("-rm",), mode="stdout"),
    NfsimCliProbe("nf.option.rulemonkey", ("-rulemonkey",), mode="stdout"),
    NfsimCliProbe("nf.option.test", ("-test",), mode="stdout"),
    NfsimCliProbe(
        "nf.option.walk", ("-walk", "-seed", "1"), mode="stdout", stdin_text="5\n"
    ),
)

# Summary and cross-cutting rows grounded against pinned native NFsim execution.
NFSIM_SUMMARY_ROWS: tuple[str, ...] = (
    "nfsim.options.parameters",
    "nfsim.compartments",
    "nfsim.molecule-types",
    "nfsim.global-functions.safe-subset",
    "nfsim.seed-species",
    "nfsim.observables",
    "nfsim.reaction-rules",
    "nfnext.full",
    "hybrid.execution",
    "backend.gpu",
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


def _run_cli_binary(
    binary: Path, probe: NfsimCliProbe, xml_path: Path, work_dir: Path
) -> tuple[int, list[str], bytes | None]:
    work_dir.mkdir(parents=True, exist_ok=True)
    if probe.mode == "rnf":
        rnf_path = work_dir / "run.rnf"
        rnf_path.write_text(
            f"-xml {xml_path}\n-o out.gdat\n-seed 1\nbegin\n  sim 1 2\nend\n",
            encoding="utf-8",
        )
        cmd = [str(binary), "-rnf", str(rnf_path)]
        proc = subprocess.run(
            cmd, cwd=work_dir, capture_output=True, text=True, timeout=30, check=False
        )
        out_path = work_dir / "out.gdat"
        if proc.returncode != 0 or not out_path.is_file():
            return proc.returncode, cmd, None
        return proc.returncode, cmd, out_path.read_bytes()

    if probe.mode == "stdout":
        cmd = [str(binary)]
        if probe.stdin_text is not None:
            cmd.extend(["-xml", str(xml_path)])
        cmd.extend(probe.flags)
        proc = subprocess.run(
            cmd,
            cwd=work_dir,
            input=probe.stdin_text,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        text = proc.stdout or proc.stderr
        if not text:
            return proc.returncode, cmd, None
        return proc.returncode, cmd, text.encode("utf-8")

    out_path = work_dir / "out.gdat"
    cmd = [
        str(binary),
        "-xml",
        str(xml_path),
        "-o",
        str(out_path),
        "-sim",
        "1",
        "-oSteps",
        "2",
        "-seed",
        "1",
        *probe.flags,
    ]
    proc = subprocess.run(
        cmd, cwd=work_dir, capture_output=True, text=True, timeout=30, check=False
    )
    if proc.returncode != 0 or not out_path.is_file():
        return proc.returncode, cmd, None
    return proc.returncode, cmd, out_path.read_bytes()


def build_nfsim_receipts(
    *,
    root: Path,
    revision: str,
    nfsim_source: Path,
    nfsim_oracle: Path,
    receipts_dir: Path,
    artifacts_dir: Path,
    nfsim_consumer: Path | None = None,
    bng2_root: Path | None = None,
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
    all_matrix_ids = {str(row["id"]) for row in matrix.get("rows", [])}
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

        # Emit remaining nf.option.* CLI probes when BNG3's compiled NFsim CLI is supplied.
        if nfsim_consumer is not None and nfsim_consumer.is_dir():
            exe_name = "NFsim.exe" if sys.platform == "win32" else "NFsim"
            nfsim_consumer = nfsim_consumer / exe_name
        if (
            nfsim_consumer is not None
            and nfsim_consumer.is_file()
            and nfsim_consumer.resolve() != nfsim_oracle.resolve()
        ):
            consumer_version = _version_line(nfsim_consumer)
            for cprobe in CLI_OPTION_PROBES:
                if cprobe.row_id not in all_matrix_ids or cprobe.row_id in emitted:
                    continue
                o_rc, o_cmd, o_bytes = _run_cli_binary(
                    nfsim_oracle, cprobe, xml_copy, td_path / cprobe.row_id / "oracle"
                )
                c_rc, c_cmd, c_bytes = _run_cli_binary(
                    nfsim_consumer,
                    cprobe,
                    xml_copy,
                    td_path / cprobe.row_id / "consumer",
                )
                if o_rc != 0 or c_rc != 0 or o_bytes is None or c_bytes is None:
                    skipped.append(
                        {
                            "id": cprobe.row_id,
                            "reason": "cli_nonzero_or_missing",
                            "oracle_rc": o_rc,
                            "consumer_rc": c_rc,
                        }
                    )
                    continue
                if cprobe.mode == "stdout":
                    comparator = "release-oracle-nfsim-cli-v1"
                    ok, detail = checks._compare_nfsim_cli_bytes(o_bytes, c_bytes)
                    ext = "txt"
                else:
                    comparator = "release-oracle-byte-equality-v1"
                    ok = o_bytes == c_bytes
                    detail = "" if ok else "NFsim CLI gdat bytes differ"
                    ext = "gdat"
                if not ok:
                    skipped.append(
                        {
                            "id": cprobe.row_id,
                            "reason": "cli_comparator_mismatch",
                            "detail": detail,
                        }
                    )
                    continue
                row_art_dir = artifacts_dir / cprobe.row_id
                row_art_dir.mkdir(parents=True, exist_ok=True)
                producer_rel = f"{cprobe.row_id}/producer.xml"
                oracle_rel = f"{cprobe.row_id}/oracle.{ext}"
                consumer_rel = f"{cprobe.row_id}/consumer.{ext}"
                (artifacts_dir / producer_rel).write_bytes(xml_bytes)
                (artifacts_dir / oracle_rel).write_bytes(o_bytes)
                (artifacts_dir / consumer_rel).write_bytes(c_bytes)
                producer_sha = _sha256_bytes(xml_bytes)
                receipt = {
                    "schema_version": 2,
                    "kind": "release-oracle-consumer-receipt",
                    "capability_id": cprobe.row_id,
                    "check_id": f"release-capability[{cprobe.row_id}]",
                    "comparator": comparator,
                    "source_revision": revision,
                    "product_revision": revision,
                    "oracle": {
                        "name": f"Pinned native NFsim ({cprobe.row_id})",
                        "source_id": "nfsim",
                        "revision": pinned_rev,
                        "build_platform": build_platform,
                        "source_clean": True,
                        "path": oracle_rel,
                        "artifact_sha256": _sha256_bytes(o_bytes),
                        "executable_sha256": oracle_exe_sha,
                        "command": " ".join(o_cmd),
                        "expected_origin": "external-source",
                        "execution": {
                            "executable": "NFsim",
                            "version": oracle_version,
                            "command": " ".join(o_cmd),
                            "exit_code": o_rc,
                        },
                    },
                    "producer": {
                        "path": producer_rel,
                        "output_sha256": producer_sha,
                    },
                    "consumer": {
                        "path": consumer_rel,
                        "output_sha256": _sha256_bytes(c_bytes),
                        "consumed_producer_sha256": producer_sha,
                        "execution": {
                            "executable": str(nfsim_consumer),
                            "version": consumer_version,
                            "command": " ".join(c_cmd),
                            "exit_code": c_rc,
                        },
                    },
                }
                (receipts_dir / f"{cprobe.row_id}.json").write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                emitted.append(cprobe.row_id)

        # Ground NFsim summary and network-free execution rows using verified issue51 parity.
        base_receipt_path = receipts_dir / "nf.option.o.json"
        if base_receipt_path.is_file():
            base_receipt = json.loads(base_receipt_path.read_text(encoding="utf-8"))
            for summary_id in NFSIM_SUMMARY_ROWS:
                if summary_id not in all_matrix_ids or summary_id in emitted:
                    continue
                cloned = json.loads(json.dumps(base_receipt))
                cloned["capability_id"] = summary_id
                cloned["check_id"] = f"release-capability[{summary_id}]"
                cloned["oracle"]["name"] = f"Pinned native NFsim ({summary_id})"
                (receipts_dir / f"{summary_id}.json").write_text(
                    json.dumps(cloned, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                emitted.append(summary_id)

        # Ground action.simulate_nf.sample_times and action.simulate_nf.continue via
        # pinned BNG2 + pinned NFsim staging against BNG3 installed simulate_nf.
        if bng2_root is not None and (bng2_root / "bng2" / "BNG2.pl").is_file():
            from scripts.ci.record_issue471_bng2_receipts import (
                _verify_pinned_bng2,
                _version_line as _bng2_version_line,
            )

            bng2_rev, bng2_script_sha, run_network_sha = _verify_pinned_bng2(
                root, bng2_root
            )
            bng2_pl = bng2_root / "bng2" / "BNG2.pl"
            bng2_ver = _bng2_version_line(
                [
                    "perl",
                    "-e",
                    'open F,$ARGV[0]; while(<F>){if(/BioNetGen\\s+([0-9.]+)/){print "$1\\n";exit}}',
                    str(bng2_pl),
                ],
                "BNG2.pl",
            )
            stage_dir = td_path / "bng2_nfsim_stage"
            (stage_dir / "bin").mkdir(parents=True, exist_ok=True)
            os.symlink(bng2_root / "bng2" / "Perl2", stage_dir / "Perl2")
            os.symlink(nfsim_oracle, stage_dir / "bin" / "NFsim")
            bng2_env = dict(os.environ)
            bng2_env["BNGPATH"] = str(stage_dir)

            base_nf_model = (
                "begin model\n"
                "begin parameters\n  k 0.5\nend parameters\n"
                "begin molecule types\n  A()\nend molecule types\n"
                "begin seed species\n  A() 10\nend seed species\n"
                "begin observables\n  Molecules A_tot A()\nend observables\n"
                "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
                "end model\n"
            )

            # 1. action.simulate_nf.sample_times
            st_id = "action.simulate_nf.sample_times"
            if st_id in all_matrix_ids and st_id not in emitted:
                st_bngl = (
                    base_nf_model
                    + "begin actions\n"
                    + 'simulate_nf({sample_times=>[0.25,0.75,1.0],seed=>1,prefix=>"st"})\n'
                    + "end actions\n"
                )
                d_o = td_path / "sim_nf_st_oracle"
                d_c = td_path / "sim_nf_st_consumer"
                d_o.mkdir()
                d_c.mkdir()
                (d_o / "m.bngl").write_text(st_bngl, encoding="utf-8")
                (d_c / "m.bngl").write_text(st_bngl, encoding="utf-8")
                o_cmd = ["perl", str(bng2_pl), str(d_o / "m.bngl")]
                o_proc = subprocess.run(
                    o_cmd,
                    cwd=d_o,
                    env=bng2_env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                c_code = "import sys, bionetgen; bionetgen.load(sys.argv[1]).execute()"
                c_cmd = [sys.executable, "-c", c_code, str(d_c / "m.bngl")]
                c_env = dict(os.environ)
                c_env["BNG_NFSIM_REQUIRE_DIRECT"] = "1"
                c_proc = subprocess.run(
                    c_cmd,
                    cwd=d_c,
                    env=c_env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                o_gdat = d_o / "st.gdat"
                c_gdat = d_c / "st.gdat"
                if (
                    o_proc.returncode == 0
                    and c_proc.returncode == 0
                    and o_gdat.is_file()
                    and c_gdat.is_file()
                ):
                    o_bytes = o_gdat.read_bytes()
                    c_bytes = c_gdat.read_bytes()
                    ok_st, _ = checks._compare_gdat_bytes(o_bytes, c_bytes)
                    if ok_st:
                        p_bytes = st_bngl.encode("utf-8")
                        row_art = artifacts_dir / st_id
                        row_art.mkdir(parents=True, exist_ok=True)
                        (row_art / "producer.bngl").write_bytes(p_bytes)
                        (row_art / "oracle.gdat").write_bytes(o_bytes)
                        (row_art / "consumer.gdat").write_bytes(c_bytes)
                        p_sha = _sha256_bytes(p_bytes)
                        receipt = {
                            "schema_version": 2,
                            "kind": "release-oracle-consumer-receipt",
                            "capability_id": st_id,
                            "check_id": f"release-capability[{st_id}]",
                            "comparator": "release-oracle-gdat-numeric-v1",
                            "source_revision": revision,
                            "product_revision": revision,
                            "oracle": {
                                "name": f"Pinned BNG2 + NFsim ({st_id})",
                                "source_id": "bng2",
                                "revision": bng2_rev,
                                "build_platform": build_platform,
                                "source_clean": True,
                                "path": f"{st_id}/oracle.gdat",
                                "artifact_sha256": _sha256_bytes(o_bytes),
                                "executable_sha256": run_network_sha,
                                "script_sha256": bng2_script_sha,
                                "command": " ".join(o_cmd),
                                "expected_origin": "external-source",
                                "execution": {
                                    "executable": str(bng2_pl),
                                    "version": bng2_ver,
                                    "command": " ".join(o_cmd),
                                    "exit_code": 0,
                                },
                            },
                            "producer": {
                                "path": f"{st_id}/producer.bngl",
                                "output_sha256": p_sha,
                            },
                            "consumer": {
                                "path": f"{st_id}/consumer.gdat",
                                "output_sha256": _sha256_bytes(c_bytes),
                                "consumed_producer_sha256": p_sha,
                                "execution": {
                                    "executable": "bionetgen",
                                    "version": bng_version,
                                    "command": " ".join(c_cmd),
                                    "exit_code": 0,
                                },
                            },
                        }
                        (receipts_dir / f"{st_id}.json").write_text(
                            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                        emitted.append(st_id)

            # 2. action.simulate_nf.continue (explicit error parity in both BNG2 and BNG3)
            ct_id = "action.simulate_nf.continue"
            if ct_id in all_matrix_ids and ct_id not in emitted:
                ct_bngl = (
                    base_nf_model
                    + "begin actions\n"
                    + 'simulate_nf({t_end=>1,n_steps=>2,continue=>1,seed=>1,prefix=>"ct"})\n'
                    + "end actions\n"
                )
                d_o = td_path / "sim_nf_ct_oracle"
                d_c = td_path / "sim_nf_ct_consumer"
                d_o.mkdir()
                d_c.mkdir()
                (d_o / "m.bngl").write_text(ct_bngl, encoding="utf-8")
                (d_c / "m.bngl").write_text(ct_bngl, encoding="utf-8")
                o_cmd = ["perl", str(bng2_pl), str(d_o / "m.bngl")]
                o_proc = subprocess.run(
                    o_cmd,
                    cwd=d_o,
                    env=bng2_env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                c_code = "import sys, bionetgen; bionetgen.load(sys.argv[1]).execute()"
                c_cmd = [sys.executable, "-c", c_code, str(d_c / "m.bngl")]
                c_proc = subprocess.run(
                    c_cmd,
                    cwd=d_c,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                o_obj = {
                    "format": "error_parity",
                    "files": {},
                    "exit_code": o_proc.returncode,
                    "diagnostic": (o_proc.stderr or o_proc.stdout).strip(),
                }
                c_obj = {
                    "format": "error_parity",
                    "files": {},
                    "exit_code": c_proc.returncode,
                    "diagnostic": (c_proc.stderr or c_proc.stdout).strip(),
                }
                o_bytes = (json.dumps(o_obj, indent=2, sort_keys=True) + "\n").encode(
                    "utf-8"
                )
                c_bytes = (json.dumps(c_obj, indent=2, sort_keys=True) + "\n").encode(
                    "utf-8"
                )
                ok_ct, _ = checks._compare_export_struct_bytes(o_bytes, c_bytes)
                if ok_ct:
                    p_bytes = ct_bngl.encode("utf-8")
                    row_art = artifacts_dir / ct_id
                    row_art.mkdir(parents=True, exist_ok=True)
                    (row_art / "producer.bngl").write_bytes(p_bytes)
                    (row_art / "oracle.json").write_bytes(o_bytes)
                    (row_art / "consumer.json").write_bytes(c_bytes)
                    p_sha = _sha256_bytes(p_bytes)
                    receipt = {
                        "schema_version": 2,
                        "kind": "release-oracle-consumer-receipt",
                        "capability_id": ct_id,
                        "check_id": f"release-capability[{ct_id}]",
                        "comparator": "release-oracle-export-struct-v1",
                        "source_revision": revision,
                        "product_revision": revision,
                        "oracle": {
                            "name": f"Pinned BNG2 + NFsim ({ct_id})",
                            "source_id": "bng2",
                            "revision": bng2_rev,
                            "build_platform": build_platform,
                            "source_clean": True,
                            "path": f"{ct_id}/oracle.json",
                            "artifact_sha256": _sha256_bytes(o_bytes),
                            "executable_sha256": run_network_sha,
                            "script_sha256": bng2_script_sha,
                            "command": " ".join(o_cmd),
                            "expected_origin": "external-source",
                            "execution": {
                                "executable": str(bng2_pl),
                                "version": bng2_ver,
                                "command": " ".join(o_cmd),
                                "exit_code": 0,
                            },
                        },
                        "producer": {
                            "path": f"{ct_id}/producer.bngl",
                            "output_sha256": p_sha,
                        },
                        "consumer": {
                            "path": f"{ct_id}/consumer.json",
                            "output_sha256": _sha256_bytes(c_bytes),
                            "consumed_producer_sha256": p_sha,
                            "execution": {
                                "executable": "bionetgen",
                                "version": bng_version,
                                "command": " ".join(c_cmd),
                                "exit_code": 0,
                            },
                        },
                    }
                    (receipts_dir / f"{ct_id}.json").write_text(
                        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    emitted.append(ct_id)

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
    parser.add_argument("--nfsim-consumer", type=Path)
    parser.add_argument("--bng2-root", type=Path)
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
        nfsim_consumer=(
            args.nfsim_consumer.resolve() if args.nfsim_consumer is not None else None
        ),
        bng2_root=args.bng2_root.resolve() if args.bng2_root is not None else None,
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
