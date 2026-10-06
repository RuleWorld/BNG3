#!/usr/bin/env python3
"""Parse a bench_batch_ssa --mode dump file and report per-chunk work imbalance.

The pool partitions a batch into `numThreads` contiguous chunks and runs one
trajectory per index b with seed base+b. Because the per-trajectory cost is
proportional to its event count, the sum of event counts per chunk is a
load-independent measure of how evenly the static partitioning balances work:
the pool's wall time is set by its heaviest chunk, not its mean chunk.

Usage: parse_dump.py <dump.bin> <batch> <num_threads>
"""

import struct
import sys


def parse(path):
    d = open(path, "rb").read()
    o = 0
    (batch,) = struct.unpack_from("<Q", d, o)
    o += 8
    (events,) = struct.unpack_from("<Q", d, o)
    o += 8

    def arr(fmt):
        nonlocal o
        (n,) = struct.unpack_from("<Q", d, o)
        o += 8
        sz = struct.calcsize(fmt)
        vals = struct.unpack_from("<" + fmt[1] * n, d, o) if n else ()
        o += sz * n
        return vals

    # observable names: count, then uint64 length-prefixed strings
    (nnames,) = struct.unpack_from("<Q", d, o)
    o += 8
    names = []
    for _ in range(nnames):
        (ln,) = struct.unpack_from("<Q", d, o)
        o += 8
        names.append(d[o : o + ln].decode())
        o += ln
    return batch, events, names, arr, d, o


def main():
    path, batch, threads = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    b, events, names, arr, d, o = parse(path)

<<<<<<< HEAD
    _ = arr("<f")  # timePoints
=======
    time_points = arr("<f")  # timePoints
>>>>>>> origin/main
    arr("<d")  # timePointsDouble
    counts = arr("<I")  # trajectoryEventCounts
    final_species = arr("<i")  # finalSpecies
    final_obs = arr("<f")  # finalObservables

    print(
        f"batch={b} total_events={events} trajectories={len(counts)} "
        f"observables={len(names)} {names}"
    )
    print(f"finalSpecies={len(final_species)} finalObservables={len(final_obs)}")

    chunk = (batch + threads - 1) // threads
    sums = []
    for t in range(threads):
        lo = t * chunk
        hi = min(lo + chunk, batch)
        if lo >= hi:
            continue
        sums.append(sum(counts[lo:hi]))
    mean = sum(sums) / len(sums)
    print(f"chunks={len(sums)} mean_events_per_chunk={mean:.1f}")
    print(
        f"  heaviest={max(sums)} ({max(sums) / mean:.4f}x mean)  "
        f"lightest={min(sums)} ({min(sums) / mean:.4f}x mean)"
    )
    print(
        f"  static-partition imbalance penalty (heaviest/mean - 1) = "
        f"{100 * (max(sums) / mean - 1):.2f}%"
    )
    print(f"  chunk sums: {sorted(sums, reverse=True)}")

    # Per-trajectory cost spread (drives the imbalance).
    m = sum(counts) / len(counts)
    var = sum((c - m) ** 2 for c in counts) / len(counts)
    print(
        f"per-trajectory events: mean={m:.2f} sd={var**0.5:.2f} "
        f"min={min(counts)} max={max(counts)}"
    )


if __name__ == "__main__":
    main()
