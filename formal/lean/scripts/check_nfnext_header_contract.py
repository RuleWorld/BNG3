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
    NF
    / "transformation.hpp": [
        "SetState",
        "AddBond",
        "DeleteBond",
        "CreateMolecule",
        "AddBondExistingToCreated",
        "AddBondCreated",
        "DestroyMolecule",
        "DestroyComplex",
    ],
    NF
    / "nfir.hpp": [
        "StateSet",
        "Free",
        "Bound",
        "MolecularityConstraint",
        "SameComplex",
        "DifferentComplex",
        "connected_to",
        "interchangeable",
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

# Keep one executable semantic slice visibly identical across the proof-friendly
# Lean reference and the production parser/CompiledModel/NFIR boundary test.
# Behavioral equality is checked by the compiled tests; this textual guard makes
# fixture drift fail early in the lightweight formal job as well.
bridge_rule = "A(x~u) + B(y) -> A(x~p!1).B(y!1)"
bridge_files = {
    ROOT
    / "formal"
    / "lean"
    / "BNG"
    / "Examples.lean": [bridge_rule, "nfnextBridgeContract_holds"],
    ROOT
    / "tests"
    / "architecture_contracts"
    / "nfnext"
    / "test_bng_lowering_bridge.cpp": [bridge_rule, "lowerFromBioNetGen"],
}
for path, tokens in bridge_files.items():
    if not path.exists():
        errors.append(f"missing {path}")
        continue
    text = path.read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            errors.append(f"{path.name}: bridge token {token!r} not found")

if errors:
    print("NFNEXT HEADER CONTRACT FAILED")
    for error in errors:
        print(" -", error)
    sys.exit(1)

print("NFNEXT HEADER CONTRACT PASS")
