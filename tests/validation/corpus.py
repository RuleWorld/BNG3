"""Model corpus, tiered.

Tier-S  smoke    ~10 models, every commit (< 60s)
Tier-P  parity   every .bngl that physically exists in the repo, filtered to the
                 BNG2-compatible allowlist when that list is provided; nightly + WO completion
Tier-NF network-free models, compared against the native NFsim oracle

Discovery is filesystem-based: a model is only in a tier if its .bngl exists on
disk. The BNG2-compatible list is an *allowlist*, not the source of paths —
those names come from a different repo tree and need not exist here.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

# Repo root: tests/validation/corpus.py -> repo/
REPO = Path(__file__).resolve().parents[2]

# Directories searched for .bngl models, in priority order.
MODEL_DIRS = [
    REPO / "models",
    REPO / "tests" / "validation" / "Validate",
]

# Smoke set. Small, fast, and deliberately includes the two known over-count
# models so the harness proves it detects the bug WO-1 fixes.
TIER_S = [
    "simple_system",
    "gene_expr",
    "michment",
    "blbr",
    "Motivating_example",
    "Motivating_example_cBNGL",
    "egfr_net",
    "Repressilator",
    "CaOscillate_Func",
    "localfunc",
]

# Network-free set (relative to MODEL_DIRS / nfsim test trees).
TIER_NF = [
    "simple_system",
    "tlbr",
    "motor",
    "localfunc",
]

# Function/expression-heavy models; RHS must match the oracle to 1e-9.
TIER_EXPR = [
    "localfunc",
    "isingspin_localfcn",
    "isingspin_energy",
    "CaOscillate_Func",
    "michment",
]


@lru_cache(maxsize=1)
def _index() -> dict[str, Path]:
    """Map model stem -> first matching .bngl path found on disk."""
    idx: dict[str, Path] = {}
    for d in MODEL_DIRS:
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.bngl")):
            idx.setdefault(p.stem, p)
    return idx


def resolve(name: str) -> Path | None:
    """Resolve a model stem (or relative path) to an on-disk .bngl."""
    idx = _index()
    if name in idx:
        return idx[name]
    # Allow 'tlbr/tlbr'-style relative references.
    stem = Path(name).stem
    return idx.get(stem)


def _exists(names: list[str]) -> list[str]:
    return [n for n in names if resolve(n) is not None]


def tier_s() -> list[str]:
    return _exists(TIER_S)


def tier_nf() -> list[str]:
    return _exists(TIER_NF)


def tier_expr() -> list[str]:
    return _exists(TIER_EXPR)


@lru_cache(maxsize=1)
def _allowlist() -> set[str] | None:
    """Stems from bng2_compatible_models.txt, if present.

    The file is a directory-tree dump in a non-UTF-8 encoding. Decode tolerantly
    and pull every *.bngl stem.
    """
    for candidate in [
        REPO / "bng2_compatible_models.txt",
        Path(os.environ.get("BNG2_COMPATIBLE_LIST", "")),
    ]:
        if candidate and candidate.is_file():
            raw = candidate.read_bytes().decode("latin-1", errors="replace")
            stems = {Path(m).stem for m in re.findall(r"[\w./-]+\.bngl", raw)}
            return stems or None
    return None


def tier_p() -> list[str]:
    """All on-disk models, filtered to the BNG2-compatible allowlist if present."""
    idx = _index()
    allow = _allowlist()
    names = sorted(idx)
    if allow:
        names = [n for n in names if n in allow]
    return names


if __name__ == "__main__":
    print(f"repo: {REPO}")
    print(f"tier-S  ({len(tier_s())}): {tier_s()}")
    print(f"tier-NF ({len(tier_nf())}): {tier_nf()}")
    print(f"tier-P  ({len(tier_p())}) models on disk"
          f"{' (allowlist-filtered)' if _allowlist() else ''}")
