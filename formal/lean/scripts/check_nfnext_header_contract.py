#!/usr/bin/env python3
"""Fail loudly if the NFnext C++ contract mirrored by Lean drifts.

This is intentionally simple textual validation.  The compiled contract test is
stronger for behavior; this script catches enum/field vocabulary changes early.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
NF = ROOT / "cpp" / "nfnext" / "include" / "nfnext"

checks = {
    NF / "transformation.hpp": [
        "SetState", "AddBond", "DeleteBond", "CreateMolecule",
        "AddBondExistingToCreated", "AddBondCreated",
        "DestroyMolecule", "DestroyComplex",
    ],
    NF / "nfir.hpp": [
        "StateSet", "Free", "Bound", "MolecularityConstraint",
        "SameComplex", "DifferentComplex", "connected_to", "interchangeable",
    ],
}

errors = []
for path, tokens in checks.items():
    if not path.exists():
        errors.append(f"missing {path}")
        continue
    text = path.read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            errors.append(f"{path.name}: expected token {token!r} not found")

if errors:
    print("NFNEXT HEADER CONTRACT FAILED")
    for error in errors:
        print(" -", error)
    sys.exit(1)

print("NFNEXT HEADER CONTRACT PASS")
