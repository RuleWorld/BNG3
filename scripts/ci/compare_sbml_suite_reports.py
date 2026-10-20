#!/usr/bin/env python3
"""Compare two official SBML Test Suite gate reports case by case.

The gate's verdicts are its evidence.  This tool exists so a change to the
gate's execution strategy can be shown not to change any verdict: it diffs
the conversion status, the round-trip status, the independent-comparison
status, the official-reference status, and the per-variable comparison
numbers of every case in two reports.

Only the fields that describe a verdict are compared.  Run-local provenance
is excluded because it is expected to differ between two runs of the same
corpus: the report-level command line, working directory and repository
provenance, and the per-record ``worker_runtime_provenance`` that names the
interpreter, the Python package tree and the native extension each run
used.  Those fields say which build observed a case, not what it observed.

Lists are compared as multisets.  The unsupported-cause and
official-reference summaries list their cases in record order, and that
order carries no verdict: two runs that dispatch the same cases in a
different order must not report a difference.

The tool exits 0 when the two reports agree on every per-case verdict and
on every aggregate the gate published, and 1 when they do not.  There is no
verdicts-only mode: a report-level difference is reported too, because it
is derived from the verdicts.  A difference that is only a report *shape*
difference -- a bucket one report has and the other does not -- is
reported as such and is not a verdict.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
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

# Per-record fields that describe the runtime that observed the case rather
# than the case's verdict.
NON_VERDICT_RECORD_FIELDS = ("worker_runtime_provenance",)


def _canonical(value: Any) -> str:
    """Return a stable text form of a JSON-compatible value."""

    return json.dumps(value, sort_keys=True, default=str)


def _verdict_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return the record without the fields that describe the run, not a verdict."""

    return {
        key: value
        for key, value in record.items()
        if key not in NON_VERDICT_RECORD_FIELDS
    }


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
        # A list's order carries no verdict in a gate report, so compare the
        # elements as a multiset and report only genuine membership changes.
        left_items = Counter(_canonical(item) for item in left)
        right_items = Counter(_canonical(item) for item in right)
        if left_items == right_items:
            return []
        differences = []
        for item, count in sorted((left_items - right_items).items()):
            differences.append(f"{path}: {item} only in the first report ({count})")
        for item, count in sorted((right_items - left_items).items()):
            differences.append(f"{path}: {item} only in the second report ({count})")
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
) -> tuple[list[str], list[str], list[str]]:
    """Return the per-case differences, the differing cases, and the report differences.

    The per-case differences are the verdict evidence.  The report-level
    differences are the aggregates the gate published over the same cases.
    """

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
        case_differences = _difference(
            _verdict_record(left_records[key]),
            _verdict_record(right_records[key]),
            label,
        )
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
    return differences, differing_cases, report_differences


def _provenance_only_cases(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    """Return the cases whose runtime provenance differs but whose verdict does not."""

    left_records = _records(left)
    right_records = _records(right)
    differing = []
    for key in sorted(set(left_records) & set(right_records)):
        if left_records[key].get("worker_runtime_provenance") != right_records[key].get(
            "worker_runtime_provenance"
        ):
            differing.append(f"{key[0]}/{key[1]}")
    return differing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path, help="first gate report")
    parser.add_argument("second", type=Path, help="second gate report")
    parser.add_argument(
        "--max-differences",
        type=int,
        default=40,
        help="how many differing cases to print in detail",
    )
    args = parser.parse_args()

    first = json.loads(args.first.read_text(encoding="utf-8"))
    second = json.loads(args.second.read_text(encoding="utf-8"))
    differences, differing_cases, report_differences = compare_reports(first, second)
    for field in NON_VERDICT_REPORT_FIELDS:
        if field in first and field in second and first[field] != second[field]:
            print(f"note: run-local field {field} differs (not a verdict)")
    provenance_only = _provenance_only_cases(first, second)
    if provenance_only:
        print(
            f"note: {len(provenance_only)} cases ran under a different runtime "
            "provenance (not a verdict)"
        )
    if not differences and not report_differences:
        print(
            f"identical verdicts for {len(_records(first))} cases; "
            "no conversion, round-trip, independent-comparison, "
            "official-reference, or per-variable difference"
        )
        return 0
    if differences:
        print(f"{len(differing_cases)} cases differ between the two reports")
        # Group the differences by case so the header's case count and the
        # detail lines agree: one case can contribute many differences.
        grouped: dict[str, list[str]] = {}
        for difference in differences:
            path, _, detail = difference.partition(": ")
            case = path.split(".", 1)[0]
            grouped.setdefault(case, []).append(f"{path}: {detail}")
        for case in sorted(grouped)[: args.max_differences]:
            details = grouped[case]
            print(f"  {case}: {len(details)} difference(s)")
            for detail in details:
                print(f"    {detail}")
        remaining = len(grouped) - args.max_differences
        if remaining > 0:
            print(f"  ... {remaining} more cases differ")
    else:
        print(
            f"no per-case verdict difference between the two reports "
            f"({len(_records(first))} cases)"
        )
    if report_differences:
        print("report-level differences:")
        for difference in report_differences[: args.max_differences]:
            print(f"  {difference}")
        if len(report_differences) > args.max_differences:
            print(
                f"  ... {len(report_differences) - args.max_differences} "
                "more report-level differences"
            )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
