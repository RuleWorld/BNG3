"""Regenerate committed golden reference outputs from the Perl oracle.

Golden files are the regression spine: tests load them instead of invoking Perl
on every run. This script is the *only* sanctioned way to (re)populate
tests/validation/golden/. It is run deliberately, reviewed, and committed —
never invoked by the test suite.

Usage:
    python scripts/regen_golden.py --tier p          # all on-disk compatible models
    python scripts/regen_golden.py --models blbr egfr_net
    python scripts/regen_golden.py --tier s --ensemble 200   # also write SSA ensembles

Requires a working Perl BNG2 (set BNG2_PERL, or have legacy/perl/BNG2.pl present).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.validation import corpus, oracle_perl  # noqa: E402

GOLDEN = corpus.REPO / "tests" / "validation" / "golden"


def regen(models: list[str], ensemble: int) -> int:
    if not oracle_perl.perl_available():
        print("ERROR: Perl BNG2 not available (set BNG2_PERL).", file=sys.stderr)
        return 2
    GOLDEN.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    for name in models:
        stem = Path(name).stem
        with tempfile.TemporaryDirectory() as td:
            net, gdat, err = oracle_perl.run_perl(name, Path(td))
            if net is None and gdat is None:
                print(f"  FAIL {stem}: {err}")
                continue
            if net is not None:
                shutil.copy2(net, GOLDEN / f"{stem}.net")
            if gdat is not None:
                shutil.copy2(gdat, GOLDEN / f"{stem}.gdat")
            print(f"  OK   {stem}  "
                  f"({'net ' if net else ''}{'gdat' if gdat else ''})".rstrip())
            n_ok += 1
        # Ensemble goldens for stochastic comparison are intentionally NOT
        # generated here yet: a faithful Perl SSA ensemble needs a fixed-seed
        # sweep wrapper. Tracked as follow-up; the harness skips ensemble tests
        # until <stem>.ens.gdat files exist.
    print(f"\n{n_ok}/{len(models)} models regenerated into {GOLDEN}")
    return 0 if n_ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", choices=["s", "p", "nf", "expr"], default=None)
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--ensemble", type=int, default=0,
                    help="(reserved) number of SSA runs per ensemble golden")
    args = ap.parse_args()

    if args.models:
        models = args.models
    elif args.tier == "s":
        models = corpus.tier_s()
    elif args.tier == "nf":
        models = corpus.tier_nf()
    elif args.tier == "expr":
        models = corpus.tier_expr()
    else:
        models = corpus.tier_p()

    print(f"Regenerating golden for {len(models)} model(s)...")
    return regen(models, args.ensemble)


if __name__ == "__main__":
    raise SystemExit(main())
