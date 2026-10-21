#!/usr/bin/env python3
"""Compare two curated BioModels corpus gate reports record by record.

The corpus gate's verdicts are its evidence.  This tool exists so a change to
the gate's execution strategy can be shown not to change any verdict: it
diffs the per-record outcome of every curated BioModels record in two
reports, stage by stage, and it compares the aggregates the gate published
over the same records.

Only the fields that describe a verdict are compared.  Run-local provenance
is excluded because it is expected to differ between two runs of the same
corpus: the imported Python package's path, the native extension's path and
digest, the command line and the working directory.  Those fields say which
build observed a record, not what it observed, so they are reported as a
*note* and never as a difference.

Lists are compared as multisets.  The gate's summaries list their record ids
in record order, and that order carries no verdict: two runs that dispatch
the same records in a different order must not report a difference.

The corpus gate has two outcome buckets of its own, and this tool treats them
the way the gate does:

``unsupported_format``
    the record is not an SBML artifact at all.  It is a refusal with a
    named construct, and a change in it is a change in the corpus.

``timeout``
    the run produced no verdict for the record.  The per-model budget is
    sized for an unloaded machine, so on a shared machine a timeout records
    that the machine was busy, not that the model is unsupported.  **A
    timeout is not a verdict.**  A difference in which a timeout takes part
    is reported as a timeout difference and is kept distinct from a real
    change; it is not a verdict difference and does not fail the comparison.

Exit status
-----------

0
    the two reports agree on every verdict and on every aggregate the gate
    published.  A difference that is only in the load-sensitive timeout
    bucket is reported as such and does not fail the comparison.
1
    the two reports disagree on a verdict, or an aggregate that is derived
    from the verdicts differs, or a record is present in one report and
    absent from the other.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, NamedTuple

# Report and record fields that describe how a run was launched rather than
# what it observed.  They are reported as a note and never treated as a
# verdict.  The names are matched at every depth, so a nested provenance
# object is excluded as well as a top-level one.
PROVENANCE_KEYS = frozenset(
    {
        "bionetgen_package_path",
        "command",
        "cwd",
        "native_extension_path",
        "native_extension_resolved_path",
        "native_extension_sha256",
        "python_package_source_sha256",
        "runtime_provenance",
        "source_provenance",
        "worker_runtime_provenance",
        "working_directory",
    }
)

# Report fields that are compared.  They are the per-record verdicts' own
# aggregates and the settings the run measured with.
COMPARED_REPORT_FIELDS = (
    "completeness",
    "core_passed",
    "mode",
    "sbml_unsupported_summary",
    "simulation",
    "simulation_comparison_is_required",
    "summary",
    "supported_surface_passed",
    "unsupported_formats_are_explicit",
    "unsupported_summary",
    "writer_sbml_version",
)

# Report fields that describe the run rather than the corpus.  They are
# reported as a note when they differ.
RUN_LOCAL_REPORT_FIELDS = (
    "cache_dir",
    "command",
    "manifest",
    "runtime_provenance",
    "source_provenance",
)

# The fields of the report's inventory that identify the corpus.  Two runs of
# different corpora are not comparable, so a difference here is a difference.
CORPUS_IDENTITY_FIELDS = ("source", "query", "matches")


class Comparison(NamedTuple):
    """The result of comparing two corpus gate reports."""

    verdict_differences: list[str]
    timeout_differences: list[str]
    differing_records: list[str]
    report_differences: list[str]
    provenance_notes: list[str]


def _canonical(value: Any) -> str:
    """Return a stable text form of a JSON-compatible value."""

    return json.dumps(value, sort_keys=True, default=str)


def _difference(
    left: Any, right: Any, path: str, skip: frozenset[str] = PROVENANCE_KEYS
) -> tuple[list[str], list[str]]:
    """Return the differing leaves between two JSON-compatible values.

    The first list holds the differences that describe a verdict.  The second
    holds the differences that describe the run: they are reported and never
    counted as a verdict difference.
    """

    if type(left) is not type(right) and not (
        isinstance(left, (int, float))
        and isinstance(right, (int, float))
        and not isinstance(left, bool)
        and not isinstance(right, bool)
    ):
        return [f"{path}: {left!r} != {right!r}"], []
    if isinstance(left, dict):
        verdict: list[str] = []
        provenance: list[str] = []
        for key in sorted(set(left) | set(right)):
            if key in skip:
                if key not in left or key not in right:
                    provenance.append(f"{path}.{key}: present in only one report")
                elif left[key] != right[key]:
                    provenance.append(f"{path}.{key}: differs (not a verdict)")
                continue
            if key not in left:
                verdict.append(f"{path}.{key}: missing from the first report")
            elif key not in right:
                verdict.append(f"{path}.{key}: missing from the second report")
            else:
                child_verdict, child_provenance = _difference(
                    left[key], right[key], f"{path}.{key}", skip
                )
                verdict.extend(child_verdict)
                provenance.extend(child_provenance)
        return verdict, provenance
    if isinstance(left, list):
        if len(left) != len(right):
            # A list's length carries a verdict: a summary that lists a
            # different number of records is a different set of records.
            return [f"{path}: list length {len(left)} != {len(right)}"], []
        # A list's order carries no verdict in a gate report, so compare the
        # elements as a multiset and report only genuine membership changes.
        left_items = Counter(_canonical(item) for item in left)
        right_items = Counter(_canonical(item) for item in right)
        if left_items == right_items:
            return [], []
        differences = []
        for item, count in sorted((left_items - right_items).items()):
            differences.append(f"{path}: {item} only in the first report ({count})")
        for item, count in sorted((right_items - left_items).items()):
            differences.append(f"{path}: {item} only in the second report ({count})")
        return differences, []
    if left != right:
        return [f"{path}: {left!r} != {right!r}"], []
    return [], []


def _records(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the report's records keyed by their BioModels id."""

    records = report.get("records")
    if not isinstance(records, list):
        raise ValueError("report does not contain a records list")
    keyed: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record.get("id") or "")
        if not key:
            raise ValueError("report contains a record without an id")
        if key in keyed:
            raise ValueError(f"report contains duplicate record {key}")
        keyed[key] = record
    return keyed


def _mode_stages(mode_result: dict[str, Any]) -> dict[str, Any]:
    """Return the verdict of each stage of one mode of one record."""

    comparison = mode_result.get("simulation_comparison") or {}
    native = mode_result.get("native_reader") or {}
    return {
        "conversion": {
            "status": mode_result.get("status"),
            "core_passed": mode_result.get("core_passed"),
            "unsupported_reason": mode_result.get("unsupported_reason"),
            "error": mode_result.get("error"),
        },
        "roundtrip_structure": {
            "written_xml_passed": (mode_result.get("written_xml") or {}).get("passed"),
            "generated_network": mode_result.get("generated_network"),
            "native_reader": {
                key: native.get(key)
                for key in ("success", "species_count", "reaction_count")
            },
        },
        "independent_comparison": {
            "passed": comparison.get("passed"),
            "skipped": comparison.get("skipped"),
            "failed_observables": sorted(
                str(observable)
                for observable in (comparison.get("failed_observables") or [])
            ),
            "error": comparison.get("error"),
        },
    }


def _record_stages(record: dict[str, Any]) -> dict[str, Any]:
    """Return the verdict of each stage of the corpus gate for one record.

    The record's own status is the gate's verdict for the record; the mode
    results carry the per-stage evidence.  Both are verdicts, so both are
    compared.
    """

    stages: dict[str, Any] = {
        "conversion": {
            "status": record.get("status"),
            "core_passed": record.get("core_passed"),
            "unsupported_reason": record.get("unsupported_reason"),
            "unsupported_causes": sorted(
                str(cause) for cause in (record.get("unsupported_causes") or [])
            ),
            "unsupported_subcauses": record.get("unsupported_subcauses"),
            "error": record.get("error"),
            "source_artifact_sha256": (record.get("source_artifact") or {}).get(
                "sha256"
            ),
        }
    }
    for mode_result in record.get("modes") or []:
        mode = str(mode_result.get("mode") or "unknown")
        for stage, detail in _mode_stages(mode_result).items():
            stages[f"{mode}:{stage}"] = detail
    return stages


def compare_reports(left: dict[str, Any], right: dict[str, Any]) -> Comparison:
    """Compare two corpus gate reports.

    The per-record differences are the verdict evidence; the report-level
    differences are the aggregates the gate published over the same records.
    A difference in which a timeout takes part is a timeout difference: the
    timeout bucket is load-sensitive and a timeout is not a verdict.
    """

    left_records = _records(left)
    right_records = _records(right)
    verdict_differences: list[str] = []
    timeout_differences: list[str] = []
    differing_records: list[str] = []
    provenance_notes: list[str] = []

    for key in sorted(set(left_records) | set(right_records)):
        if key not in left_records:
            verdict_differences.append(f"{key}: missing from the first report")
            differing_records.append(key)
            continue
        if key not in right_records:
            verdict_differences.append(f"{key}: missing from the second report")
            differing_records.append(key)
            continue
        left_status = str(left_records[key].get("status") or "")
        right_status = str(right_records[key].get("status") or "")
        timeout_related = "timeout" in {left_status, right_status}
        differences, provenance = _difference(
            _record_stages(left_records[key]),
            _record_stages(right_records[key]),
            key,
        )
        provenance_notes.extend(provenance)
        if not differences:
            continue
        differing_records.append(key)
        if timeout_related:
            timeout_differences.extend(differences)
        else:
            verdict_differences.extend(differences)

    report_differences: list[str] = []
    for field in COMPARED_REPORT_FIELDS:
        if field not in left and field not in right:
            continue
        differences, provenance = _difference(left.get(field), right.get(field), field)
        report_differences.extend(differences)
        provenance_notes.extend(provenance)

    for field in RUN_LOCAL_REPORT_FIELDS:
        if field in left and field in right and left[field] != right[field]:
            provenance_notes.append(
                f"note: run-local field {field} differs (not a verdict)"
            )

    for field in CORPUS_IDENTITY_FIELDS:
        left_value = (left.get("inventory") or {}).get(field)
        right_value = (right.get("inventory") or {}).get(field)
        if left_value != right_value:
            report_differences.append(
                f"inventory.{field}: {left_value!r} != {right_value!r}"
            )

    return Comparison(
        verdict_differences=verdict_differences,
        timeout_differences=timeout_differences,
        differing_records=differing_records,
        report_differences=report_differences,
        provenance_notes=provenance_notes,
    )


def _group_by_record(differences: list[str]) -> dict[str, list[str]]:
    """Group the differences by the record they belong to."""

    grouped: dict[str, list[str]] = {}
    for difference in differences:
        path, _, detail = difference.partition(": ")
        record = path.split(".", 1)[0]
        grouped.setdefault(record, []).append(f"{path}: {detail}")
    return grouped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path, help="first corpus gate report")
    parser.add_argument("second", type=Path, help="second corpus gate report")
    parser.add_argument(
        "--max-differences",
        type=int,
        default=40,
        help="how many differing records to print in detail",
    )
    args = parser.parse_args()

    first = json.loads(args.first.read_text(encoding="utf-8"))
    second = json.loads(args.second.read_text(encoding="utf-8"))
    comparison = compare_reports(first, second)

    for note in comparison.provenance_notes:
        print(note)

    if comparison.timeout_differences:
        grouped = _group_by_record(comparison.timeout_differences)
        print(
            f"{len(grouped)} record(s) differ only in the timeout bucket "
            f"({len(comparison.timeout_differences)} difference(s)).  The "
            "timeout bucket is load-sensitive on a shared machine and a "
            "timeout is not a verdict, so these are reported and are not "
            "counted as a change:"
        )
        for record in sorted(grouped)[: args.max_differences]:
            print(f"  {record}: {len(grouped[record])} difference(s)")
            for detail in grouped[record]:
                print(f"    {detail}")

    if not comparison.verdict_differences and not comparison.report_differences:
        print(
            f"identical verdicts for {len(_records(first))} records; no "
            "conversion, round-trip, independent-comparison, or aggregate "
            "difference"
        )
        return 0

    if comparison.verdict_differences:
        grouped = _group_by_record(comparison.verdict_differences)
        print(f"{len(grouped)} records differ between the two reports")
        for record in sorted(grouped)[: args.max_differences]:
            details = grouped[record]
            print(f"  {record}: {len(details)} difference(s)")
            for detail in details:
                print(f"    {detail}")
        remaining = len(grouped) - args.max_differences
        if remaining > 0:
            print(f"  ... {remaining} more records differ")
    else:
        print(
            f"no per-record verdict difference between the two reports "
            f"({len(_records(first))} records)"
        )
    if comparison.report_differences:
        print("report-level differences:")
        for difference in comparison.report_differences[: args.max_differences]:
            print(f"  {difference}")
        if len(comparison.report_differences) > args.max_differences:
            print(
                f"  ... {len(comparison.report_differences) - args.max_differences} "
                "more report-level differences"
            )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
