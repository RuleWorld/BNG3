#!/usr/bin/env python3
"""Recognize only the two known Species proof rejections, not arbitrary build failures."""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Each expected theorem maps to (leading error message, marker that must appear
# in that theorem's OWN diagnostic block). A marker of None means the leading
# message alone identifies the rejection. Binding a semantic marker to the
# theorem whose proof actually failed (rather than searching the whole log)
# prevents a stray string elsewhere from satisfying the classifier.
EXPECTED = {
    "coverage-species-bond-blind": {
        "SpeciesIsoMap.validFor_bond_count": (
            "Type mismatch",
            "left.bonds.length = right.bonds.length",
        ),
        "SpeciesIsoMap.validFor_bijective": ("Invalid projection", None),
        "SpeciesIsoMap.validFor_molecules": ("Invalid projection", None),
        "SpeciesIsoMap.validFor_bondsForward": (
            "Type mismatch",
            "bondsPreservedForward left right m = true",
        ),
        "isomorphicSpecies_counts": ("Invalid projection", None),
    },
    "coverage-network-duplicate-species": {
        "addSpeciesModuloIso_preserves_existing": ("Type mismatch", None),
        "addSpeciesModuloIso_contains_candidate_or_iso": (
            "unsolved goals",
            "⊢ candidate ∈ pool",
        ),
        "addSpeciesModuloIso_length": ("unsolved goals", "⊢ False"),
        "addSpeciesModuloIso_empty": ("unsolved goals", None),
    },
}
# Total error diagnostics expected for each mutation. The bond-blind mutation
# legitimately produces two errors for isomorphicSpecies_counts, so this is an
# error count, not the number of distinct expected theorems.
EXPECTED_ERROR_COUNTS = {
    "coverage-species-bond-blind": 6,
    "coverage-network-duplicate-species": 4,
}

# A top-level declaration opens a new body boundary. Errors are attributed to
# the nearest preceding declaration. Tracking def/lemma/etc. AND theorem (not
# just theorem) is what stops an error inside an unrelated definition from
# being attributed to the theorem above it -- the hole demonstrated against
# the merged #707 classifier.
_DECLARATION = re.compile(
    r"^(?:(?:private|protected|noncomputable|unsafe|partial|local)\s+)*"
    r"(theorem|lemma|def|abbrev|axiom|example|instance|structure|inductive|class|opaque)\s+"
    r"([\w.]+)\b"
)
_ERROR = re.compile(r"^error: BNG/Species\.lean:(\d+):\d+: (.*)$")
# These "error:" lines are build summaries, not declaration diagnostics.
_SUMMARY_ERRORS = {"error: Lean exited with code 1", "error: build failed"}
_BLOCK_START = re.compile(r"^(?:error|warning|info|trace): ")
_FAILURE = re.compile(r"^\s*- (BNG\.[\w.]+)\s*$", re.MULTILINE)


def declaration_ranges(source):
    """Return [(name, start_line, end_line)] for each top-level declaration."""
    starts = []
    for line_no, line in enumerate(source.splitlines(), 1):
        # A block-comment continuation such as "structure via ... -/" is not a
        # declaration, even though it starts with a declaration keyword.
        if line.rstrip().endswith("-/"):
            continue
        match = _DECLARATION.match(line)
        if match:
            starts.append((line_no, match.group(2)))
    ranges = []
    for index, (line_no, name) in enumerate(starts):
        end = starts[index + 1][0] - 1 if index + 1 < len(starts) else None
        ranges.append((name, line_no, end))
    return ranges


def error_blocks(output):
    """Return [(line_no, message, block_text)] per Species error, or None.

    None means an error line was found that is neither a known build summary
    nor a diagnostic against BNG/Species.lean (e.g. another module or a missing
    tool), which must never count as the expected rejection.
    """
    lines = output.splitlines()
    blocks = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("error:") and line not in _SUMMARY_ERRORS:
            match = _ERROR.match(line)
            if match is None:
                return None
            block = [line]
            index += 1
            while index < len(lines) and not _BLOCK_START.match(lines[index]):
                if lines[index].startswith("Some required targets logged failures:"):
                    break
                block.append(lines[index])
                index += 1
            blocks.append((int(match.group(1)), match.group(2), "\n".join(block)))
        else:
            index += 1
    return blocks


def matches(name: str, source: str, output: str) -> bool:
    expected = EXPECTED.get(name)
    if expected is None:
        return False

    # Only the BNG.Species target may be reported as a failing module.
    if _FAILURE.findall(output) != ["BNG.Species"]:
        return False

    blocks = error_blocks(output)
    if blocks is None or len(blocks) != EXPECTED_ERROR_COUNTS[name]:
        return False

    ranges = declaration_ranges(source)
    markers_by_theorem = {theorem: [] for theorem in expected}
    found = []
    for line_no, message, block in blocks:
        # Attribute the error to the declaration whose body actually contains
        # it. An error in a def (or past the last declaration) is not a proof
        # rejection of an expected theorem and must not inherit its name.
        theorem = next(
            (
                decl_name
                for decl_name, start, end in ranges
                if start <= line_no and (end is None or line_no <= end)
            ),
            None,
        )
        if theorem not in expected:
            return False
        expected_message, marker = expected[theorem]
        if not message.startswith(expected_message):
            return False
        found.append(theorem)
        if marker is not None:
            markers_by_theorem[theorem].append(marker in block)

    if len(found) != EXPECTED_ERROR_COUNTS[name] or set(found) != set(expected):
        return False
    for theorem, (_message, marker) in expected.items():
        if marker is not None and not any(markers_by_theorem[theorem]):
            return False
    return True


def main() -> int:
    name, source, output = sys.argv[1:]
    return 0 if matches(name, Path(source).read_text(), Path(output).read_text()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
