#!/usr/bin/env python3
"""Benchmark Python-side speed: import spawns (primary), wall time, outputs.

Primary metric is the number of subprocess spawns during a fresh
``python -c "import bionetgen"`` — a deterministic, load-insensitive integer
counted with a sys audit hook.  Secondary is wall-clock over fresh
subprocesses (min / median / spread plus the full sorted list and the
loadavg band of the run).  Tertiary is the byte-level output gate: the
banner digest, ``__version__``, the ``--version`` line, and the resolved
``UNDER TEST`` package path.

Run from the repository root:

    PYTHONPATH=python:build/cpp python benchmarks/benchmark_python_speed.py \\
        --reps 30 --json /tmp/result.json

To A/B a change against a baseline tree, prepare a pristine ``python/``
directory (e.g. ``git archive <sha> python | tar -x -C /tmp/base``) and pass
``--baseline-pypath /tmp/base/python``: arms then alternate per repetition
inside one session so co-tenant load hits both arms.

Every child strips the environment's scikit-build editable meta-path finder,
which would otherwise import ``bionetgen`` from the shared main worktree and
silently measure the wrong tree.
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
DEFAULT_PYPATH = os.pathsep.join(
    [str(REPO_ROOT / "python"), str(REPO_ROOT / "build" / "cpp")]
)

# Strip scikit-build editable meta-path finders so the subprocess imports the
# tree under test, not the shared main worktree the editable install points at.
_PRELUDE = (
    "import sys\n"
    "sys.meta_path = [\n"
    "    f for f in sys.meta_path\n"
    "    if 'editable' not in type(f).__module__.lower()\n"
    "    and 'editable' not in getattr(f, '__name__', '').lower()\n"
    "]\n"
)

_SPAWN_EVENTS = (
    "subprocess.Popen",
    "os.system",
    "pty.spawn",
)


def _is_spawn_event(event: str) -> bool:
    return (
        event in _SPAWN_EVENTS
        or event.startswith("os.exec")
        or event.startswith("os.posix_spawn")
    )


def _child_env(pypath: str | None) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = pypath or DEFAULT_PYPATH
    return env


def _run_child(code: str, pypath: str | None = None) -> tuple[float, str]:
    """Run `code` in a fresh interpreter; return (wall seconds, stdout)."""
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-c", _PRELUDE + code],
        env=_child_env(pypath),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(
            f"child failed ({proc.returncode}):\n{proc.stderr[-2000:]}"
        )
    return elapsed, proc.stdout


def _loadavg() -> list[float]:
    return list(os.getloadavg())


def _concurrent_benchmarks() -> dict:
    """Contention context: N runnable plus the named timing-sensitive procs.

    Runnable count responds within seconds (memWatch calibration); loadavg is
    reported only as a coarse band elsewhere. The process list is exact.
    """
    try:
        proc = subprocess.run(
            ["ps", "-axo", "pid,state,etime,command"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return {"runnable": None, "processes": []}
    needles = ("bng_cpp", "cc1plus", "clang++", "ninja", "mem_bench", "bench")
    runnable = 0
    hits = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        _, state, rest = parts
        if state.startswith("R"):
            runnable += 1
        if "benchmark_python_speed" in rest:
            continue
        if any(n in rest for n in needles):
            hits.append(f"{parts[0]} {state} {rest.strip()}")
    return {"runnable": runnable, "processes": hits}


def _summarize(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "min_ms": ordered[0] * 1000.0,
        "median_ms": statistics.median(ordered) * 1000.0,
        "max_ms": ordered[-1] * 1000.0,
        "spread_ms": (ordered[-1] - ordered[0]) * 1000.0,
        "all_ms": [round(s * 1000.0, 1) for s in ordered],
        "n": len(ordered),
    }


# ---------------------------------------------------------------- primary ---

_COUNT_CHILD = (
    "import json, sys\n"
    "events = []\n"
    "def _hook(event, args):\n"
    f"    if event in {_SPAWN_EVENTS!r} or event.startswith('os.exec')"
    " or event.startswith('os.posix_spawn'):\n"
    "        events.append(event)\n"
    "sys.addaudithook(_hook)\n"
    "import bionetgen\n"
    "payload = {\n"
    "    'under_test': bionetgen.__file__,\n"
    "    'spawns': len(events),\n"
    "    'events': sorted(set(events)),\n"
    "}\n"
    "print(json.dumps(payload))\n"
)


def bench_spawn_count(reps: int, pypath: str | None) -> dict:
    """Subprocess spawns during a fresh `import bionetgen` (deterministic)."""
    counts: list[int] = []
    under_test = None
    events: list[str] = []
    for _ in range(reps):
        _, stdout = _run_child(_COUNT_CHILD, pypath)
        payload = json.loads(stdout.strip().splitlines()[-1])
        counts.append(payload["spawns"])
        under_test = payload["under_test"]
        events = payload["events"]
    # Resolved-path assertion: the editable finder was stripped iff the child
    # imported THIS tree (or the explicit baseline tree), never the shared one.
    expected_root = (
        str(Path(pypath).resolve()) if pypath else str((REPO_ROOT / "python").resolve())
    )
    resolved = str(Path(under_test).resolve())
    if not resolved.startswith(expected_root):
        raise RuntimeError(
            f"UNDER TEST path assertion failed: {resolved} not under {expected_root}"
        )
    return {
        "name": "subprocess spawns during fresh `import bionetgen`",
        "metric": "count",
        "counts": counts,
        "spawns": counts[0],
        "deterministic": len(set(counts)) == 1,
        "events": events,
        "under_test": under_test,
        "pypath": pypath or DEFAULT_PYPATH,
    }


# -------------------------------------------------------------- secondary ---

_WALL_CHILD = "import bionetgen\n"


def bench_wall(reps: int, pypath: str | None) -> dict:
    """Wall-clock for a fresh `import bionetgen` subprocess."""
    samples = [_run_child(_WALL_CHILD, pypath)[0] for _ in range(reps)]
    return {"name": "import bionetgen wall (fresh subprocess)", **_summarize(samples)}


def bench_cli(reps: int, pypath: str | None) -> dict:
    """CLI startup to first output: bionetgen --help in a fresh subprocess."""
    code = (
        "import sys\n"
        "sys.argv = ['bionetgen', '--help']\n"
        "import runpy\n"
        "runpy.run_module('bionetgen', run_name='__main__')\n"
    )
    samples = [_run_child(code, pypath)[0] for _ in range(reps)]
    return {"name": "bionetgen --help (fresh subprocess)", **_summarize(samples)}


def bench_atomize(reps: int, fixture: str, pypath: str | None) -> dict:
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
        env=_child_env(pypath),
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


# ---------------------------------------------------------------- tertiary ---

_OUTPUT_CHILD = (
    "import hashlib, json\n"
    "import bionetgen\n"
    "banner = bionetgen.defaults.banner\n"
    "payload = {\n"
    "    'under_test': bionetgen.__file__,\n"
    "    'banner': banner,\n"
    "    'banner_sha256': hashlib.sha256(banner.encode('utf-8')).hexdigest(),\n"
    "    'version': bionetgen.__version__,\n"
    "    'spawns_during_access': None,\n"
    "}\n"
    "print(json.dumps(payload))\n"
)

_VERSION_CHILD = (
    "import sys\n"
    "sys.argv = ['bionetgen', '--version']\n"
    "import io, contextlib\n"
    "buf = io.StringIO()\n"
    "import runpy\n"
    "try:\n"
    "    with contextlib.redirect_stdout(buf):\n"
    "        runpy.run_module('bionetgen', run_name='__main__')\n"
    "except SystemExit:\n"
    "    pass\n"
    "print('VERSION_LINE:' + buf.getvalue().strip().splitlines()[0])\n"
)


def bench_outputs(pypath: str | None) -> dict:
    """Byte-level output gate: banner digest, version, --version line."""
    _, stdout = _run_child(_OUTPUT_CHILD, pypath)
    payload = json.loads(stdout.strip().splitlines()[-1])
    _, version_stdout = _run_child(_VERSION_CHILD, pypath)
    version_line = next(
        line for line in version_stdout.splitlines() if line.startswith("VERSION_LINE:")
    )
    payload["version_line"] = version_line[len("VERSION_LINE:"):]
    return payload


# -------------------------------------------------------------------- main ---


def _print_result(record: dict) -> None:
    if record.get("metric") == "count":
        print(
            f"PRIMARY {record['name']}: {record['spawns']} "
            f"(per-rep counts={record['counts']}, deterministic="
            f"{record['deterministic']}, events={record['events']})"
        )
        print(f"  UNDER TEST: {record['under_test']}")
        return
    extra = ""
    if "output_digest" in record:
        extra = (
            f", out_len={record['output_len']} digest={record['output_digest']}"
        )
    print(
        f"  {record['name']}: min {record['min_ms']:.1f} ms, "
        f"spread {record['spread_ms']:.1f} ms, "
        f"median {record['median_ms']:.1f} ms, all={record['all_ms']}{extra}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=30)
    parser.add_argument(
        "--fixture",
        default="tests/validation/Validate/gene_expr_sbml.xml",
        help="small SBML file for the atomizer candidate",
    )
    parser.add_argument(
        "--baseline-pypath",
        default=None,
        help="pristine python/ dir to interleave as the baseline arm",
    )
    parser.add_argument("--json", default=None, help="optional JSON output path")
    parser.add_argument(
        "--skip-candidates",
        action="store_true",
        help="only run the primary count, wall, and output gate",
    )
    args = parser.parse_args()

    load_start = _loadavg()
    live_start = _concurrent_benchmarks()

    results: dict = {"loadavg_start": load_start, "concurrent_start": live_start}

    # PRIMARY: spawn count, deterministic; verify each arm reps times.
    results["spawn_count"] = bench_spawn_count(max(3, args.reps // 10), None)
    if args.baseline_pypath:
        results["spawn_count_baseline"] = bench_spawn_count(
            max(3, args.reps // 10), args.baseline_pypath
        )

    # SECONDARY: wall clock, interleaved per repetition when A/B.
    if args.baseline_pypath:
        arms = {"current": [], "baseline": []}
        for i in range(args.reps):
            arm = "baseline" if i % 2 == 0 else "current"
            pypath = args.baseline_pypath if arm == "baseline" else None
            arms[arm].append(_run_child(_WALL_CHILD, pypath)[0])
        results["wall_current"] = {
            "name": "import bionetgen wall interleaved (current)",
            **_summarize(arms["current"]),
        }
        results["wall_baseline"] = {
            "name": "import bionetgen wall interleaved (baseline)",
            **_summarize(arms["baseline"]),
        }
    else:
        results["wall"] = bench_wall(args.reps, None)

    if not args.skip_candidates:
        results["cli"] = bench_cli(max(7, args.reps // 3), None)
        results["atomize"] = bench_atomize(
            max(7, args.reps // 3), args.fixture, None
        )

    # TERTIARY: output gate.
    results["outputs"] = bench_outputs(None)
    if args.baseline_pypath:
        results["outputs_baseline"] = bench_outputs(args.baseline_pypath)

    results["loadavg_end"] = _loadavg()
    results["concurrent_end"] = _concurrent_benchmarks()

    primary = results["spawn_count"]
    print(
        f"PRIMARY subprocess-spawns-on-import: {primary['spawns']} "
        f"(counts={primary['counts']}, deterministic={primary['deterministic']})"
    )
    print(f"  UNDER TEST: {primary['under_test']}")
    if args.baseline_pypath:
        base = results["spawn_count_baseline"]
        print(
            f"  BASELINE spawns: {base['spawns']} "
            f"(counts={base['counts']}) UNDER TEST: {base['under_test']}"
        )
    for key in ("wall", "wall_current", "wall_baseline", "cli", "atomize"):
        if key in results:
            _print_result(results[key])
    out = results["outputs"]
    print(
        f"  outputs: version={out['version']} "
        f"banner_sha256={out['banner_sha256']} "
        f"version_line={out['version_line']!r}"
    )
    print(
        f"  loadavg band: start={load_start} end={results['loadavg_end']} "
        f"(band, not a precise reading)"
    )
    live_end = results["concurrent_end"]
    print(
        f"  contention: R(start)={live_start['runnable']} "
        f"R(end)={live_end['runnable']} "
        f"timing-sensitive procs start={len(live_start['processes'])} "
        f"end={len(live_end['processes'])}"
    )
    for line in live_start["processes"][:5]:
        print(f"    live: {line[:160]}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(results, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
