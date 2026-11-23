"""Read-only check for the single-owner poplevel decision (Issue #178).

The finite/non-negative PSA population-level rule must be implemented once, in
the compile-owned module, with both the compile-time default and the runtime
action override delegating to it. A second inline copy would let the layers
disagree about the same user input.
"""

from __future__ import annotations

import re
from pathlib import Path

OWNER_DECL = "poplevelDecisionError"
DIRECT_TEST = re.compile(r"poplevel\s*<\s*0\.0")


def inline_decision_sites(root: Path) -> list[str]:
    """Return files still making the poplevel finite/non-negative decision inline."""
    sites: list[str] = []
    for rel in ("cpp/compile/Document.cpp", "cpp/actions/ActionDispatch.cpp"):
        text = (root / rel).read_text(encoding="utf-8")
        # The owner itself defines the decision; only flag other inline tests.
        code_lines = [
            line for line in text.splitlines() if not line.lstrip().startswith("//")
        ]
        for line in code_lines:
            if DIRECT_TEST.search(line) and OWNER_DECL not in line:
                sites.append(f"{rel}: {line.strip()}")
    return sites


def has_single_owner(root: Path) -> bool:
    header = (root / "cpp" / "compile" / "Document.hpp").read_text(encoding="utf-8")
    source = (root / "cpp" / "compile" / "Document.cpp").read_text(encoding="utf-8")
    action = (root / "cpp" / "actions" / "ActionDispatch.cpp").read_text(
        encoding="utf-8"
    )
    return (
        OWNER_DECL in header
        and f"{OWNER_DECL}(" in source
        and f"bng::compile::{OWNER_DECL}" in action
        and not inline_decision_sites(root)
    )
