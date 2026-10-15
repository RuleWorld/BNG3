"""Publish granular CI findings and independently gate recorded evidence."""

from __future__ import annotations

import argparse
import json
import shlex
from collections import Counter
from pathlib import Path

STATUSES = {
    "PASS",
    "FAIL",
    "UNSUPPORTED",
    "NOT_TESTED",
    "INVALID_INPUT",
    "TIMEOUT",
    "HARNESS_ERROR",
}


def _escape(value):
    return (
        str(value)
        .replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(",", "%2C")
        .replace(":", "%3A")
    )


def publish(report, summary, *, strict=False, revision=None):
    rows = report.get("results", [])
    bad = [
        r
        for r in rows
        if not r.get("aggregate")
        and r["status"] != "PASS"
        and not (
            r["status"] == "NOT_TESTED" and r.get("applicability") == "no-observables"
        )
    ]
    errors = []
    ids = Counter(r["id"] for r in rows)
    missing = set(report.get("expected_contract_ids", [])) - ids.keys()
    duplicates = [name for name, count in ids.items() if count > 1]
    if missing:
        errors.append(
            "Missing selected contract evidence: " + ", ".join(sorted(missing))
        )
    if duplicates:
        errors.append("Duplicate case identities: " + ", ".join(sorted(duplicates)))
    if not rows:
        errors.append("No executed contract evidence; discovery alone cannot pass CI.")
    if revision and report.get("source", {}).get("revision") != revision:
        errors.append("Report source revision does not match the exact CI candidate.")
    severity = "error" if strict else "warning"
    for message in errors:
        print(f"::{severity} title=Conformance evidence invalid::{_escape(message)}")
    for row in bad[:50]:
        print(
            f'::{severity} title={_escape(row["id"])}::{_escape(row["status"]+": "+(row.get("failure_summary") or row.get("detail", ""))[:1000])}; inspect investigation-tasks.json and recorded receipts'
        )
    counts = Counter(r["status"] for r in rows if not r.get("aggregate"))
    lines = [
        "## Conformance contract findings",
        "",
        f"Candidate: `{report.get('source', {}).get('revision', 'missing')}`. Aggregate model rows are excluded from the following counts.",
        "",
        "| Outcome | Leaf checks |",
        "| --- | ---: |",
    ]
    lines += [f"| {status} | {counts[status]} |" for status in sorted(counts)]
    lines += [
        "",
        f'**{"FAIL" if bad or errors else "PASS"}** for the selected contracts. Unknown/unexecuted inventory entries remain unqualified; this check does not approve a release.',
        "",
    ]
    lines += [f"- {e}" for e in errors]
    for task in report.get("investigation_tasks", []):
        observation = str(task["observation"]).replace("<", "&lt;").replace("\n", " ")
        lines += [
            f"### {task['case_id']}",
            "",
            observation[:1600],
            "",
            f"Task packet `{task['id']}` in `investigation-tasks.json`. "
            + " ".join(
                f"[#{issue}](https://github.com/RuleWorld/BNG3/issues/{issue})"
                for issue in task.get("related_issues", [])
            ),
            "",
            "Inspect: "
            + ", ".join("`" + p + "`" for p in task.get("source_locations", [])),
            "",
            "```sh",
            (
                "cd " + shlex.quote(task["reproduce_cwd"])
                if task.get("reproduce_cwd")
                else "# Run from the repository root"
            ),
            shlex.join(
                [
                    "env",
                    *[
                        f"{key}={value}"
                        for key, value in task.get("reproduce_environment", {}).items()
                    ],
                    *task.get("reproduce_command", []),
                ]
            ),
            "```",
            "",
        ]
        lines += ["- " + criterion for criterion in task["acceptance_criteria"]]
        lines += [""]
    lines += [
        "Download the conformance artifact for report.json, input hashes, source/reference identities, logs, commands and intermediate outputs. Use a new empty directory for each replay.",
        "",
    ]
    summary = Path(summary)
    summary.parent.mkdir(parents=True, exist_ok=True)
    with summary.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    return int(strict and bool(bad or errors))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text())
    except (OSError, ValueError) as exc:
        print(f"::error title=Missing conformance evidence::{_escape(exc)}")
        return 1
    return publish(report, args.summary, strict=args.strict, revision=args.revision)


if __name__ == "__main__":
    raise SystemExit(main())
