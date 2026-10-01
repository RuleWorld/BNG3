#!/usr/bin/env python3
"""Benchmark Python-side speed: import cold-start, CLI startup, atomizer.

Prints one primary number (import cold-start, fresh subprocesses) with min and
spread over --reps repetitions, then secondary candidate timings.  Run from the
repository root:

    PYTHONPATH=python:build/cpp python benchmarks/benchmark_python_speed.py

Every timing uses time.perf_counter.  Import and CLI timings run in fresh
subprocesses so the page cache and import machinery see the same starting
state each repetition; the atomizer timing runs in one process after a warm-up
so it measures conversion, not interpreter startup.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = os.pathsep.join(
    [str(REPO_ROOT / "python"), str(REPO_ROOT / "build" / "cpp")]
)

# Strip the environment's scikit-build editable meta-path finder so the
# subprocess imports THIS tree, not whatever tree the editable install was
# generated from.  Without this the benchmark silently measures another
# checkout.
_PRELUDE = (
    "import sys\n"
    "sys.meta_path[:] = [\n"
    "    f for f in sys.meta_path\n"
    "    if type(f).__module__ != '_editable_skbc_bionetgen'\n"
    "]\n"
)


def _child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = PYTHONPATH
    return env


def _run_child(code: str) -> float:
    """Run `code` in a fresh interpreter; return wall seconds."""
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-c", _PRELUDE + code],
        env=_child_env(),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(
            f"child failed ({proc.returncode}):\n{proc.stderr[-2000:]}"
        )
    return elapsed


def _summarize(samples: list[float]) -> dict:
    return {
        "min_ms": min(samples) * 1000.0,
        "median_ms": statistics.median(samples) * 1000.0,
        "max_ms": max(samples) * 1000.0,
        "spread_ms": (max(samples) - min(samples)) * 1000.0,
        "n": len(samples),
    }


def bench_import(reps: int) -> dict:
    """import bionetgen in a fresh subprocess each rep."""
    samples = [_run_child("import bionetgen\n") for _ in range(reps)]
    return {"name": "import bionetgen (fresh subprocess)", **_summarize(samples)}


def bench_cli(reps: int) -> dict:
    """CLI startup to first output: bionetgen --help in a fresh subprocess."""
    code = (
        "import sys\n"
        "sys.argv = ['bionetgen', '--help']\n"
        "import runpy\n"
        "runpy.run_module('bionetgen', run_name='__main__')\n"
    )
    samples = [_run_child(code) for _ in range(reps)]
    return {
        "name": "bionetgen --help (fresh subprocess)",
        **_summarize(samples),
    }


def bench_atomize(reps: int, fixture: str) -> dict:
    """Atomizer conversion on a small SBML file, warmed, in-process."""
    code = (
        "import json, time\n"
        "from bionetgen.sbml import sbml_to_bngl\n"
        f"fixture = {fixture!r}\n"
        "sbml_to_bngl(fixture, atomize=True)\n"
        f"runs = {reps}\n"
        "samples = []\n"
        "digest = None\n"
        "for _ in range(runs):\n"
        "    t0 = time.perf_counter()\n"
        "    text = sbml_to_bngl(fixture, atomize=True)\n"
        "    samples.append(time.perf_counter() - t0)\n"
        "    digest = hash(text)\n"
        "print(json.dumps({'samples': samples, 'digest': digest, 'len': len(text)}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", _PRELUDE + code],
        env=_child_env(),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"atomize child failed:\n{proc.stderr[-2000:]}")
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    return {
        "name": f"atomizer sbml_to_bngl({Path(fixture).name}) in-process",
        **_summarize(payload["samples"]),
        "output_len": payload["len"],
        "output_digest": payload["digest"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=9)
    parser.add_argument(
        "--fixture",
        default="tests/validation/Validate/gene_expr_sbml.xml",
        help="small SBML file for the atomizer candidate",
    )
    parser.add_argument("--json", default=None, help="optional JSON output path")
    args = parser.parse_args()

    results = [bench_import(args.reps), bench_cli(args.reps)]
    results.append(bench_atomize(max(args.reps, 7), args.fixture))

    primary = results[0]
    print(
        f"PRIMARY import-bionetgen cold-start: "
        f"min {primary['min_ms']:.1f} ms, "
        f"spread {primary['spread_ms']:.1f} ms "
        f"(median {primary['median_ms']:.1f} ms, n={primary['n']})"
    )
    for record in results[1:]:
        extra = ""
        if "output_digest" in record:
            extra = (
                f", out_len={record['output_len']}"
                f" digest={record['output_digest']}"
            )
        print(
            f"  {record['name']}: min {record['min_ms']:.1f} ms, "
            f"spread {record['spread_ms']:.1f} ms, "
            f"median {record['median_ms']:.1f} ms{extra}"
        )

    if args.json:
        Path(args.json).write_text(
            json.dumps(results, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
