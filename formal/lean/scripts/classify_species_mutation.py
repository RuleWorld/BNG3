#!/usr/bin/env python3
"""Recognize only the two known Species proof rejections, not arbitrary build failures."""

from __future__ import annotations

import re
import sys
from pathlib import Path

EXPECTED = {
    "coverage-species-bond-blind": {
        "SpeciesIsoMap.validFor_bond_count": "Type mismatch",
        "SpeciesIsoMap.validFor_bijective": "Invalid projection",
        "SpeciesIsoMap.validFor_molecules": "Invalid projection",
        "SpeciesIsoMap.validFor_bondsForward": "Type mismatch",
        "isomorphicSpecies_counts": "Invalid projection",
    },
    "coverage-network-duplicate-species": {
        "addSpeciesModuloIso_preserves_existing": "Type mismatch",
        "addSpeciesModuloIso_contains_candidate_or_iso": "unsolved goals",
        "addSpeciesModuloIso_length": "unsolved goals",
        "addSpeciesModuloIso_empty": "unsolved goals",
    },
}
MARKERS = {
    "coverage-species-bond-blind": (
        "left.bonds.length = right.bonds.length",
        "bondsPreservedForward left right m = true",
    ),
    "coverage-network-duplicate-species": ("⊢ candidate ∈ pool", "⊢ False"),
}


def matches(name: str, source: str, output: str) -> bool:
    expected = EXPECTED.get(name)
    if expected is None or not all(marker in output for marker in MARKERS[name]):
        return False
    failures = re.findall(r"^\s*- (BNG\.[\w.]+)\s*$", output, re.MULTILINE)
    if failures != ["BNG.Species"]:
        return False
    declarations = []
    for line_no, line in enumerate(source.splitlines(), 1):
        match = re.match(r"theorem\s+([\w.]+)\b", line)
        if match:
            declarations.append((line_no, match.group(1)))
    found = []
    for line in output.splitlines():
        if not line.startswith("error:"):
            continue
        if line in ("error: Lean exited with code 1", "error: build failed"):
            continue
        match = re.match(r"error: BNG/Species\.lean:(\d+):\d+: (.*)", line)
        if not match:
            return False
        line_no, message = int(match.group(1)), match.group(2)
        theorem = next((n for pos, n in reversed(declarations) if pos <= line_no), None)
        if theorem not in expected or not message.startswith(expected[theorem]):
            return False
        found.append(theorem)
    expected_count = 6 if name == "coverage-species-bond-blind" else 4
    return len(found) == expected_count and set(found) == set(expected)


def main() -> int:
    name, source, output = sys.argv[1:]
    return 0 if matches(name, Path(source).read_text(), Path(output).read_text()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
