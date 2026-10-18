"""Deterministic bounded selection over locked official SSTS model metadata.

Feature selection is a coverage description, never a support claim.
"""

from pathlib import Path
import re
from typing import Any


class SuiteSelectionError(ValueError):
    """Official metadata is missing, ambiguous, or selection is unbounded."""


def _case_feature_classes(case: dict[str, Any]) -> set[str]:
    """Read official feature tags from a semantic case's model header."""

    model_path = Path(case["path"]).parent / f"{case['id']}-model.m"
    identity = f"{case['category']}/{case['id']}"
    try:
        model_text = model_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SuiteSelectionError(
            f"cannot read official feature metadata for {identity}: {exc}"
        ) from exc
    header = re.search(r"\(\*([\s\S]*?)\*\)", model_text)
    if header is None:
        raise SuiteSelectionError(f"missing official model header for {identity}")

    fields: dict[str, str] = {}
    for line in header.group(1).splitlines():
        match = re.match(
            r"^[ \t]*(componentTags|testTags|testType|packagesPresent):[ \t]*(.*?)[ \t]*$",
            line,
        )
        if match is None:
            continue
        key, value = match.groups()
        if key in fields:
            raise SuiteSelectionError(f"duplicate {key} metadata field for {identity}")
        fields[key] = value

    required = ("componentTags", "testTags", "testType")
    missing = [field for field in required if field not in fields]
    empty_required = [
        field for field in ("componentTags", "testType") if not fields.get(field)
    ]
    if missing or empty_required:
        raise SuiteSelectionError(
            f"missing or empty official metadata for {identity}: "
            f"{', '.join(missing + empty_required)}"
        )

    classes: set[str] = set()
    for field in ("componentTags", "testTags", "packagesPresent"):
        raw = fields.get(field, "")
        if not raw:
            continue
        # A few official model headers use one terminal comma after their
        # final component tag. It is a field terminator, not an empty tag.
        if raw.endswith(","):
            raw = raw[:-1]
        values = [value.strip() for value in raw.split(",")]
        if any(not value for value in values):
            raise SuiteSelectionError(
                f"empty values in {field} metadata for {identity}"
            )
        prefix = {
            "componentTags": "component",
            "testTags": "test",
            "packagesPresent": "package",
        }[field]
        classes.update(f"{prefix}:{value}" for value in values)
    classes.add(f"testType:{fields['testType']}")
    return classes


def select_feature_cover(
    cases: list[dict[str, Any]], budget: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Greedily cover official metadata classes, then fill by stable case ID.

    This describes which cases were selected by their metadata. It does not
    claim that a selected feature class executed successfully or is supported.
    """

    if type(budget) is not int or budget < 1:
        raise SuiteSelectionError("feature-cover selection requires a positive budget")
    if not cases:
        raise SuiteSelectionError(
            "feature-cover selection requires a non-empty inventory"
        )
    ordered = sorted(cases, key=lambda case: (case["category"], case["id"]))
    identities = [(case["category"], case["id"]) for case in ordered]
    if len(identities) != len(set(identities)):
        raise SuiteSelectionError("duplicate category/case identity in suite inventory")

    case_key = lambda case: (case["category"], case["id"])
    features = {case_key(case): _case_feature_classes(case) for case in ordered}
    inventory_classes = set().union(*(features[case_key(case)] for case in ordered))
    selected: list[dict[str, Any]] = []
    remaining = list(ordered)
    covered: set[str] = set()
    target_count = min(budget, len(ordered))
    while remaining and len(selected) < target_count and covered != inventory_classes:
        gains = {
            case_key(case): len(features[case_key(case)] - covered)
            for case in remaining
        }
        best_gain = max(gains.values())
        if best_gain == 0:
            break
        choice = next(case for case in remaining if gains[case_key(case)] == best_gain)
        selected.append(choice)
        covered.update(features[case_key(choice)])
        remaining.remove(choice)

    selected.extend(remaining[: target_count - len(selected)])
    selected_classes = set().union(*(features[case_key(case)] for case in selected))
    report = {
        "strategy": "official-metadata-greedy-cover-v1",
        "budget": budget,
        "inventory_feature_classes": sorted(inventory_classes),
        "selected_feature_classes": sorted(selected_classes),
        "unselected_feature_classes": sorted(inventory_classes - selected_classes),
        "selected_case_features": [
            {
                "category": case["category"],
                "id": case["id"],
                "feature_classes": sorted(features[case_key(case)]),
            }
            for case in selected
        ],
        "unselected_case_count": len(ordered) - len(selected),
        "selected_case_count": len(selected),
        "selection_is_support_claim": False,
    }
    return selected, report
