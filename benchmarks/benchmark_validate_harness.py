#!/usr/bin/env python3
"""Benchmark the reference-validation harness on a fixed subset of models.

The subset consists of the models that dominate ``scripts/validate.py`` wall
time: their network comparisons account for nearly all of the Python-side
cost of a full validation run, while their ``bng_cpp`` generation cost stays
small.  The benchmark runs the real harness path (``run_validation`` from
``scripts/validate.py``) so the measured number is the number a developer
waits on.

Primary number: mean wall time (seconds) of one ``run_validation`` pass over
the subset, plus the standard deviation across repeats.  The compare-phase
subtotal is printed as a secondary diagnostic.  ``species_isomorphic`` is an
``lru_cache``; its cache is cleared before every repeat so every repeat does
the same work as a fresh process.

Usage:
    python benchmarks/benchmark_validate_harness.py \
        --bng-cpp build/cpp/bng_cpp --repeats 5
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import validate as validate_module  # noqa: E402
from tests.validation import compare  # noqa: E402

# The five models whose compare_net calls dominate harness wall time
# (measured: 68.9 s of the 69.4 s compare total across all 61 models).
SUBSET = [
    "test_network_gen",
    "isingspin_energy",
    "egfr_net",
    "fceri_ji",
    "SHP2_base_model",
]

# compare_net is the phase the harness spends the most time in; wrapping the
# name validate.py binds lets the benchmark report the compare-phase subtotal
# without re-implementing run_validation.
_compare_phase = 0.0
_orig_compare_net = validate_module.compare_net


def _timed_compare_net(*args, **kwargs):
    global _compare_phase
    start = time.perf_counter()
    try:
        return _orig_compare_net(*args, **kwargs)
    finally:
        _compare_phase += time.perf_counter() - start


validate_module.compare_net = _timed_compare_net


def _clear_caches() -> None:
    """Drop memoized comparison state so each repeat does full work."""

    compare.species_isomorphic.cache_clear()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark scripts/validate.py on a fixed model subset"
    )
    parser.add_argument(
        "--bng-cpp",
        type=Path,
        default=REPO / "build" / "cpp" / "bng_cpp",
        help="Path to the bng_cpp executable",
    )
    parser.add_argument("--repeats", type=int, default=5, help="Repetitions")
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write machine-readable results to this path",
    )
    args = parser.parse_args()

    bng_cpp = args.bng_cpp.resolve()
    if not bng_cpp.exists():
        print(f"ERROR: bng_cpp not found at {bng_cpp}", file=sys.stderr)
        return 1

    validate_dir = REPO / "tests" / "validation" / "Validate"
    all_models = {path.stem for path in validate_dir.glob("*.bngl")}
    missing = [name for name in SUBSET if name not in all_models]
    if missing:
        print(f"ERROR: subset models missing: {', '.join(missing)}", file=sys.stderr)
        return 1
    skip = sorted(all_models - set(SUBSET))

    print(f"subset: {', '.join(SUBSET)}")
    print(f"repeats: {args.repeats}")
    print()

    walls: list[float] = []
    compare_phases: list[float] = []
    for repeat in range(args.repeats):
        global _compare_phase
        _compare_phase = 0.0
        _clear_caches()
        start = time.perf_counter()
        results, details = validate_module.run_validation(
            bng_cpp,
            validate_dir,
            skip_models=skip,
            strict_references=True,
            action_models=[],
            molecule_name_aliases_by_model={},
        )
        wall = time.perf_counter() - start
        if results["fail"] or results["error"]:
            for line in details:
                print(line, file=sys.stderr)
            print(
                f"ERROR: subset validation not clean: {results}",
                file=sys.stderr,
            )
            return 1
        if results["pass"] != len(SUBSET):
            print(
                f"ERROR: expected {len(SUBSET)} passes, got {results['pass']}",
                file=sys.stderr,
            )
            return 1
        walls.append(wall)
        compare_phases.append(_compare_phase)
        print(
            f"repeat {repeat + 1}: wall {wall:7.2f}s "
            f"(compare {_compare_phase:6.2f}s)"
        )

    mean = statistics.mean(walls)
    stdev = statistics.stdev(walls) if len(walls) > 1 else 0.0
    print()
    print(
        f"PRIMARY  mean wall {mean:.2f}s  +/- {stdev:.2f}s stdev "
        f"(min {min(walls):.2f}s, max {max(walls):.2f}s, n={len(walls)})"
    )
    print(f"secondary  mean compare phase {statistics.mean(compare_phases):.2f}s")

    if args.json:
        payload = {
            "subset": SUBSET,
            "repeats": args.repeats,
            "wall_seconds": walls,
            "compare_seconds": compare_phases,
            "wall_mean": mean,
            "wall_stdev": stdev,
        }
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
