#!/usr/bin/env python3
"""Compare generated BNG3 networks with an independent Perl BNG2 oracle.

This is a correctness check, not a benchmark: each engine runs once per fixture
in a temporary directory. The comparison ignores serialization-only ordering
and bond numbers while checking species graphs, reaction multiplicity, groups,
and rates through ``tests.validation.compare``.

Usage:
    python3 bench/check_netgen_semantics.py \
        --binary build/cpp/bng_cpp \
        --bng2 /path/to/bionetgen/bng2/BNG2.pl

The oracle run translates only the BNG3 ``reaction_rules`` section marker to
the BNG2 spelling ``reaction rules``. It does not rewrite rule patterns or
rates. Oracle syntax/semantic rejections are reported as unsupported, never as
passes. ``--preserve-adapters`` saves changed oracle inputs; ``--json-report``
records hashes, exact errors, and comparison results.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "bench" / "models"
sys.path.insert(0, str(ROOT))

from tests.validation.compare import compare_net, parse_net  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_bng2_source(source: str) -> str:
    """Translate BNG3's underscore block marker without changing model rules."""
    return re.sub(
        r"(?m)^(\s*(?:begin|end)\s+)reaction_rules(\s*(?:#.*)?$)",
        r"\1reaction rules\2",
        source,
    )


def source_revision(script: Path) -> str | None:
    root = subprocess.run(
        ["git", "-C", str(script.parent), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if root.returncode:
        return None
    revision = subprocess.run(
        ["git", "-C", root.stdout.strip(), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    return revision.stdout.strip() if revision.returncode == 0 else None


def run_model(
    binary: Path,
    bng2_script: Path,
    fixture: Path,
    *,
    timeout: int,
    preserve_adapters: Path | None,
) -> dict[str, Any]:
    original_text = fixture.read_text()
    oracle_text = normalize_bng2_source(original_text)
    record: dict[str, Any] = {
        "fixture": fixture.name,
        "fixture_sha256": sha256_file(fixture),
        "oracle_input_sha256": hashlib.sha256(oracle_text.encode()).hexdigest(),
        "adapter_changes": [],
    }
    if oracle_text != original_text:
        diff = "".join(
            difflib.unified_diff(
                original_text.splitlines(keepends=True),
                oracle_text.splitlines(keepends=True),
                fromfile=f"a/{fixture.name}",
                tofile=f"b/{fixture.name}.bng2",
            )
        )
        record["adapter_changes"] = [
            "begin/end reaction_rules block markers changed to BNG2's begin/end reaction rules"
        ]
        record["adapter_diff"] = diff
        if preserve_adapters is not None:
            adapter_path = preserve_adapters / fixture.name
            adapter_path.parent.mkdir(parents=True, exist_ok=True)
            adapter_path.write_text(oracle_text)
            record["adapter_path"] = str(adapter_path)

    perl = os.environ.get("PERL", "perl")
    perl_path = shutil.which(perl)
    if perl_path is None:
        record.update(status="FAIL", reason=f"Perl interpreter not found: {perl}")
        return record

    with tempfile.TemporaryDirectory(prefix="bng3-netgen-parity-") as raw_dir:
        work = Path(raw_dir)
        cpp_dir, oracle_dir = work / "bng3", work / "bng2"
        cpp_dir.mkdir()
        oracle_dir.mkdir()
        cpp_input = cpp_dir / fixture.name
        oracle_input = oracle_dir / fixture.name
        shutil.copy2(fixture, cpp_input)
        oracle_input.write_text(oracle_text)
        oracle_out = oracle_dir / "out"
        oracle_out.mkdir()
        env = dict(os.environ, BNGPATH=str(bng2_script.parent))

        try:
            bng3 = subprocess.run(
                [str(binary), str(cpp_input)],
                cwd=cpp_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            record.update(status="FAIL", reason=f"BNG3 timeout after {timeout}s")
            record["bng3_output"] = str(exc.stderr or exc.stdout or "")[-4000:]
            return record
        if bng3.returncode != 0:
            record.update(status="FAIL", reason=f"BNG3 exited {bng3.returncode}")
            record["bng3_output"] = (bng3.stderr or bng3.stdout)[-4000:]
            return record

        try:
            bng2 = subprocess.run(
                [
                    perl_path,
                    str(bng2_script),
                    "--outdir",
                    str(oracle_out),
                    str(oracle_input),
                ],
                cwd=oracle_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            record.update(status="UNSUPPORTED", reason=f"BNG2 timeout after {timeout}s")
            record["bng2_output"] = str(exc.stderr or exc.stdout or "")[-4000:]
            return record
        if bng2.returncode != 0:
            output = (bng2.stderr or "") + "\n" + (bng2.stdout or "")
            record["bng2_exit_code"] = bng2.returncode
            record["bng2_output"] = output[-4000:]
            if "dangling edge not allowed in species graph" in output:
                record.update(
                    status="UNSUPPORTED",
                    reason="pinned BNG2 rejects a dangling numbered bond in the fixture",
                )
            else:
                record.update(status="FAIL", reason=f"BNG2 exited {bng2.returncode}")
            return record

        bng3_net = cpp_input.with_suffix(".net")
        bng2_nets = sorted(oracle_out.glob("*.net"))
        if not bng3_net.is_file() or len(bng2_nets) != 1:
            record.update(
                status="FAIL",
                reason=(
                    f"missing/ambiguous network output: BNG3={bng3_net.is_file()}, "
                    f"BNG2_count={len(bng2_nets)}"
                ),
            )
            return record

        bng3_network = parse_net(bng3_net)
        bng2_network = parse_net(bng2_nets[0])
        if bng3_network is None or bng2_network is None:
            record.update(status="FAIL", reason="one engine emitted an unparsable .net")
            return record
        comparison = compare_net(bng2_network, bng3_network)
        if comparison.ok:
            record.update(status="PASS", reason="graph/reaction/group/rate parity")
        else:
            record.update(status="FAIL", reason="semantic .net mismatch")
            record["comparison"] = comparison.summary()
        return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "build/cpp/bng_cpp")
    parser.add_argument(
        "--bng2",
        type=Path,
        default=ROOT / "legacy/perl/BNG2.pl",
        help="independent Perl BNG2.pl script",
    )
    parser.add_argument("--models", nargs="*", default=None, help="fixture basenames")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--preserve-adapters", type=Path, default=None)
    parser.add_argument("--json-report", type=Path, default=None)
    args = parser.parse_args()
    binary = args.binary.expanduser().resolve()
    bng2_script = args.bng2.expanduser().resolve()
    if not binary.is_file():
        parser.error(f"BNG3 binary not found: {binary}")
    if not bng2_script.is_file():
        parser.error(f"BNG2 script not found: {bng2_script}")
    if args.timeout < 1:
        parser.error("--timeout must be at least 1 second")

    fixtures = (
        [FIXTURE_DIR / name for name in args.models]
        if args.models
        else sorted(FIXTURE_DIR.glob("*_gen.bngl"))
    )
    if not fixtures:
        parser.error(f"no fixtures found in {FIXTURE_DIR}")
    for fixture in fixtures:
        if not fixture.is_file():
            parser.error(f"fixture not found: {fixture}")

    report: dict[str, Any] = {
        "bng3_binary": str(binary),
        "bng3_binary_sha256": sha256_file(binary),
        "bng2_script": str(bng2_script),
        "bng2_script_sha256": sha256_file(bng2_script),
        "bng2_source_revision": source_revision(bng2_script),
        "fixture_count": len(fixtures),
        "results": [],
    }
    print(f"BNG3 binary sha256: {report['bng3_binary_sha256']}")
    print(f"BNG2 script sha256: {report['bng2_script_sha256']}")
    print(f"BNG2 source revision: {report['bng2_source_revision'] or 'unknown'}")
    for fixture in fixtures:
        result = run_model(
            binary,
            bng2_script,
            fixture,
            timeout=args.timeout,
            preserve_adapters=args.preserve_adapters,
        )
        report["results"].append(result)
        print(f"{result['status']:11s} {fixture.name}: {result.get('reason', '')}")
        if result.get("bng2_output"):
            print(
                result["bng2_output"],
                end="" if result["bng2_output"].endswith("\n") else "\n",
            )
        if result.get("comparison"):
            print(result["comparison"])
        if result.get("adapter_diff"):
            print(result["adapter_diff"], end="")

    statuses = [result["status"] for result in report["results"]]
    passed = statuses.count("PASS")
    unsupported = statuses.count("UNSUPPORTED")
    failed = statuses.count("FAIL")
    report["summary"] = {"passed": passed, "unsupported": unsupported, "failed": failed}
    print(
        f"RESULT {passed}/{len(fixtures)} passed, {unsupported} unsupported, {failed} failed"
    )
    if args.json_report is not None:
        report_path = args.json_report.expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"JSON report: {report_path}")
    if failed:
        return 1
    return 2 if unsupported else 0


if __name__ == "__main__":
    raise SystemExit(main())
