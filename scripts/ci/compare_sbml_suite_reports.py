#!/usr/bin/env python3
"""Compare two official SBML Test Suite gate reports case by case.

The gate's verdicts are its evidence.  This tool exists so a change to the
gate's execution strategy can be shown not to change any verdict: it diffs
the conversion status, the round-trip status, the independent-comparison
status, the official-reference status, and the per-variable comparison
numbers of every case in two reports.

Only the fields that describe a verdict are compared.  Run-local provenance
(the command line, the working directory, the report path) is excluded
because it is expected to differ between two runs of the same corpus.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# Report fields that describe how a run was launched rather than what it
# observed.  They are reported separately and never treated as a verdict.
NON_VERDICT_REPORT_FIELDS = (
    "command",
    "source_provenance",
    "case_isolation",
    "suite_dir",
)


def _difference(left: Any, right: Any, path: str) -> list[str]:
    """Return the differing leaves between two JSON-compatible values."""

    if type(left) is not type(right) and not (
        isinstance(left, (int, float))
        and isinstance(right, (int, float))
        and not isinstance(left, bool)
        and not isinstance(right, bool)
    ):
        return [f"{path}: {left!r} != {right!r}"]
    if isinstance(left, dict):
        differences = []
        for key in sorted(set(left) | set(right)):
            if key not in left:
                differences.append(f"{path}.{key}: missing from the first report")
            elif key not in right:
                differences.append(f"{path}.{key}: missing from the second report")
            else:
                differences.extend(_difference(left[key], right[key], f"{path}.{key}"))
        return differences
    if isinstance(left, list):
        if len(left) != len(right):
            return [f"{path}: list length {len(left)} != {len(right)}"]
        differences = []
        for index, (one, other) in enumerate(zip(left, right)):
            differences.extend(_difference(one, other, f"{path}[{index}]"))
        return differences
    if left != right:
        return [f"{path}: {left!r} != {right!r}"]
    return []


def _records(report: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    records = report.get("records")
    if not isinstance(records, list):
        raise ValueError("report does not contain a records list")
    keyed = {}
    for record in records:
        key = (str(record.get("category")), str(record.get("id")))
        if key in keyed:
            raise ValueError(f"report contains duplicate case {key[0]}/{key[1]}")
        keyed[key] = record
    return keyed


def compare_reports(
    left: dict[str, Any], right: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Return the differing cases and the differing report-level fields."""

    left_records = _records(left)
    right_records = _records(right)
    differences: list[str] = []
    differing_cases: list[str] = []
    for key in sorted(set(left_records) | set(right_records)):
        label = f"{key[0]}/{key[1]}"
        if key not in left_records:
            differences.append(f"{label}: missing from the first report")
            differing_cases.append(label)
            continue
        if key not in right_records:
            differences.append(f"{label}: missing from the second report")
            differing_cases.append(label)
            continue
        case_differences = _difference(left_records[key], right_records[key], label)
        if case_differences:
            differing_cases.append(label)
            differences.extend(case_differences)
    report_differences = []
    for field in (
        "counts",
        "stage_counts",
        "by_category",
        "official_conformance",
        "unsupported_summary",
        "sbml_unsupported_summary",
        "partial_run",
        "selected_surface_passed",
        "core_passed",
        "supported_surface_passed",
        "case_inventory",
        "full_suite_inventory",
        "selected_cases",
    ):
        if field not in left and field not in right:
            continue
        report_differences.extend(_difference(left.get(field), right.get(field), field))
    return differences + report_differences, differing_cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path, help="first gate report")
    parser.add_argument("second", type=Path, help="second gate report")
    parser.add_argument(
        "--max-differences",
        type=int,
        default=40,
        help="how many differences to print",
    )
    args = parser.parse_args()

    first = json.loads(args.first.read_text(encoding="utf-8"))
    second = json.loads(args.second.read_text(encoding="utf-8"))
    differences, differing_cases = compare_reports(first, second)
    for field in NON_VERDICT_REPORT_FIELDS:
        if field in first and field in second and first[field] != second[field]:
            print(f"note: run-local field {field} differs (not a verdict)")
    if not differences:
        print(
            f"identical verdicts for {len(_records(first))} cases; "
            "no conversion, round-trip, independent-comparison, "
            "official-reference, or per-variable difference"
        )
        return 0
    print(f"{len(differing_cases)} cases differ between the two reports")
    for difference in differences[: args.max_differences]:
        print(f"  {difference}")
    if len(differences) > args.max_differences:
        print(f"  ... {len(differences) - args.max_differences} more differences")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
