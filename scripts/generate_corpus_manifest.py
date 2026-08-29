#!/usr/bin/env python3
"""Generate the deterministic validation-corpus selection manifest.

The manifest freezes the exact model IDs used by each validation tier and
records the source-lock digest that selected them.  It intentionally contains
repository fixtures only until maintainers approve RuleHub selectors; no test
should infer a broader external corpus from compatibility metadata at runtime.

Usage:
    python scripts/generate_corpus_manifest.py
    python scripts/generate_corpus_manifest.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.validation import corpus  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO / "provenance" / "corpus" / "selection.json"
LOCK_PATH = REPO / "provenance" / "upstreams.lock.yml"
SCHEMA_PATH = "provenance/schemas/corpus-selection.schema.json"
TIERS = ("s", "p", "nf", "expr", "x", "b")


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def _filesystem_tier_p() -> list[str]:
    index = corpus._index()
    allowlist = corpus._allowlist()
    names = sorted(index)
    if allowlist:
        names = [name for name in names if name in allowlist]
    return names


def build_manifest() -> dict[str, Any]:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    lock_rulehub = lock["sources"]["rulehub"]

    requested = {
        "s": list(corpus.TIER_S),
        "p": _filesystem_tier_p(),
        "nf": list(corpus.TIER_NF),
        "expr": list(corpus.TIER_EXPR),
        # Translation and benchmark selectors are intentionally empty until
        # their maintainer-owned RuleHub policies are approved.
        "x": [],
        "b": [],
    }

    resolved: dict[str, Path] = {}
    tier_ids: dict[str, list[str]] = {}
    for tier, names in requested.items():
        ids: list[str] = []
        for name in names:
            path = corpus.resolve(name)
            if path is None:
                raise ValueError(f"tier {tier} references missing model {name!r}")
            ids.append(name)
            resolved.setdefault(name, path)
        tier_ids[tier] = sorted(set(ids))

    records = []
    for model_id in sorted(resolved):
        path = resolved[model_id]
        records.append(
            {
                "id": model_id,
                "path": path.relative_to(REPO).as_posix(),
                "sha256": digest(path),
                "origin": "repository-fixture",
                "tiers": [tier for tier in TIERS if model_id in tier_ids[tier]],
            }
        )

    return {
        "$schema": SCHEMA_PATH,
        "schema_version": 1,
        "selection_status": "pending-maintainer-approval",
        "source_lock": {
            "path": LOCK_PATH.relative_to(REPO).as_posix(),
            "sha256": digest(LOCK_PATH),
        },
        "rulehub": {
            "repository": lock_rulehub["repository"],
            "revision": lock_rulehub["revision"],
            "status": "pending-maintainer-approval",
            "policy": (
                "Repository fixtures are frozen; RuleHub selectors and external "
                "tier membership require maintainer approval."
            ),
        },
        "tiers": tier_ids,
        "records": records,
        "notes": [
            "Generated from tests/validation/corpus.py and the checked-in model tree.",
            "RuleHub revision is recorded but not expanded until selectors are approved.",
            "Run this generator and review the diff whenever a fixture or tier changes.",
        ],
    }


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    try:
        expected = render(build_manifest())
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot generate corpus manifest: {exc}", file=sys.stderr)
        return 2

    if args.check:
        try:
            actual = args.output.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: cannot read {args.output}: {exc}", file=sys.stderr)
            return 2
        if actual != expected:
            print(
                f"ERROR: {args.output} is stale; regenerate and review it",
                file=sys.stderr,
            )
            return 1
        print(f"corpus manifest is current: {args.output}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8")
    print(f"wrote corpus manifest: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
