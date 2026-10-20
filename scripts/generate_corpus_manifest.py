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
PARITY_REPORT = REPO / "tests/validation/evidence/parity-report.json"
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


def reconciliation() -> dict[str, Any]:
    """Reconcile the selection with the separate 71-model Tier-P workflow.

    The workflow result is a retained artifact: it names the head it ran on,
    the digest of the selection manifest it ran against and the failure
    categories it recorded.  The selection it covered is the frozen
    100-model tier; the models that were on disk but outside it are recorded
    with the outcome they received, so the difference between the two counts
    is explained rather than silent.
    """
    report = json.loads(PARITY_REPORT.read_text(encoding="utf-8"))
    followup = report["matched_network_only_followup"]
    run = followup["required_post_fix_full_run"]
    source = report["source"]["selection_reconciliation"]
    supplemental = followup["supplemental_on_disk_models_outside_frozen_selection"]

    outcomes: dict[str, str] = {}
    for model_id in supplemental["models"]["pass"]:
        outcomes[model_id] = "passed"
    for entry in supplemental["models"]["fail"]:
        outcomes[entry["model"]] = "failed: " + entry["reason"]
    for entry in supplemental["models"]["error"]:
        outcomes[entry["model"]] = "oracle error: " + entry["reason"]

    added = []
    for model_id in source["unselected_on_disk_models"]:
        added.append(
            {
                "id": model_id,
                "recorded_outcome": outcomes.get(model_id, "unrecorded"),
            }
        )

    return {
        "workflow": run["selection"],
        "tested_head": run["tested_head"],
        "status": run["status"],
        "selection_manifest_sha256": run["selection_manifest_sha256"],
        "selected_model_count": source["tested_frozen_tier_p_count"],
        "result": run["result"],
        "failure_categories": {
            name: {
                "count": category["count"],
                "models": sorted(category["models"]),
            }
            for name, category in run["failure_categories"].items()
        },
        "evidence": PARITY_REPORT.relative_to(REPO).as_posix(),
        "added_models": added,
        "coverage_claim": source["coverage_claim"],
    }


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

    reconciliation_record = reconciliation()
    added = {entry["id"] for entry in reconciliation_record["added_models"]}

    records = []
    for model_id in sorted(resolved):
        path = resolved[model_id]
        relative = path.relative_to(REPO).as_posix()
        tiers = [tier for tier in TIERS if model_id in tier_ids[tier]]
        text = path.read_text(encoding="utf-8", errors="replace")
        records.append(
            {
                "id": model_id,
                "path": relative,
                "sha256": digest(path),
                "origin": "repository-fixture",
                "tiers": tiers,
                "selection": {
                    "reason": corpus.selection_reason(text, tiers[0], relative),
                    "tiers": tiers,
                    "capability": corpus.TIER_JUSTIFICATIONS[tiers[0]]["capability"],
                    "provenance": (
                        "added-after-the-frozen-selection"
                        if model_id in added
                        else "frozen-selection"
                    ),
                },
            }
        )

    justifications = {}
    for tier in TIERS:
        entry = dict(corpus.TIER_JUSTIFICATIONS[tier])
        if not tier_ids[tier]:
            entry["empty_reason"] = corpus.TIER_JUSTIFICATIONS[tier]["empty_reason"]
        justifications[tier] = entry

    return {
        "$schema": SCHEMA_PATH,
        "schema_version": 2,
        "selection_status": "pending-maintainer-approval",
        "accepted_selections": {
            "status": "pending-maintainer-approval",
            "approved_tiers": [],
            "approved_models": [],
            "note": corpus.ACCEPTED_SELECTION_NOTE,
        },
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
        "tier_justifications": justifications,
        "reconciliation": reconciliation_record,
        "records": records,
        "notes": [
            "Generated from tests/validation/corpus.py and the checked-in model tree.",
            "RuleHub revision is recorded but not expanded until selectors are approved.",
            "Every tier records its justification, its owner and its budget; an empty tier records why it is empty.",
            "Every selected model records the reason why it is selected, derived from the model file itself.",
            "The reconciliation record keeps the separate 71-model Tier-P workflow with the selection it ran against.",
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
