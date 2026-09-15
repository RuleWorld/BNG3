#!/usr/bin/env python3
"""Fresh-process CPU benchmark for the direct NFsim energy path.

The benchmark reports measurements only.  It does not claim a speedup unless a
caller supplies a separately pinned control run.  The XML route is included as
the migration control so construction overhead and peak resident memory remain
visible.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

_RSS = re.compile(r"maximum resident set size:\s+(\d+)")


def _model_with_action(
    source: Path, destination: Path, t_end: float, n_steps: int
) -> None:
    text = source.read_text(encoding="utf-8")
    text += (
        "\nbegin actions\n"
        '  simulate_nf({prefix=>"energy_benchmark",'
        f"t_end=>{t_end!r},n_steps=>{n_steps},seed=>17}})\n"
        "end actions\n"
    )
    destination.write_text(text, encoding="utf-8")


def _run_once(
    bng_cpp: Path,
    model: Path,
    *,
    force_xml: bool,
) -> tuple[float, int | None, str]:
    environment = os.environ.copy()
    if force_xml:
        environment["BNG_NFSIM_FORCE_XML"] = "1"
        environment["BNG_NFSIM_ALLOW_XML_FALLBACK"] = "1"
    else:
        environment.pop("BNG_NFSIM_FORCE_XML", None)
        environment.pop("BNG_NFSIM_ALLOW_XML_FALLBACK", None)
    command = ["/usr/bin/time", "-l", str(bng_cpp), str(model)]
    start = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=model.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )
    elapsed = time.perf_counter() - start
    time_reports_restricted_sysctl = (
        completed.returncode != 0
        and "sysctl kern.clockrate: Operation not permitted" in completed.stderr
        and "You just simulated" in completed.stdout
    )
    if completed.returncode != 0 and not time_reports_restricted_sysctl:
        detail = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        ).strip()
        raise RuntimeError(
            f"benchmark command failed (exit {completed.returncode}): {detail[:4000]}"
        )
    rss_match = _RSS.search(completed.stderr)
    rss = int(rss_match.group(1)) if rss_match else None
    route = "in-memory-xml" if force_xml else "direct"
    return elapsed, rss, route


def benchmark(
    bng_cpp: Path,
    fixture: Path,
    *,
    repeats: int,
    t_end: float,
    n_steps: int,
) -> dict:
    if repeats < 2:
        raise ValueError("at least two fresh-process repeats are required")
    if not bng_cpp.is_file():
        raise FileNotFoundError(bng_cpp)
    if not fixture.is_file():
        raise FileNotFoundError(fixture)
    bng_cpp = bng_cpp.resolve()
    fixture = fixture.resolve()

    rows = []
    with tempfile.TemporaryDirectory(prefix="bng3-energy-benchmark-") as temp:
        root = Path(temp)
        for route_is_xml in (False, True):
            route_rows = []
            for repeat in range(repeats):
                run_dir = root / f"{'xml' if route_is_xml else 'direct'}-{repeat}"
                run_dir.mkdir()
                model = run_dir / fixture.name
                _model_with_action(fixture, model, t_end, n_steps)
                elapsed, rss, route = _run_once(bng_cpp, model, force_xml=route_is_xml)
                route_rows.append({"wall_s": elapsed, "peak_rss_bytes": rss})
            walls = sorted(row["wall_s"] for row in route_rows)
            rows.append(
                {
                    "route": route,
                    "repeats": route_rows,
                    "median_wall_s": walls[len(walls) // 2],
                    "min_wall_s": walls[0],
                    "max_wall_s": walls[-1],
                }
            )
    return {
        "fixture": str(fixture.resolve()),
        "bng_cpp": str(bng_cpp.resolve()),
        "repeats": repeats,
        "t_end": t_end,
        "n_steps": n_steps,
        "comparison": "measurement-only; no speedup or release claim",
        "routes": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--bng-cpp", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--t-end", type=float, default=1.0)
    parser.add_argument("--n-steps", type=int, default=5)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()
    report = benchmark(
        args.bng_cpp,
        args.fixture,
        repeats=args.repeats,
        t_end=args.t_end,
        n_steps=args.n_steps,
    )
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
