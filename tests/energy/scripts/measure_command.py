#!/usr/bin/env python3
"""Repeat a command and emit median wall time (RSS is not measured) for performance gates."""

from __future__ import annotations
import argparse, json, statistics, subprocess, time


def measure(cmd: list[str], repeats: int) -> dict:
    if not cmd or type(repeats) is not int or repeats < 1:
        raise ValueError("a command and positive repeat count are required")
    walls = []
    for _ in range(repeats):
        t = time.perf_counter()
        p = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
        )
        walls.append(time.perf_counter() - t)
        if p.returncode:
            raise RuntimeError(f"command failed ({p.returncode}): {p.stderr}")
    return {
        "command": cmd,
        "repeats": repeats,
        "wall_s": walls,
        "median_wall_s": statistics.median(walls),
        "peak_rss_bytes": None,
        "memory_status": "not measured; cumulative child high-water differences are not per-run RSS",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    a = p.parse_args()
    if not a.cmd:
        p.error("missing command")
    print(json.dumps(measure(a.cmd, a.repeats), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
