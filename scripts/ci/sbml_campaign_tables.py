#!/usr/bin/env python3
"""Render the Atomizer coverage campaign's result tables from harness reports.

The campaign document used to carry hand-maintained result tables.  They
drifted from the reports they described: a stage row kept an old pass count
while the report had moved on, and a failure table listed cases whose verdict
had already changed.  This tool regenerates every table from the harness
reports themselves, so a table cannot state a number the measured run does not
support.

The tool never runs the harness and never changes a verdict.  It reads the
reports the harness produced and the pinned official suite's own case notes,
and it writes markdown into the marked regions of the campaign document.

Usage:
    python scripts/ci/sbml_campaign_tables.py \
        --baseline-suite-report /tmp/bng3-campaign/baseline-ssts.json \
        --suite-report /tmp/bng3-campaign/main-merged-report.json \
        --baseline-biomodels-report /tmp/bng3-campaign/biomodels-baseline.json \
        --biomodels-report /tmp/bng3-campaign/biomodels-main-flat.json \
        --suite-dir /tmp/bng3-ssts-20261016 \
        --pytest-junit /tmp/bng3-campaign/pytest-main.xml \
        --doc docs/SBML_ATOMIZER_COVERAGE_CAMPAIGN.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ci import sbml_campaign_inventory as inventory  # noqa: E402

# The named regions of the campaign document this tool owns.
REGIONS: tuple[str, ...] = (
    "sbml-campaign-baseline",
    "sbml-campaign-current",
    "sbml-campaign-python",
)

# The region syntax a document uses to hand a section to this tool.  A
# document marks a generated section with
#
#     <!-- BEGIN GENERATED: <name> -->
#     ...generated markdown...
#     <!-- END GENERATED: <name> -->
#
# and the tool rewrites everything between the two markers.  The markers are
# plain HTML comments, so they render as nothing.
BEGIN_MARKER_TEMPLATE = "<!-- BEGIN GENERATED: {name} -->"
END_MARKER_TEMPLATE = "<!-- END GENERATED: {name} -->"

# The order of the stages in every generated stage table.
STAGE_LABELS: tuple[tuple[str, str], ...] = (
    ("conversion", "Conversion (SBML → BNGL)"),
    ("roundtrip_structure", "Round-trip structure"),
    ("independent_comparison", "Independent libRoadRunner comparison"),
    ("official_reference", "Official reference comparison"),
)

# Official-reference unsupported verdicts, grouped by the blocking reason and
# the component that owns it.  The first matching rule wins; a reason that
# matches no rule is reported under the generic Atomizer owner.
UNSUPPORTED_OWNER_RULES: tuple[tuple[str, str, str], ...] = (
    (
        "generated BNGL contains scheduled actions",
        "harness",
        "the in-memory CVODE reference runner cannot execute actions on the "
        "official output grid",
    ),
    (
        "official stochastic conformance requires repeated-run",
        "harness",
        "official stochastic conformance requires repeated-run mean and "
        "standard-deviation evaluation",
    ),
    (
        "does not define an official time-course reference",
        "not applicable",
        "case does not define an official time-course reference",
    ),
    (
        "no exact BNG3 result mapping",
        "harness mapping",
        "no exact BNG3 result mapping for: <reaction id>",
    ),
    (
        "is marked fast",
        "Atomizer diagnostic",
        'Reaction "…" is marked fast (fast="true")',
    ),
    (
        "not losslessly representable",
        "C++ writer",
        'SBML math function "…" is not losslessly representable in the C++ '
        "SBML writer",
    ),
    (
        "in math; BNGL has no built-in function",
        "Atomizer diagnostic",
        "<sec>/<csc>/… in math; BNGL has no built-in function",
    ),
    (
        "have no MathML kinetic law",
        "Atomizer diagnostic",
        "N reaction(s) have no MathML kinetic law",
    ),
    (
        "no MathML expression",
        "Atomizer",
        "… has no MathML expression (empty math)",
    ),
    (
        "SBML event(s) parsed",
        "Atomizer",
        "state-dependent / non-constant SBML events untranslated",
    ),
    (
        "unsupported stoichiometry",
        "Atomizer",
        "… has unsupported stoichiometry; the reaction is omitted",
    ),
    (
        "could not be resolved to a number",
        "Atomizer",
        "an assigned stoichiometry could not be resolved at initialization",
    ),
    (
        "spatialDimensions",
        "Atomizer",
        "a compartment declares unsupported spatialDimensions",
    ),
    (
        "compartment derivative",
        "Atomizer",
        "a species concentration rate rule requires an explicit compartment "
        "derivative",
    ),
    (
        "constant encountered in math",
        "Atomizer",
        "<infinity>/<notanumber> constant encountered in math",
    ),
    (
        "distrib",
        "Atomizer diagnostic",
        'SBML "distrib" package detected',
    ),
    (
        "algebraic rule",
        "Atomizer",
        "algebraic rule(s) present",
    ),
)

# The official feature tag that names each remaining-failure cluster.  The
# first tag present in a case's own official metadata selects its cluster.
FAILURE_CLUSTER_TAGS: tuple[tuple[str, str], ...] = (
    ("CSymbolDelay", "CSymbolDelay"),
    ("CSymbolRateOf", "CSymbolRateOf"),
    ("CSymbolAvogadro", "CSymbolAvogadro"),
    ("AlgebraicRule", "AlgebraicRule"),
    ("InitialAssignment", "InitialAssignment"),
    ("AssignmentRule", "AssignmentRule"),
    ("RateRule", "RateRule"),
)
FAILURE_CLUSTER_OTHER = "other"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _caption(parts: list[str]) -> list[str]:
    return ["_" + "; ".join(parts) + "._"]


def _report_caption(path: Path, report: dict[str, Any], extra: str = "") -> list[str]:
    revision = str(report.get("suite_commit") or "")
    commit = str((report.get("source_provenance") or {}).get("bng3_commit") or "")
    parts = [f"Source: `{path}` (SHA-256 `{_digest(path)}`)"]
    if revision:
        parts.append(f"SBML Test Suite revision `{revision}`")
    if commit:
        parts.append(f"BNG3 commit `{commit}`")
    if extra:
        parts.append(extra)
    return _caption(parts)


def suite_stage_counts(report: dict[str, Any]) -> dict[str, Counter]:
    counters = {stage: Counter() for stage, _ in STAGE_LABELS}
    for statuses in inventory.expectation_cases(report).values():
        for stage, status in statuses.items():
            counters[stage][status] += 1
    return counters


def suite_stage_table(report: dict[str, Any], path: Path) -> list[str]:
    counters = suite_stage_counts(report)
    rows = []
    for stage, label in STAGE_LABELS:
        counts = counters[stage]
        rows.append(
            [
                label,
                str(counts.get("passed", 0)),
                str(counts.get("unsupported", 0)),
                str(counts.get("failed", 0)),
                str(counts.get("not_tested", 0)),
            ]
        )
    return _table(
        ["Stage", "Passed", "Unsupported", "Failed", "Not tested"], rows
    ) + _report_caption(
        path,
        report,
        "a timed-out case is recorded as failed and an unevaluated stage "
        "as not tested",
    )


def biomodels_table(report: dict[str, Any], path: Path) -> list[str]:
    records = report.get("records") or []
    counts = Counter(str(record.get("status", "unknown")) for record in records)
    completeness = report.get("completeness") or {}
    rows = [
        [
            str(report.get("mode") or "unknown"),
            str(completeness.get("inventory_records", sum(counts.values()))),
            str(counts.get("passed", 0)),
            str(counts.get("unsupported", 0)),
            str(counts.get("unsupported_format", 0)),
            str(counts.get("failed", 0)),
            str(counts.get("timeout", 0)),
        ]
    ]
    lines = _table(
        [
            "Mode",
            "Records",
            "Passed",
            "Unsupported",
            "Unsupported format",
            "Failed",
            "Timed out",
        ],
        rows,
    )
    summary = report.get("summary") or {}
    lines.append("")
    lines.append(
        f"Denominators: {summary.get('selected_records', '?')} inventory records; "
        f"{summary.get('sbml_records', '?')} records reach the SBML path; "
        f"{summary.get('declared_sbml_records', '?')} declare SBML; "
        f"{summary.get('archive_records', '?')} are archives."
    )
    lines.extend(
        _report_caption(
            path,
            report,
            f"mode `{report.get('mode')}`",
        )
    )
    return lines


def official_unsupported_table(report: dict[str, Any], path: Path) -> list[str]:
    counts: Counter = Counter()
    for record in report.get("records") or []:
        official = record.get("official_conformance") or {}
        if str(official.get("status")) != "unsupported":
            continue
        reason = str(official.get("reason") or "")
        owner = "Atomizer"
        description = "other Atomizer-side limitation"
        for needle, rule_owner, rule_description in UNSUPPORTED_OWNER_RULES:
            if needle in reason:
                owner = rule_owner
                description = rule_description
                break
        counts[(owner, description)] += 1
    rows = [
        [str(count), owner, description]
        for (owner, description), count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0][0])
        )
    ]
    lines = _table(["Count", "Owner", "Blocking reason"], rows)
    lines.append("")
    lines.append(
        f"Total official-reference unsupported verdicts: {sum(counts.values())}."
    )
    lines.extend(_report_caption(path, report))
    return lines


def component_tags(suite_dir: Path, category: str, case_id: str) -> list[str]:
    notes = suite_dir / "cases" / category / case_id / f"{case_id}-model.m"
    text = notes.read_text(encoding="utf-8")
    match = re.search(r"^componentTags:[ \t]*(.*)$", text, re.MULTILINE)
    if match is None:
        raise ValueError(f"missing componentTags metadata for {category}/{case_id}")
    raw = match.group(1).strip()
    if raw.endswith(","):
        raw = raw[:-1]
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def failure_cluster_table(
    report: dict[str, Any], path: Path, suite_dir: Path
) -> list[str]:
    clusters: dict[str, list[str]] = {}
    for record in report.get("records") or []:
        official = record.get("official_conformance") or {}
        if str(official.get("status")) != "failed":
            continue
        tags = component_tags(
            suite_dir, str(record.get("category")), str(record.get("id"))
        )
        cluster = FAILURE_CLUSTER_OTHER
        for tag, label in FAILURE_CLUSTER_TAGS:
            if tag in tags:
                cluster = label
                break
        clusters.setdefault(cluster, []).append(str(record.get("id")))
    ordered = sorted(clusters.items(), key=lambda item: (-len(item[1]), item[0]))
    rows = [[cluster, str(len(ids)), " ".join(sorted(ids))] for cluster, ids in ordered]
    lines = _table(["Cluster", "n", "Cases"], rows)
    lines.append("")
    lines.append(
        "Total official-reference failures: "
        f"{sum(len(ids) for ids in clusters.values())}."
    )
    lines.extend(
        _report_caption(path, report, f"clusters read from `{suite_dir}` case notes")
    )
    return lines


def verdict_changes(
    baseline_report: dict[str, Any], current_report: dict[str, Any]
) -> tuple[Counter, list[dict[str, str]], set[str]]:
    """Return the per-stage transitions, the regressions and the changed cases."""

    baseline = inventory.expectation_cases(baseline_report)
    current = inventory.expectation_cases(current_report)
    transitions: Counter = Counter()
    regressions: list[dict[str, str]] = []
    changed: set[str] = set()
    for identity in sorted(set(baseline) & set(current)):
        for stage in inventory.EXPECTATION_STAGES:
            before = baseline[identity][stage]
            after = current[identity][stage]
            if before == after:
                continue
            changed.add(identity)
            transitions[(stage, before, after)] += 1
            if before == "passed" and after != "passed":
                regressions.append(
                    {
                        "case": identity,
                        "stage": stage,
                        "before": before,
                        "after": after,
                    }
                )
    return transitions, regressions, changed


def verdict_change_table(
    baseline_report: dict[str, Any],
    current_report: dict[str, Any],
    baseline_path: Path,
    current_path: Path,
) -> list[str]:
    transitions, regressions, changed = verdict_changes(baseline_report, current_report)
    rows = [
        [stage, before, after, str(count)]
        for (stage, before, after), count in sorted(transitions.items())
    ]
    lines = _table(["Stage", "Before", "After", "Cases"], rows)
    lines.append("")
    lines.append(f"Cases with at least one stage change: {len(changed)}.")
    lines.append("")
    if regressions:
        lines.append("Regressions (a stage that was `passed` and no longer is):")
        lines.append("")
        for regression in regressions:
            lines.append(
                f"- `{regression['case']}` [{regression['stage']}]: "
                f"{regression['before']} → {regression['after']}"
            )
    else:
        lines.append("Regressions (a stage that was `passed` and no longer is): none.")
    lines.append("")
    lines.append(
        "A stage that becomes `passed` is accepted only when the expectation "
        "manifest is explicitly updated."
    )
    lines.append("")
    lines.append(
        f"Baseline source: `{baseline_path}` (SHA-256 `{_digest(baseline_path)}`); "
        f"current source: `{current_path}` (SHA-256 `{_digest(current_path)}`)."
    )
    return lines


def python_suite_table(junit_path: Path | None) -> list[str]:
    if junit_path is None:
        return [
            "_Python suite counts were not measured in this run "
            "(pass `--pytest-junit`)._"
        ]
    root = ET.parse(junit_path).getroot()
    tests = failures = errors = skipped = xfailed = 0
    for suite in root.iter("testsuite"):
        tests += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
    for case in root.iter("testcase"):
        for child in case:
            if child.tag == "skipped":
                if child.get("type") == "pytest.xfail":
                    xfailed += 1
                else:
                    skipped += 1
    passed = tests - failures - errors - skipped - xfailed
    lines = _table(
        ["Suite", "Passed", "Skipped", "Xfailed", "Failed"],
        [
            [
                "tests/python",
                str(passed),
                str(skipped),
                str(xfailed),
                str(failures + errors),
            ]
        ],
    )
    lines.extend(["", f"Source: `{junit_path}` (SHA-256 `{_digest(junit_path)}`)."])
    return lines


def render(
    *,
    baseline_suite_report: Path | None,
    suite_report: Path | None,
    baseline_biomodels_report: Path | None,
    biomodels_report: Path | None,
    suite_dir: Path | None,
    pytest_junit: Path | None,
) -> dict[str, str]:
    regions: dict[str, str] = {}

    baseline_blocks: list[list[str]] = []
    if baseline_suite_report is not None:
        baseline_report = _load(baseline_suite_report)
        baseline_blocks.append(
            ["#### Official SBML Test Suite — baseline stage results", ""]
            + suite_stage_table(baseline_report, baseline_suite_report)
        )
        baseline_blocks.append(
            [
                "#### Official-reference unsupported verdicts at the baseline, by owner",
                "",
            ]
            + official_unsupported_table(baseline_report, baseline_suite_report)
        )
        if suite_dir is not None:
            baseline_blocks.append(
                [
                    "#### Baseline official-reference failures, by official feature",
                    "",
                ]
                + failure_cluster_table(
                    baseline_report, baseline_suite_report, suite_dir
                )
            )
    if baseline_biomodels_report is not None:
        baseline_blocks.append(
            ["#### Curated BioModels — baseline", ""]
            + biomodels_table(
                _load(baseline_biomodels_report), baseline_biomodels_report
            )
        )
    regions["sbml-campaign-baseline"] = _join(baseline_blocks)

    current_blocks: list[list[str]] = []
    if suite_report is not None:
        current_report = _load(suite_report)
        current_blocks.append(
            ["#### Official SBML Test Suite — current stage results", ""]
            + suite_stage_table(current_report, suite_report)
        )
        current_blocks.append(
            [
                "#### Official-reference unsupported verdicts, by owner",
                "",
            ]
            + official_unsupported_table(current_report, suite_report)
        )
        if suite_dir is not None:
            current_blocks.append(
                [
                    "#### Remaining official-reference failures, by official feature",
                    "",
                ]
                + failure_cluster_table(current_report, suite_report, suite_dir)
            )
    if biomodels_report is not None:
        current_blocks.append(
            ["#### Curated BioModels — current", ""]
            + biomodels_table(_load(biomodels_report), biomodels_report)
        )
    if baseline_suite_report is not None and suite_report is not None:
        current_blocks.append(
            ["#### Stage verdict changes, baseline to current", ""]
            + verdict_change_table(
                _load(baseline_suite_report),
                _load(suite_report),
                baseline_suite_report,
                suite_report,
            )
        )
    regions["sbml-campaign-current"] = _join(current_blocks)

    regions["sbml-campaign-python"] = _join(
        [["#### Result", ""] + python_suite_table(pytest_junit)]
    )
    return regions


def _join(blocks: list[list[str]]) -> str:
    lines: list[str] = []
    for index, block in enumerate(blocks):
        if index:
            lines.append("")
        lines.extend(block)
    return "\n".join(lines).rstrip() + "\n"


def replace_region(document: str, name: str, block: str) -> str:
    begin = BEGIN_MARKER_TEMPLATE.format(name=name)
    end = END_MARKER_TEMPLATE.format(name=name)
    start = document.find(begin)
    stop = document.find(end)
    if start < 0 or stop < 0 or stop < start:
        raise ValueError(
            f"campaign document is missing the generated region {name} "
            f"({begin} … {end})"
        )
    prefix = document[: start + len(begin)]
    suffix = document[stop:]
    return f"{prefix}\n\n{block}\n{suffix}"


def read_region(document: str, name: str) -> str:
    """Return the markdown a generated region currently holds."""

    begin = BEGIN_MARKER_TEMPLATE.format(name=name)
    end = END_MARKER_TEMPLATE.format(name=name)
    start = document.find(begin)
    stop = document.find(end)
    if start < 0 or stop < 0 or stop < start:
        raise ValueError(
            f"campaign document is missing the generated region {name} "
            f"({begin} … {end})"
        )
    return document[start + len(begin) : stop].strip()


def check_regions(document: str, regions: dict[str, str]) -> list[str]:
    """Return one message per region whose content drifted from the reports."""

    problems = []
    for name in REGIONS:
        expected = regions[name].strip()
        actual = read_region(document, name)
        if actual == expected:
            continue
        problems.append(
            f"generated region {name} does not match the reports "
            f"(document: {len(actual)} characters, reports: "
            f"{len(expected)} characters)"
        )
        for line in _diff_lines(actual, expected):
            problems.append(f"  {line}")
    return problems


def _diff_lines(actual: str, expected: str) -> list[str]:
    import difflib

    return list(
        difflib.unified_diff(
            actual.splitlines(),
            expected.splitlines(),
            fromfile="document",
            tofile="reports",
            lineterm="",
            n=1,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-suite-report", type=Path)
    parser.add_argument("--suite-report", type=Path)
    parser.add_argument("--baseline-biomodels-report", type=Path)
    parser.add_argument("--biomodels-report", type=Path)
    parser.add_argument("--suite-dir", type=Path)
    parser.add_argument("--pytest-junit", type=Path)
    parser.add_argument("--doc", type=Path, help="campaign document to update")
    parser.add_argument("--out-dir", type=Path, help="write each region to a file")
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "verify that the document's generated regions match the reports; "
            "exit non-zero on drift and leave the document unchanged"
        ),
    )
    args = parser.parse_args()

    regions = render(
        baseline_suite_report=args.baseline_suite_report,
        suite_report=args.suite_report,
        baseline_biomodels_report=args.baseline_biomodels_report,
        biomodels_report=args.biomodels_report,
        suite_dir=args.suite_dir,
        pytest_junit=args.pytest_junit,
    )
    if args.check:
        if args.doc is None:
            parser.error("--check requires --doc")
        document = args.doc.read_text(encoding="utf-8")
        problems = check_regions(document, regions)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        print(f"{args.doc} matches the reports")
        return 0
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        for name, block in regions.items():
            target = args.out_dir / f"{name}.md"
            target.write_text(block, encoding="utf-8")
            print(f"wrote {target}")
    if args.doc is not None:
        document = args.doc.read_text(encoding="utf-8")
        for name in REGIONS:
            document = replace_region(document, name, regions[name])
        args.doc.write_text(document, encoding="utf-8")
        print(f"updated {args.doc}")
    if args.out_dir is None and args.doc is None:
        parser.error("one of --out-dir or --doc is required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
