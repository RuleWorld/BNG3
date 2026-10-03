#!/usr/bin/env python3
"""Reproducible network-generation benchmark for BNG3.

Measures end-to-end ``bng_cpp <fixture>`` wall time for generate-only BNGL
fixtures: parse, pattern lowering, network expansion, and .net write. It does
not time the independent oracle; run ``bench/check_netgen_semantics.py`` for
graph/rate comparison against Perl BNG2.

Usage (from the repository root):
    python3 bench/netgen_bench.py
    python3 bench/netgen_bench.py --full
    python3 bench/netgen_bench.py --binary /path/base --binary /path/candidate
    python3 bench/netgen_bench.py --reps 7

The default preset uses egfr_net, fceri_ji, e6, and e7. ``--full`` runs all 11
fixtures. A/B order alternates by round. Every invocation gets a fresh temp
directory, so stale .net output cannot satisfy a run and generated files do not
accumulate beside the fixtures. Raw .net identity must hold across every rep
and binary, including tlbr: current main fixed its address-dependent emission
order in 44664f1.

For measurement runs, wrap this command with tools/benchlock/benchlock using a
shared BENCHLOCK_DIR and BENCHLOCK_MAX=1. Correctness/oracle checks need no
timing slot. The summary reports per-fixture and per-rep wall time, per-fixture
peak RSS, and coarse host context; compare paired A/B reps and retain the full
output with the exact binary SHAs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "bench" / "models"
HEAVY = ["egfr_net_gen.bngl", "fceri_ji_gen.bngl", "e6_gen.bngl", "e7_gen.bngl"]
NOISE_SPREAD = 0.25


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_identity_mismatches(raw_hashes: dict[str, list[dict[str, int]]]) -> list[str]:
    """Return fixture names whose bytes differ across reps or binaries."""
    mismatches = []
    for fixture, per_binary in raw_hashes.items():
        all_hashes = {digest for table in per_binary for digest in table}
        if len(all_hashes) != 1 or any(len(table) != 1 for table in per_binary):
            mismatches.append(fixture)
    return sorted(mismatches)


def ru_maxrss_bytes(value: int, platform: str | None = None) -> int:
    """Normalize wait4 ru_maxrss units on supported macOS and Linux hosts."""
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        return int(value)
    if platform.startswith("linux"):
        return int(value) * 1024
    raise RuntimeError(f"ru_maxrss units are not defined for platform {platform!r}")


def run_fixture(binary: Path, fixture: Path) -> tuple[float, str, int]:
    """Return (wall seconds, raw .net SHA256, peak RSS bytes)."""
    with tempfile.TemporaryDirectory(prefix="bng3-netgen-bench-") as raw_dir:
        run_dir = Path(raw_dir)
        run_fixture_path = run_dir / fixture.name
        shutil.copy2(fixture, run_fixture_path)

        start = time.perf_counter()
        proc = subprocess.Popen(
            [str(binary), str(run_fixture_path)],
            cwd=run_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert proc.stderr is not None
        stderr = proc.stderr.read()
        _, status, rusage = os.wait4(proc.pid, 0)
        proc.returncode = os.waitstatus_to_exitcode(status)
        elapsed = time.perf_counter() - start

        if proc.returncode != 0:
            sys.stderr.write(
                f"FAILED {fixture.name}: exit {proc.returncode}\n"
                + stderr.decode(errors="replace")[:2000]
            )
            raise SystemExit(1)
        net_path = run_fixture_path.with_suffix(".net")
        if not net_path.is_file():
            raise SystemExit(f"FAILED {fixture.name}: no fresh .net produced")
        return elapsed, sha256(net_path.read_bytes()), ru_maxrss_bytes(rusage.ru_maxrss)


def load_context() -> str:
    """Coarse host load band and runnable-process count."""
    try:
        load = os.getloadavg()
        band = f"loadavg band {int(min(load))}-{int(max(load))}"
    except OSError:
        band = "loadavg n/a"
    try:
        out = subprocess.run(
            ["ps", "-axo", "state="], capture_output=True, text=True, timeout=10
        ).stdout
        runnable = sum(1 for line in out.splitlines() if line.startswith("R"))
        band += f", R={runnable}"
    except (OSError, subprocess.SubprocessError):
        band += ", R=n/a"
    return band


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--binary", action="append", type=Path,
        help="bng_cpp executable; repeat for paired A/B runs",
    )
    parser.add_argument("--reps", type=int, default=7, help="rounds per binary (default 7)")
    parser.add_argument(
        "--primary", choices=("min", "median", "mean"), default="median",
        help="summary statistic used for the headline delta (default: median)",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="run all 11 fixtures instead of the four-fixture heavy preset",
    )
    parser.add_argument(
        "--models", nargs="*", default=None,
        help="fixture basenames (overrides --full)",
    )
    parser.add_argument("--json", type=Path, default=None,
                        help="write samples, hashes, contexts, and RSS as JSON")
    args = parser.parse_args()
    if args.reps < 1:
        parser.error("--reps must be at least 1")

    binaries = [path.expanduser().resolve() for path in (args.binary or [ROOT / "build/cpp/bng_cpp"])]
    for binary in binaries:
        if not binary.is_file():
            raise SystemExit(f"binary not found: {binary}")

    if args.models:
        fixtures = [FIXTURE_DIR / name for name in args.models]
    elif args.full:
        fixtures = sorted(FIXTURE_DIR.glob("*_gen.bngl"))
    else:
        fixtures = [FIXTURE_DIR / name for name in HEAVY]
    if not fixtures:
        raise SystemExit(f"no fixtures in {FIXTURE_DIR}")
    for fixture in fixtures:
        if not fixture.is_file():
            raise SystemExit(f"fixture not found: {fixture}")

    start_context = load_context()
    print(f"fixtures ({len(fixtures)}): " + ", ".join(f.name for f in fixtures))
    print(f"reps={args.reps}; alternating arm order by round; binaries={binaries}")
    for binary in binaries:
        print(f"binary sha256 {binary}: {sha256(binary.read_bytes())}")
    print(f"context at start: {start_context}")

    totals: list[list[float]] = [[] for _ in binaries]
    raw_hashes: dict[str, list[dict[str, int]]] = {
        fixture.name: [{} for _ in binaries] for fixture in fixtures
    }
    per_fixture: dict[str, list[list[float]]] = {
        fixture.name: [[] for _ in binaries] for fixture in fixtures
    }
    peak_rss_bytes: dict[str, list[int]] = {
        fixture.name: [0 for _ in binaries] for fixture in fixtures
    }

    for rep in range(args.reps):
        order = list(range(len(binaries)))
        if len(order) == 2 and rep % 2:
            order.reverse()
        for binary_index in order:
            binary = binaries[binary_index]
            total = 0.0
            for fixture in fixtures:
                elapsed, digest, rss_bytes = run_fixture(binary, fixture)
                total += elapsed
                per_fixture[fixture.name][binary_index].append(elapsed)
                peak_rss_bytes[fixture.name][binary_index] = max(
                    peak_rss_bytes[fixture.name][binary_index], rss_bytes
                )
                hash_table = raw_hashes[fixture.name][binary_index]
                hash_table[digest] = hash_table.get(digest, 0) + 1
            totals[binary_index].append(total)
            print(f"rep {rep} {binary.name}: total {total:.3f}s", flush=True)

    mismatches = raw_identity_mismatches(raw_hashes)
    for fixture in mismatches:
        print(f"RAW MISMATCH/NONDETERMINISTIC {fixture}: "
              f"{raw_hashes[fixture]}")

    end_context = load_context()
    print("\n== per-fixture wall time (s), median over reps ==")
    print(f"{'fixture':28s}" + "".join(f"{binary.name:>16s}" for binary in binaries))
    for fixture_name, per_binary in per_fixture.items():
        row = f"{fixture_name:28s}"
        for series in per_binary:
            row += f"{statistics.median(series):16.3f}"
        print(row)

    print("\n== peak RSS by fixture (MiB) ==")
    print(f"{'fixture':28s}" + "".join(f"{binary.name:>16s}" for binary in binaries))
    for fixture_name, per_binary in peak_rss_bytes.items():
        row = f"{fixture_name:28s}"
        for value in per_binary:
            row += f"{value / (1 << 20):16.2f}"
        print(row)

    print("\n== per-rep total wall time (s) ==")
    print(f"{'binary':28s}{'min':>10s}{'median':>10s}{'mean':>10s}{'stdev':>10s}")
    stats = []
    for index, binary in enumerate(binaries):
        series = totals[index]
        summary = (
            min(series), statistics.median(series), statistics.fmean(series),
            statistics.stdev(series) if len(series) > 1 else 0.0,
        )
        stats.append(summary)
        print(f"{binary.name:28s}{summary[0]:10.3f}{summary[1]:10.3f}"
              f"{summary[2]:10.3f}{summary[3]:10.3f}")
        print(f"{'  sorted:':28s}" + "".join(f"{value:10.3f}" for value in sorted(series)))
        if summary[1] - summary[0] > summary[0] * NOISE_SPREAD:
            print(f"  NOISE WARNING {binary.name}: median-min exceeds "
                  f"{NOISE_SPREAD * 100:.0f}% of min; small deltas are unresolved")

    statistic_index = {"min": 0, "median": 1, "mean": 2}[args.primary]
    primary = [summary[statistic_index] for summary in stats]
    print(f"\nPRIMARY ({args.primary} total): "
          + "  ".join(f"{binary.name}={value:.3f}s"
                      for binary, value in zip(binaries, primary)))
    if len(binaries) == 2:
        paired_deltas = [
            (candidate - baseline) / baseline * 100.0
            for baseline, candidate in zip(totals[0], totals[1]) if baseline > 0
        ]
        selected_delta = (primary[1] - primary[0]) / primary[0] * 100.0
        print(f"candidate vs baseline: {selected_delta:+.1f}% on {args.primary}")
        print("paired per-round deltas (%): "
              + ", ".join(f"{delta:+.1f}" for delta in paired_deltas))
        print(f"paired median delta: {statistics.median(paired_deltas):+.1f}%")
    print(f"context at start: {start_context}")
    print(f"context at end:   {end_context}")
    print("raw .net identity across all reps and binaries: "
          + ("PASS" if not mismatches else "FAIL  <-- CORRECTNESS FAILURE"))
    if args.json is not None:
        report = {
            "fixtures": [fixture.name for fixture in fixtures],
            "reps": args.reps,
            "primary": args.primary,
            "arm_order": "alternating by round for two binaries",
            "context_start": start_context,
            "context_end": end_context,
            "raw_identity_pass": not mismatches,
            "raw_identity_mismatches": mismatches,
            "binaries": [],
        }
        for index, binary in enumerate(binaries):
            report["binaries"].append({
                "path": str(binary),
                "sha256": sha256(binary.read_bytes()),
                "total_wall_s": totals[index],
                "per_fixture_wall_s": {
                    name: series[index] for name, series in per_fixture.items()
                },
                "peak_rss_bytes": {
                    name: per_binary[index]
                    for name, per_binary in peak_rss_bytes.items()
                },
                "raw_hash_counts": {
                    name: raw_hashes[name][index] for name in raw_hashes
                },
            })
        report_path = args.json.expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"JSON report: {report_path}")
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
