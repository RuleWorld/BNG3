#!/usr/bin/env python3
"""Reproducible network-generation benchmark for BNG3 (lane: cpp/core netgen path).

Measures end-to-end wall time of ``bng_cpp <fixture>`` for a fixed set of
generate-only BNGL fixtures (``bench/models/*_gen.bngl``), i.e. parse + pattern
lowering + network expansion + .net write.  No simulation actions run.

Usage:
    python bench/netgen_bench.py                          # one binary, N reps
    python bench/netgen_bench.py --binary A --binary B    # interleaved A/B/A/B
    python bench/netgen_bench.py --reps 9 --primary median

Primary number: per-rep total wall time (sum over fixtures), summarized over
reps by --primary (default ``min``; also ``median``/``mean``).  Run-to-run
variance: min / median / mean / stdev of the per-rep totals.

Every run hashes the produced ``.net`` file; any hash variation across reps or
binaries is reported as a correctness failure (networks must be bit-identical).
"""

from __future__ import annotations

import argparse
import hashlib
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "bench" / "models"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def run_fixture(binary: Path, fixture: Path) -> tuple[float, str]:
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(binary), str(fixture)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    dt = time.perf_counter() - t0
    if proc.returncode != 0:
        sys.stderr.write(
            f"FAILED {fixture.name}: exit {proc.returncode}\n"
            + proc.stderr.decode(errors="replace")[:2000]
        )
        raise SystemExit(1)
    net = fixture.with_suffix(".net")
    if not net.exists():
        raise SystemExit(f"FAILED {fixture.name}: no .net produced")
    return dt, sha256(net)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", action="append", type=Path,
                    help="bng_cpp binary; repeat for interleaved A/B runs")
    ap.add_argument("--reps", type=int, default=7,
                    help="repetitions per binary (default 7)")
    ap.add_argument("--primary", choices=("min", "median", "mean"), default="min")
    ap.add_argument("--models", nargs="*", default=None,
                    help="fixture basenames to run (default: all in bench/models)")
    args = ap.parse_args()

    binaries = args.binary or [ROOT / "build" / "cpp" / "bng_cpp"]
    for b in binaries:
        if not b.is_file():
            raise SystemExit(f"binary not found: {b}")

    if args.models:
        fixtures = [FIXTURE_DIR / m for m in args.models]
    else:
        fixtures = sorted(FIXTURE_DIR.glob("*_gen.bngl"))
    if not fixtures:
        raise SystemExit(f"no fixtures in {FIXTURE_DIR}")
    for f in fixtures:
        if not f.is_file():
            raise SystemExit(f"fixture not found: {f}")

    print(f"fixtures ({len(fixtures)}): " + ", ".join(f.name for f in fixtures))
    print(f"reps={args.reps} binaries={[str(b) for b in binaries]}")

    # totals[binary_idx][rep] and hashes[fixture][binary_idx] -> {hash: count}
    totals: list[list[float]] = [[] for _ in binaries]
    hashes: dict[str, list[dict[str, int]]] = {
        f.name: [{} for _ in binaries] for f in fixtures
    }
    per_fixture: dict[str, list[list[float]]] = {
        f.name: [[] for _ in binaries] for f in fixtures
    }

    for rep in range(args.reps):
        for bi, binary in enumerate(binaries):
            total = 0.0
            for fixture in fixtures:
                dt, digest = run_fixture(binary, fixture)
                total += dt
                per_fixture[fixture.name][bi].append(dt)
                table = hashes[fixture.name][bi]
                table[digest] = table.get(digest, 0) + 1
            totals[bi].append(total)
            print(f"rep {rep} {binary.name}: total {total:.3f}s", flush=True)

    # ---- correctness: one hash per fixture per binary, identical across binaries
    ok = True
    for fname, per_bin in hashes.items():
        digests = set()
        for table in per_bin:
            digests.update(table)
            if len(table) != 1:
                print(f"NONDETERMINISTIC {fname}: {table}")
                ok = False
        if len(digests) != 1:
            print(f"MISMATCH {fname}: {[list(t)[0][:12] for t in per_bin]}")
            ok = False

    # ---- report
    print("\n== per-fixture wall time (s), median over reps ==")
    print(f"{'fixture':28s}" + "".join(f"{b.name:>16s}" for b in binaries))
    for fname, per_bin in per_fixture.items():
        row = f"{fname:28s}"
        for series in per_bin:
            row += f"{statistics.median(series):16.3f}"
        print(row)

    print("\n== per-rep total wall time (s) ==")
    print(f"{'binary':20s}{'min':>10s}{'median':>10s}{'mean':>10s}{'stdev':>10s}")
    stats = []
    for bi, binary in enumerate(binaries):
        series = totals[bi]
        st = (min(series), statistics.median(series),
              statistics.fmean(series), statistics.stdev(series) if len(series) > 1 else 0.0)
        stats.append(st)
        print(f"{binary.name:20s}{st[0]:10.3f}{st[1]:10.3f}{st[2]:10.3f}{st[3]:10.3f}")

    idx = {"min": 0, "median": 1, "mean": 2}[args.primary]
    primary = [st[idx] for st in stats]
    print(f"\nPRIMARY ({args.primary} total): "
          + "  ".join(f"{b.name}={p:.3f}s" for b, p in zip(binaries, primary)))
    if len(binaries) == 2:
        delta = (primary[1] - primary[0]) / primary[0] * 100.0
        noise = max(stats[0][3], stats[1][3]) / stats[0][0] * 100.0
        print(f"candidate vs baseline: {delta:+.1f}%  (noise floor ~{noise:.1f}% of min)")
    print("net hashes identical across reps and binaries: "
          + ("YES" if ok else "NO  <-- CORRECTNESS FAILURE"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
