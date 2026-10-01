#!/usr/bin/env python3
"""Reproducible network-generation benchmark for BNG3 (lane: cpp/core netgen path).

Measures end-to-end wall time of ``bng_cpp <fixture>`` for generate-only BNGL
fixtures (``bench/models/*_gen.bngl``), i.e. parse + pattern lowering + network
expansion + .net write.  No simulation actions run.  Fixtures are regenerated
from models/ by ``python bench/make_fixtures.py``.

Usage:
    python bench/netgen_bench.py                          # heavy preset (default)
    python bench/netgen_bench.py --full                   # all 11 fixtures (final gate)
    python bench/netgen_bench.py --binary A --binary B    # interleaved A/B
    python bench/netgen_bench.py --reps 7

Populations:
  * ``--default`` (no flags): 4 heavy fixtures (egfr_net, fceri_ji, e6, e7).
    e7 is ~70% of the 11-fixture runtime; the heavy preset keeps a run to
    ~12 s/rep while still spanning two model families.
  * ``--full``: all 11 fixtures — for the final correctness gate, not for
    detecting small timing deltas.

Interleaving: rounds are per-rep; inside each round the arms run back-to-back
(A then B), so co-tenant load hits both arms of the same round roughly equally.
Report min AND median; if min-to-median spread exceeds 25% of min the harness
prints NOISE WARNING and any delta inside that spread must be treated as
unmeasured (host floor: ~11% cross-session drift, measured by the shared
fitness harness).

Measurement context: printout includes loadavg band and runnable-process count
at start and end (loadavg is a coarse band on this host, not a decimal — see
docs), plus per-fixture peak RSS from wait4 rusage.

Correctness gate (every run, every binary): sha256 of the raw .net bytes must
be identical across all reps and all binaries — with ONE exemption:

  ``tlbr_gen.bngl`` — RAW-EXEMPT.  The BASELINE binary itself emits two
  site-numbering variants of the same network across runs (measured: 46/60 vs
  14/60 on one binary; 15/24 vs 9/24 on an independent binary; two canonical
  variants also survive bond-id renumbering, so the difference is construction
  order, not just numbering).  Pre-existing defect, escalated to
  orchPerf/Main and owned elsewhere; not touched by this benchmark.  Instead
  of a byte hash, tlbr must satisfy a weak structural gate: identical species
  line count, identical reactions block, identical groups block, across all
  reps and binaries.  Re-check exemption status with:
      for i in $(seq 1 60); do bng_cpp bench/models/tlbr_gen.bngl;
          shasum -a 256 bench/models/tlbr_gen.net; done
"""

from __future__ import annotations

import argparse
import hashlib
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "bench" / "models"

HEAVY = ["egfr_net_gen.bngl", "fceri_ji_gen.bngl", "e6_gen.bngl", "e7_gen.bngl"]
RAW_EXEMPT = {"tlbr_gen.bngl"}
NOISE_SPREAD = 0.25


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def block_digest(data: bytes, begin: bytes, end: bytes) -> tuple[int, str]:
    """(line count inside block, sha of block text) for weak gates."""
    text = data.decode(errors="replace").splitlines()
    inside = False
    block = []
    for line in text:
        if line.strip() == begin:
            inside = True
            continue
        if line.strip() == end:
            break
        if inside:
            block.append(line)
    body = "\n".join(block).encode()
    return len(block), sha256(body)


def weak_gate(data: bytes) -> tuple[int, str, str]:
    species_n, _ = block_digest(data, b"begin species", b"end species")
    _, rxn = block_digest(data, b"begin reactions", b"end reactions")
    _, grp = block_digest(data, b"begin groups", b"end groups")
    return species_n, rxn, grp


def run_fixture(binary: Path, fixture: Path) -> tuple[float, str, tuple, int]:
    """Returns (wall_s, raw_hash, weak_gate_tuple, peak_rss_bytes)."""
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        [str(binary), str(fixture)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    stderr = proc.stderr.read()
    _, status, rusage = os.wait4(proc.pid, 0)
    proc.returncode = os.waitstatus_to_exitcode(status)
    dt = time.perf_counter() - t0
    if proc.returncode != 0:
        sys.stderr.write(
            f"FAILED {fixture.name}: exit {proc.returncode}\n"
            + stderr.decode(errors="replace")[:2000]
        )
        raise SystemExit(1)
    net = fixture.with_suffix(".net")
    if not net.exists():
        raise SystemExit(f"FAILED {fixture.name}: no .net produced")
    data = net.read_bytes()
    # macOS ru_maxrss is in bytes.
    return dt, sha256(data), weak_gate(data), int(rusage.ru_maxrss)


def load_context() -> str:
    """Coarse band + runnable count; loadavg is NOT a precise signal here."""
    try:
        load = os.getloadavg()
        band = f"loadavg band {int(min(load))}-{int(max(load))}"
    except OSError:
        band = "loadavg n/a"
    try:
        out = subprocess.run(["ps", "-axo", "state="], capture_output=True,
                             text=True, timeout=10).stdout
        runnable = sum(1 for ln in out.splitlines() if ln.startswith("R"))
        band += f", R={runnable}"
    except Exception:
        pass
    return band


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", action="append", type=Path,
                    help="bng_cpp binary; repeat for interleaved A/B runs")
    ap.add_argument("--reps", type=int, default=7,
                    help="rounds per binary (default 7)")
    ap.add_argument("--primary", choices=("min", "median", "mean"), default="min")
    ap.add_argument("--full", action="store_true",
                    help="run all 11 fixtures (final gate); default is the 4 heavy ones")
    ap.add_argument("--models", nargs="*", default=None,
                    help="explicit fixture basenames (overrides --full)")
    args = ap.parse_args()

    binaries = args.binary or [ROOT / "build" / "cpp" / "bng_cpp"]
    for b in binaries:
        if not b.is_file():
            raise SystemExit(f"binary not found: {b}")

    if args.models:
        fixtures = [FIXTURE_DIR / m for m in args.models]
    elif args.full:
        fixtures = sorted(FIXTURE_DIR.glob("*_gen.bngl"))
    else:
        fixtures = [FIXTURE_DIR / m for m in HEAVY]
    if not fixtures:
        raise SystemExit(f"no fixtures in {FIXTURE_DIR}")
    for f in fixtures:
        if not f.is_file():
            raise SystemExit(f"fixture not found: {f}")

    start_ctx = load_context()
    print(f"fixtures ({len(fixtures)}): " + ", ".join(f.name for f in fixtures))
    print(f"reps={args.reps} (arms interleaved per round) "
          f"binaries={[str(b) for b in binaries]}")
    print(f"context at start: {start_ctx}")
    exempt = sorted(RAW_EXEMPT & {f.name for f in fixtures})
    if exempt:
        print(f"raw-hash EXEMPT (pre-existing baseline nondeterminism; "
              f"weak structural gate applies): {exempt}")

    totals: list[list[float]] = [[] for _ in binaries]
    raw_hashes: dict[str, list[dict[str, int]]] = {
        f.name: [{} for _ in binaries] for f in fixtures
    }
    weak_gates: dict[str, list[dict[tuple, int]]] = {
        f.name: [{} for _ in binaries] for f in fixtures
    }
    per_fixture: dict[str, list[list[float]]] = {
        f.name: [[] for _ in binaries] for f in fixtures
    }
    peak_rss = 0

    for rep in range(args.reps):
        for bi, binary in enumerate(binaries):
            total = 0.0
            for fixture in fixtures:
                dt, raw, weak, rss = run_fixture(binary, fixture)
                total += dt
                peak_rss = max(peak_rss, rss)
                per_fixture[fixture.name][bi].append(dt)
                raw_table = raw_hashes[fixture.name][bi]
                raw_table[raw] = raw_table.get(raw, 0) + 1
                gate_table = weak_gates[fixture.name][bi]
                gate_table[weak] = gate_table.get(weak, 0) + 1
            totals[bi].append(total)
            print(f"rep {rep} {binary.name}: total {total:.3f}s", flush=True)

    # ---- correctness gates
    ok = True
    for fname, per_bin in raw_hashes.items():
        digests = set()
        for table in per_bin:
            digests.update(table)
        if fname in RAW_EXEMPT:
            continue
        if len(digests) != 1 or any(len(t) != 1 for t in per_bin):
            print(f"RAW MISMATCH/NONDETERMINISTIC {fname}: "
                  f"{[{k[:12]: v for k, v in t.items()} for t in per_bin]}")
            ok = False
    for fname, per_bin in weak_gates.items():
        if fname not in RAW_EXEMPT:
            continue
        digests = set()
        for table in per_bin:
            digests.update(table)
        if len(digests) != 1 or any(len(t) != 1 for t in per_bin):
            print(f"WEAK GATE FAILURE {fname}: {per_bin}")
            ok = False
        else:
            print(f"weak structural gate for EXEMPT {fname}: "
                  f"species-lines/reactions/groups stable {list(digests)[0][:2]}")

    # ---- report
    end_ctx = load_context()
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
        print(f"{'  sorted:':20s}"
              + "".join(f"{v:10.3f}" for v in sorted(series)))
        if st[1] - st[0] > st[0] * NOISE_SPREAD:
            print(f"  NOISE WARNING {binary.name}: median-min = "
                  f"{st[1] - st[0]:.3f}s > {NOISE_SPREAD * 100:.0f}% of min; "
                  "deltas inside this spread are UNMEASURED")

    idx = {"min": 0, "median": 1, "mean": 2}[args.primary]
    primary = [st[idx] for st in stats]
    print(f"\nPRIMARY ({args.primary} total): "
          + "  ".join(f"{b.name}={p:.3f}s" for b, p in zip(binaries, primary)))
    if len(binaries) == 2:
        delta = (primary[1] - primary[0]) / primary[0] * 100.0
        noise = max(stats[0][3], stats[1][3]) / stats[0][0] * 100.0
        print(f"candidate vs baseline: {delta:+.1f}%  (stdev of arms: {noise:.1f}% of min; "
              "host cross-session floor ~11%)")
    print(f"context at start: {start_ctx}")
    print(f"context at end:   {end_ctx}")
    print(f"peak RSS of any single run: {peak_rss / (1 << 20):.1f} MiB")
    print("correctness gates (raw .net identity + weak gate for exempt): "
          + ("PASS" if ok else "FAIL  <-- CORRECTNESS FAILURE"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
