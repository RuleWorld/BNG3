"""Model corpus, tiered.

Tier-S  smoke    ~10 models, every commit (< 60s)
Tier-P  parity   the exact model IDs committed in the corpus selection manifest
                 (generated from the on-disk tree until a RuleHub selector is approved)
Tier-NF network-free models, compared against the native NFsim oracle

The committed selection manifest is authoritative when present. A model is only
usable when its .bngl still exists on disk; the dedicated manifest validator
also checks every recorded digest. The BNG2-compatible list is an *allowlist*,
not the source of paths — those names come from a different repo tree and need
not exist here.
"""

from __future__ import annotations

import os
import json
import re
from functools import lru_cache
from pathlib import Path

# Repo root: tests/validation/corpus.py -> repo/
REPO = Path(__file__).resolve().parents[2]
SELECTION_MANIFEST = REPO / "provenance" / "corpus" / "selection.json"

# Directories searched for .bngl models, in priority order.
MODEL_DIRS = [
    REPO / "models",
    REPO / "tests" / "validation" / "Validate",
]

# Smoke set. Small, fast, and deliberately includes the symmetry-heavy models
# used to investigate WO-1a; active expected failures live only in exceptions.json.
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

# The recorded justification of every tier: what the tier qualifies, who
# owns it, what it costs and which capability it exercises.  A tier that is
# empty records why it is empty, so an empty selection is reported rather
# than hidden.  The selection itself stays pending maintainer approval.
TIER_JUSTIFICATIONS = {
    "s": {
        "question": (
            "every-commit smoke coverage of the parser, the network expansion "
            "and the observable projection"
        ),
        "owner": "validation and release role",
        "capability": "network.expansion",
        "budget": {"models": 10, "stage_timeout_seconds": 60},
    },
    "p": {
        "question": (
            "legacy agreement of the generated network with the canonical BNG2 "
            "oracle over the frozen repository fixtures"
        ),
        "owner": "numerical and stochastic validation",
        "capability": "network.expansion",
        "budget": {"models": 106, "stage_timeout_seconds": 180},
    },
    "nf": {
        "question": (
            "network-free trajectory comparison with the independently built "
            "native NFsim oracle"
        ),
        "owner": "NFsim semantics and stochastic validation",
        "capability": "nfsim.direct-ast",
        "budget": {"models": 4, "stage_timeout_seconds": 300},
    },
    "expr": {
        "question": (
            "expression and rate-law agreement of the right-hand side with the "
            "oracle to 1e-9"
        ),
        "owner": "expression and rate-law semantics",
        "capability": "compiler.rate-laws",
        "budget": {"models": 5, "stage_timeout_seconds": 300},
    },
    "x": {
        "question": (
            "semantic round trip of the supported interchange formats and the "
            "consumption of the written artifacts by their downstream readers"
        ),
        "owner": "pending-maintainer",
        "capability": "export.sbml",
        "budget": {"models": 0, "stage_timeout_seconds": 300},
        "empty_reason": (
            "The format tier is empty because its RuleHub selector and its "
            "maintainer-owned budget are not approved yet. The empty "
            "selection is recorded here instead of being hidden."
        ),
    },
    "b": {
        "question": (
            "runtime and memory budget of the stress tier on the supported " "hardware"
        ),
        "owner": "pending-maintainer",
        "capability": "simulation.ode",
        "budget": {"models": 0, "stage_timeout_seconds": 1800},
        "empty_reason": (
            "The stress tier is empty because its RuleHub selector and its "
            "maintainer-owned budget are not approved yet. The empty "
            "selection is recorded here instead of being hidden."
        ),
    },
}

# The accepted selections are empty by record: no tier membership has been
# approved by a maintainer, so the pending selection is not an approval.
ACCEPTED_SELECTION_NOTE = (
    "No tier membership is approved, so the accepted selection set is empty "
    "by record and not by omission. The selected models and the separate "
    "71-model workflow are reconciled in the reconciliation record."
)

_OBSERVABLE = re.compile(r"^[ \t]*(?:Molecules|Species)[ \t]+(.+?)[ \t]*$", re.M)


def observable_names(text: str) -> list[str]:
    """The observable names a model declares, in declaration order."""
    names = []
    for match in _OBSERVABLE.finditer(text):
        fields = match.group(1).split()
        if fields:
            names.append(fields[0])
    return names


def header_description(text: str) -> str:
    """The first descriptive comment of a model, without its comment marks."""
    head = re.split(
        r"^[ \t]*begin[ \t]+(parameters|model|species|molecule|functions)",
        text,
        maxsplit=1,
        flags=re.M,
    )[0]
    lines = []
    for line in head.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        content = stripped.lstrip("#").strip()
        if not content or set(content) <= {"=", "-"}:
            continue
        lines.append(content)
    if not lines:
        return ""
    description = " ".join(lines)
    if len(description) > 160:
        description = description[:157].rstrip() + "..."
    return description


def selection_reason(text: str, tier: str, relative_path: str) -> str:
    """The recorded reason why a model is selected into a tier.

    The reason names the tier's recorded question and the model's own
    declared content, so it is specific to that model and can be re-derived
    from the model file.
    """
    question = TIER_JUSTIFICATIONS[tier]["question"]
    description = header_description(text)
    names = observable_names(text)
    if description:
        evidence = f'{relative_path} documents itself as "{description}"'
    elif names:
        listed = ", ".join(names[:3])
        if len(names) > 3:
            listed += f" and {len(names) - 3} more"
        evidence = f"{relative_path} publishes {listed}"
    else:
        evidence = f"{relative_path} declares no observable"
    return f"tier {tier}: {question}; {evidence}"


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


@lru_cache(maxsize=1)
def _selection_manifest() -> dict | None:
    """Load the committed tier selection, if present.

    A malformed or incomplete committed manifest is an integration error, not
    permission to silently fall back to live filesystem discovery.  The
    dedicated manifest validator provides the detailed diagnostics; this
    loader keeps test selection deterministic in the meantime.
    """
    if not SELECTION_MANIFEST.is_file():
        return None
    try:
        value = json.loads(SELECTION_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read corpus selection manifest: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("tiers"), dict):
        raise RuntimeError("corpus selection manifest must contain a tiers object")
    return value


def _selected_tier(tier: str, fallback: list[str]) -> list[str]:
    manifest = _selection_manifest()
    if manifest is None:
        return _exists(fallback)
    selected = manifest["tiers"].get(tier)
    if not isinstance(selected, list) or any(
        not isinstance(name, str) for name in selected
    ):
        raise RuntimeError(f"corpus selection manifest has invalid tiers.{tier}")
    missing = [name for name in selected if resolve(name) is None]
    if missing:
        raise RuntimeError(
            f"corpus selection manifest references missing {tier} model(s): "
            + ", ".join(missing)
        )
    return list(selected)


def tier_s() -> list[str]:
    return _selected_tier("s", TIER_S)


def tier_nf() -> list[str]:
    return _selected_tier("nf", TIER_NF)


def tier_expr() -> list[str]:
    return _selected_tier("expr", TIER_EXPR)


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
    manifest = _selection_manifest()
    if manifest is not None:
        return _selected_tier("p", [])
    idx = _index()
    allow = _allowlist()
    names = sorted(idx)
    if allow:
        names = [n for n in names if n in allow]
    return names


def tier_x() -> list[str]:
    """Format-conversion tier from the committed selection manifest."""
    return _selected_tier("x", [])


def tier_b() -> list[str]:
    """Benchmark/stress tier from the committed selection manifest."""
    return _selected_tier("b", [])


if __name__ == "__main__":
    print(f"repo: {REPO}")
    print(f"tier-S  ({len(tier_s())}): {tier_s()}")
    print(f"tier-NF ({len(tier_nf())}): {tier_nf()}")
    print(
        f"tier-P  ({len(tier_p())}) models on disk"
        f"{' (allowlist-filtered)' if _allowlist() else ''}"
    )
