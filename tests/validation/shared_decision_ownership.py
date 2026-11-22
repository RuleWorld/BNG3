"""Read-only architecture check for single-owner capability decisions (Issue #178).

The general-energy gate is a semantic decision: when it is off, barrier patterns
and driven reservoirs must be refused everywhere, not approximated by one
backend. ``bng::compile::energy::generalEnergyEnabled()`` in
``cpp/compile/energy/DrivenEnergy.cpp`` is the recorded owner. A writer that
reads the environment variable directly would create a second, drift-prone
decision with no common diagnostic identity.

This module audits the *source* shape; it does not execute any backend. A
negative fixture proves the checker has power to reject a duplicated decision.
"""

from __future__ import annotations

import re
from pathlib import Path

GATE_NAME = "BNG_NFSIM_GENERAL_ENERGY"
OWNER = "cpp/compile/energy/DrivenEnergy.cpp"
ACCESSOR = "generalEnergyEnabled()"

# Direct readers of the gate name outside the owner are duplicated decisions.
# Comments and diagnostics that merely *name* the gate are allowed: they do not
# decide behavior. We look for std::getenv / getenv on the literal gate name.
DIRECT_READ = re.compile(
    r"\b(?:std::)?getenv\s*\(\s*[\"']" + re.escape(GATE_NAME) + r"[\"']\s*\)"
)


def duplicated_gate_readers(root: Path) -> list[str]:
    """Return source paths that read the gate directly outside its owner."""
    owners: list[str] = []
    for path in sorted((root / "cpp").rglob("*")):
        if path.suffix not in {".cpp", ".hpp"}:
            continue
        rel = path.relative_to(root).as_posix()
        if rel == OWNER:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        # Strip comment lines so a diagnostic mentioning the gate is not a hit.
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("//")
        )
        if DIRECT_READ.search(code):
            owners.append(rel)
    return owners


def has_single_owner(root: Path) -> bool:
    """The owner must exist and define the accessor; no other direct reader."""
    owner_text = (root / OWNER).read_text(encoding="utf-8", errors="replace")
    return ACCESSOR in owner_text and not duplicated_gate_readers(root)


def rejects_duplicated_decision(source: str) -> bool:
    """Negative control: a synthetic direct reader must be detected."""
    return DIRECT_READ.search(source) is not None
