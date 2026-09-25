#!/usr/bin/env python3
"""Repeat and record the legacy SBML Atomizer CLI for a fixed input model."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION_FILES = (
    "python/bionetgen/atomizer/atomizer/analyzeSBML.py",
    "python/bionetgen/atomizer/atomizer/moleculeCreation.py",
    "python/bionetgen/atomizer/atomizer/resolveSCT.py",
    "python/bionetgen/atomizer/utils/smallStructures.py",
    "python/bionetgen/atomizer/utils/structures.py",
)
WORKER = r"""
import sys
from bionetgen.main import BioNetGenTest

source, output, mode = sys.argv[1:4]
argv = ["atomize", "-i", source, "-o", output]
if mode == "atomized":
    argv.append("-a")
with BioNetGenTest(argv=argv) as app:
    app.run()
    code = app.exit_code
if code != 0:
    raise SystemExit(code or 1)
"""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_bngl_sha256(contents: bytes) -> str:
    """Normalize ordering of annotation URI lists, which have set semantics."""
    text = contents.decode("utf-8")
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("#@") or ":[" not in line:
            continue
        key, encoded = line.split(":", 1)
        try:
            value = ast.literal_eval(encoded)
        except (SyntaxError, ValueError):
            continue
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            lines[index] = (
                f"{key}:{value!r}"
                if value == sorted(value)
                else f"{key}:{sorted(value)!r}"
            )
    normalized = "\n".join(lines)
    if text.endswith(("\n", "\r")):
        normalized += "\n"
    return sha256_bytes(normalized.encode("utf-8"))


def git_head() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def run_once(source: Path, mode: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="bng3-legacy-atomizer-") as temp:
        output = Path(temp) / f"{source.stem}_{mode}.bngl"
        env = os.environ.copy()
        source_pythonpath = os.pathsep.join(
            (str(ROOT / "python"), str(ROOT / "build" / "cpp"))
        )
        env["PYTHONPATH"] = source_pythonpath + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        start = time.perf_counter()
        result = subprocess.run(
            [sys.executable, "-c", WORKER, str(source), str(output), mode],
            cwd=temp,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if result.returncode != 0:
            raise RuntimeError(
                "legacy Atomizer failed with exit code "
                f"{result.returncode}: {(result.stderr or result.stdout)[-2000:]}"
            )
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("legacy Atomizer returned success without BNGL output")
        contents = output.read_bytes()
        return {
            "elapsed_ms": elapsed_ms,
            "output_bytes": len(contents),
            "output_sha256": sha256_bytes(contents),
            "canonical_model_sha256": canonical_bngl_sha256(contents),
        }


def benchmark(source: Path, mode: str, repeats: int) -> dict:
    samples = [run_once(source, mode) for _ in range(repeats)]
    elapsed = [sample["elapsed_ms"] for sample in samples]
    raw_hashes = {sample["output_sha256"] for sample in samples}
    canonical_hashes = {sample["canonical_model_sha256"] for sample in samples}
    return {
        "schema_version": 1,
        "implementation": "legacy Python Atomizer CLI",
        "git_head": git_head(),
        "implementation_file_sha256": {
            name: sha256_file(ROOT / name) for name in IMPLEMENTATION_FILES
        },
        "python": sys.version,
        "platform": platform.platform(),
        "mode": mode,
        "repeats": repeats,
        "input": {
            "path": str(source),
            "bytes": source.stat().st_size,
            "sha256": sha256_file(source),
        },
        "samples": samples,
        "summary": {
            "median_elapsed_ms": statistics.median(elapsed),
            "mean_elapsed_ms": statistics.mean(elapsed),
            "stdev_elapsed_ms": statistics.stdev(elapsed) if len(elapsed) > 1 else 0.0,
            "deterministic_raw_output": len(raw_hashes) == 1,
            "deterministic_canonical_model": len(canonical_hashes) == 1,
            "unique_raw_output_hashes": sorted(raw_hashes),
            "unique_canonical_model_hashes": sorted(canonical_hashes),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sbml", type=Path, help="SBML input file")
    parser.add_argument("--mode", choices=("flat", "atomized"), default="atomized")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--json", type=Path, required=True, dest="json_path")
    args = parser.parse_args()
    source = args.sbml.resolve()
    if not source.is_file():
        parser.error(f"SBML input is not a file: {source}")
    if args.repeats < 2:
        parser.error("--repeats must be at least 2")

    report = benchmark(source, args.mode, args.repeats)
    args.json_path.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"mode={report['mode']} repeats={report['repeats']} "
        f"median_ms={report['summary']['median_elapsed_ms']:.3f} "
        f"stdev_ms={report['summary']['stdev_elapsed_ms']:.3f} "
        f"deterministic_canonical_model={report['summary']['deterministic_canonical_model']}"
    )
    print(f"report={args.json_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
