#!/usr/bin/env python3
"""Parse-only microbenchmark for the BNGL parser (swarm lane parse-hot).

Times `_bionetgen_cpp.parse_file` alone -- no network generation, no
simulation -- on fixed BNGL inputs, in a fresh interpreter per extension so
two builds can be compared interleaved in one session:

    PYTHONPATH= python3 bench/parse_bench.py --reps 50 --rounds 4 \
        --a <pre-change build>/cpp --b <candidate build>/cpp --json out.json

Each round runs A and B in alternating order.  For every input the child
reports min and median wall seconds over `--reps` parses plus a semantic
guard tuple (parameter / molecule-type / observable / rule / seed-species
counts and a digest of parameter names+values) so an AST-semantics change
fails the run instead of looking like a speedup.

Prerequisites: a Release build of this worktree with Python bindings
(`cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON_BINDINGS=ON
&& cmake --build build --parallel 3`) providing `build/cpp/_bionetgen_cpp*`.
Stdlib only; no network access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Fixed inputs: the two harness models plus a larger one so the per-parse
# number is not dominated by fixed startup costs.
DEFAULT_INPUTS = [
    "models/egfr_net.bngl",
    "bench/fixtures/netgen_egfr.bngl",
    "models/test_partial_dynamical_scaling.bngl",
]

# Pre-import bootstrap shared with bench/run_bench.py: worktree-local sys.path
# first, then drop scikit-build editable MetaPathFinders that would redirect
# the import to another checkout.
_BOOTSTRAP = """\
import sys
ROOT = sys.argv[1]
sys.path.insert(0, ROOT + "/build/cpp")
sys.path.insert(0, ROOT + "/python")
sys.meta_path[:] = [
    f for f in sys.meta_path
    if not type(f).__module__.startswith("_editable")
]
"""


def run_child(ext_dir: Path, reps: int, root: Path, timeout: float = 600.0) -> dict:
    """Run one measurement child against the extension in `ext_dir`."""
    code = _BOOTSTRAP + f"""
import hashlib, json, sys, time
sys.path.insert(0, {str(ext_dir)!r})
sys.path.insert(0, {str(root / "python")!r})
import _bionetgen_cpp as cpp
import pathlib

INPUTS = {DEFAULT_INPUTS!r}
REPS = {reps}
ROOT_PATH = {str(root)!r}

def guard(model):
    params = model.parameters
    pdigest = hashlib.sha256(
        ";".join(f"{{p.name}}={{p.value}}" for p in params).encode()
    ).hexdigest()[:16]
    return [
        len(params),
        len(model.molecule_types),
        len(model.observables),
        len(model.reaction_rules),
        len(model.seed_species),
        pdigest,
    ]

out = {{"times": {{}}, "guards": {{}}, "ext": None}}
for rel in INPUTS:
    path = str(pathlib.Path(ROOT_PATH) / rel)
    model = cpp.parse_file(path)
    g = guard(model)
    del model
    samples = []
    for _ in range(REPS):
        t0 = time.perf_counter()
        m = cpp.parse_file(path)
        samples.append(time.perf_counter() - t0)
        del m
    out["times"][rel] = samples
    out["guards"][rel] = g
out["ext"] = cpp.__file__
print(json.dumps(out))
"""
    proc = subprocess.run(
        [sys.executable, "-c", code, str(root), str(reps)],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(root),
        env={**os.environ, "PYTHONPATH": ""},
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"child for {ext_dir} exited {proc.returncode}\n{proc.stderr.strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"child for {ext_dir} produced non-JSON output: {proc.stdout!r}"
        ) from exc


def load1() -> float:
    try:
        return os.getloadavg()[0]
    except OSError:
        return float("nan")


def stats(samples: list[float]) -> dict:
    ordered = sorted(samples)
    n = len(ordered)
    mid = n // 2
    median = ordered[mid] if n % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])
    mean = sum(ordered) / n
    var = sum((s - mean) ** 2 for s in ordered) / n
    cv = (var**0.5) / mean if mean else 0.0
    return {
        "min": ordered[0],
        "median": median,
        "mean": mean,
        "cv": cv,
        "n": n,
    }


def find_ext(build_cpp: Path) -> Path:
    if not build_cpp.is_dir():
        raise SystemExit(f"extension dir not found: {build_cpp}")
    hits = sorted(build_cpp.glob("_bionetgen_cpp*.so")) + sorted(
        build_cpp.glob("_bionetgen_cpp*.pyd")
    )
    if not hits:
        raise SystemExit(f"no _bionetgen_cpp extension in {build_cpp}")
    return hits[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--a",
        default=str(ROOT / "build" / "cpp"),
        help="extension dir A (default: this worktree's build/cpp)",
    )
    ap.add_argument(
        "--b", default=None, help="extension dir B; enables interleaved A/B rounds"
    )
    ap.add_argument(
        "--reps", type=int, default=50, help="parses per input per round (default 50)"
    )
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument(
        "--inputs",
        nargs="*",
        default=None,
        help="BNGL paths relative to repo root (default: fixed set)",
    )
    ap.add_argument("--json", default=None, help="write full results here")
    args = ap.parse_args()

    global DEFAULT_INPUTS
    if args.inputs:
        DEFAULT_INPUTS = list(args.inputs)

    a_dir = Path(args.a).resolve()
    find_ext(a_dir)
    b_dir = Path(args.b).resolve() if args.b else None
    if b_dir:
        find_ext(b_dir)

    meta = {
        "load1_start": load1(),
        "host": platform.platform(),
        "python": sys.version.split()[0],
        "reps": args.reps,
        "rounds": args.rounds,
        "inputs": DEFAULT_INPUTS,
        "a": str(a_dir),
        "b": str(b_dir) if b_dir else None,
        "a_ext": str(find_ext(a_dir)),
        "b_ext": str(find_ext(b_dir)) if b_dir else None,
        "git": _git_head(),
    }

    # Collect per-input samples per variant.
    collected: dict[str, dict[str, list[float]]] = {
        "a": {rel: [] for rel in DEFAULT_INPUTS},
    }
    guards: dict[str, dict] = {"a": {}}
    if b_dir:
        collected["b"] = {rel: [] for rel in DEFAULT_INPUTS}
        guards["b"] = {}

    order_toggles = 0
    for rnd in range(args.rounds):
        variants = ["a", "b"] if b_dir else ["a"]
        if rnd % 2 == 1:
            variants = variants[::-1]
            order_toggles += 1
        for v in variants:
            ext_dir = a_dir if v == "a" else b_dir
            res = run_child(ext_dir, args.reps, ROOT)
            for rel in DEFAULT_INPUTS:
                collected[v][rel].extend(res["times"][rel])
                g = tuple(res["guards"][rel])
                if rel in guards[v] and guards[v][rel] != g:
                    raise SystemExit(
                        f"guard mismatch for {v}/{rel}: {guards[v][rel]} -> {g}"
                    )
                guards[v][rel] = g

    # Cross-variant guard equality: identical AST semantics required.
    if b_dir:
        for rel in DEFAULT_INPUTS:
            if tuple(guards["a"][rel]) != tuple(guards["b"][rel]):
                raise SystemExit(
                    f"SEMANTICS MISMATCH on {rel}: A={guards['a'][rel]} "
                    f"B={guards['b'][rel]}"
                )

    report = {"meta": meta, "results": {}}
    print(
        f"load1={meta['load1_start']:.1f}  reps={args.reps} "
        f"rounds={args.rounds}  head={meta['git']}"
    )
    for rel in DEFAULT_INPUTS:
        row = {"a": stats(collected["a"][rel])}
        if b_dir:
            row["b"] = stats(collected["b"][rel])
            sa, sb = row["a"]["median"], row["b"]["median"]
            delta = (sb - sa) / sa * 100.0 if sa else 0.0
            row["delta_median_pct"] = delta
            print(
                f"{rel:52s} A(med)={sa * 1e3:8.3f} ms  "
                f"B(med)={sb * 1e3:8.3f} ms  {delta:+6.2f}%"
            )
        else:
            print(
                f"{rel:52s} A(min)={row['a']['min'] * 1e3:8.3f} ms  "
                f"A(med)={row['a']['median'] * 1e3:8.3f} ms  "
                f"cv={row['a']['cv'] * 100:4.1f}%"
            )
        report["results"][rel] = row
    report["meta"]["load1_end"] = load1()
    print(f"load1_end={report['meta']['load1_end']:.1f}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))
        print(f"wrote {args.json}")
    return 0


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
