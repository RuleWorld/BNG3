"""Eyeball localfunc's per-species local-function rates: C++ engine vs Perl.

localfunc is the one "naming difference" that is NOT purely cosmetic: its local
function f_synth(x) is evaluated per species, and Perl emits one derived rate
parameter per distinct local context (__R1_local1, __R1_local2, ...). A
name-only difference is fine; a difference in the NUMBER of contexts or in which
reaction maps to which value is a real physics bug.

The automated gate (compare_net rate_mode="value") already catches a value
mismatch. This script is for the first look: it prints both sides' resolved
rate per reaction so you can confirm count + mapping agree before trusting the
gate, per the two-round rule.

Usage:
    python scripts/check_localfunc_rates.py --bng-cpp build/bng_cpp [--model localfunc]
Requires the Perl oracle (golden or live) for the reference side.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.validation import compare, oracle_perl, runner  # noqa: E402


def _resolved_rows(net: compare.Network):
    """Yield (reactants, products, resolved_rate_key) for every reaction."""
    rows = []
    for reactants, products, rate in net._raw:
        try:
            r = tuple(sorted(net.species_by_index[i] for i in reactants))
            p = tuple(sorted(net.species_by_index[i] for i in products))
        except KeyError:
            r = tuple(f"?{i}" for i in sorted(reactants))
            p = tuple(f"?{i}" for i in sorted(products))
        key = compare._resolve_rate(rate, net.rate_defs, "value")
        raw_key = compare._resolve_rate(rate, net.rate_defs, "string")
        rows.append((r, p, raw_key, key))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bng-cpp", required=True)
    ap.add_argument("--model", default="localfunc")
    args = ap.parse_args()

    bng_cpp = Path(args.bng_cpp)
    with tempfile.TemporaryDirectory() as td:
        ref_path, ref_src = oracle_perl.net(args.model, Path(td) / "perl")
        if ref_path is None:
            print(f"no reference .net for {args.model}: {ref_src}", file=sys.stderr)
            return 2
        test_net, _, err = runner.run_cli(bng_cpp, args.model, Path(td) / "cpp")
        if test_net is None:
            print(f"engine produced no .net: {err}", file=sys.stderr)
            return 2

        ref = compare.parse_net(ref_path)
        test = compare.parse_net(test_net)
        ref_rows = _resolved_rows(ref)
        test_rows = _resolved_rows(test)

        print(f"\n=== {args.model}: reference ({ref_src}) ===")
        print(
            f"reactions: {len(ref_rows)}   generated rate params: "
            f"{sum(1 for k in ref.rate_defs if k.startswith(('rateLaw','_rateLaw','__R')))}"
        )
        for r, p, raw, val in ref_rows:
            print(f"  {' + '.join(r)} -> {' + '.join(p)}   name={raw:<14} value={val}")

        print(f"\n=== {args.model}: C++ engine ===")
        print(
            f"reactions: {len(test_rows)}   generated rate params: "
            f"{sum(1 for k in test.rate_defs if k.startswith(('rateLaw','_rateLaw','__R')))}"
        )
        for r, p, raw, val in test_rows:
            print(f"  {' + '.join(r)} -> {' + '.join(p)}   name={raw:<14} value={val}")

        diff = compare.compare_net(ref, test)
        print(f"\n=== value-mode parity: {'OK' if diff.ok else 'MISMATCH'} ===")
        if not diff.ok:
            print(diff.summary())
            print(
                "\nIf the VALUES match and only NAMES differ, this is cosmetic "
                "(comparator passes in value-mode). If values or counts differ, "
                "it's a local-function evaluation bug, not naming."
            )
        return 0 if diff.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
