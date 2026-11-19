#!/usr/bin/env python3
"""Reproduce the NonConsuming false-equality control described in WRONG_CONTROL.md.

Run in an environment whose editable finder points at the pre-fix checkout to
observe the false `equal` verdict; run in the clean installed worktree package
to observe the honest `EqualityUndecided` verdict.
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import bionetgen
from bionetgen import BioNetGenModel
from bionetgen.bngir import EqualityUndecided, semantic_equal
from tests.python.test_delayed_competing_intervention import SOURCE


def main() -> int:
    print("bionetgen from", bionetgen.__file__)
    base = BioNetGenModel(bionetgen.model._cpp.parse_string(SOURCE))
    variant = BioNetGenModel(
        bionetgen.model._cpp.parse_string(
            SOURCE.replace(" delay=tau NonConsuming", " delay=tau")
        )
    )
    counts: collections.Counter = collections.Counter()
    for _ in range(200):
        try:
            counts["equal" if semantic_equal(base, variant) else "not_equal"] += 1
        except EqualityUndecided:
            counts["undecided"] += 1
    print(dict(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
