"""Publish granular CI findings and independently gate recorded evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
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
    priority = {
        "HARNESS_ERROR": 0,
        "FAIL": 1,
        "TIMEOUT": 2,
        "INVALID_INPUT": 3,
        "UNSUPPORTED": 4,
        "NOT_TESTED": 5,
    }
    for row in sorted(bad, key=lambda r: (priority.get(r["status"], 0), r["id"]))[:50]:
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


def _external_revision(document):
    provenance = document.get("source_provenance") or {}
    if not isinstance(provenance, dict):
        return None
    revision = provenance.get("bng3_commit") or provenance.get("revision")
    revision = (
        revision or document.get("bng3_revision") or document.get("source_revision")
    )
    return revision if isinstance(revision, str) and revision else None


def _external_report(
    document,
    input_format,
    input_path,
    input_bytes,
    issues,
    issues_bytes,
    output_directory,
):
    from . import external_lanes, inventory, reporting
    import yaml

    adapter = {
        "ssts": external_lanes.sbml_results,
        "biomodels": external_lanes.biomodel_results,
    }[input_format]
    results = adapter(document)
    root = Path(__file__).resolve().parents[2]
    selection = document.get("case_selection") or {}
    features = {
        (case["category"], case["id"]): case["feature_classes"]
        for case in selection.get("selected_case_features", [])
    }
    for row in results:
        row["evidence"] = ["input-report.json"]
        if row["stage"] == "cross-engine-simulation":
            row["comparison_boundary"] = "generated BNGL versus BNG3-exported SBML"
        if input_format == "ssts":
            _, category, case_id, *_ = row["id"].split(":")
            row["feature_classes"] = features.get((category, case_id), [])
            protocol = document.get("simulation") or {}
            if document.get("suite_dir") and all(
                key in protocol for key in ("t_end", "n_steps", "rtol", "atol")
            ):
                replay = output_directory / "replay" / category / case_id
                row["command"] = [
                    sys.executable,
                    str(root / "scripts/ci/validate_sbml_test_suite.py"),
                    "--suite-dir",
                    str(document["suite_dir"]),
                    "--only-case",
                    f"{category}/{case_id}",
                    "--isolate-cases",
                    "--json",
                    str(replay / "report.json"),
                    "--artifacts-dir",
                    str(replay / "artifacts"),
                ]
                for option, key in (
                    ("t-end", "t_end"),
                    ("n-steps", "n_steps"),
                    ("rtol", "rtol"),
                    ("atol", "atol"),
                ):
                    row["command"] += [f"--simulation-{option}", str(protocol[key])]
    matrix = yaml.safe_load(
        (
            Path(__file__).resolve().parents[2] / "provenance/capability-matrix.yml"
        ).read_text()
    )
    capabilities = inventory.discover_capabilities(
        Path(__file__).resolve().parents[2], matrix["validation_capabilities"]
    )
    reporting.attach_coverage(capabilities, results)

    source_provenance = document.get("source_provenance") or {}
    if not isinstance(source_provenance, dict):
        source_provenance = {}
    runtime = document.get("runtime_provenance") or {}
    if not isinstance(runtime, dict):
        runtime = {}
    revision = _external_revision(document)
    issue_inventory = {"scope": "mapped-only"}
    if issues_bytes is not None:
        issue_inventory = {
            "scope": "provided-snapshot",
            "path": "issues-input.json",
            "sha256": hashlib.sha256(issues_bytes).hexdigest(),
        }
    report = {
        "schema_version": 1,
        "generated_by": "tests.validation.ci_report external report triage",
        "source": {
            "revision": revision,
            "dirty": (
                not source_provenance["bng3_worktree_clean_for_report"]
                if type(source_provenance.get("bng3_worktree_clean_for_report")) is bool
                else None
            ),
            "external_report_format": input_format,
            "external_report_path": str(input_path.resolve()),
            "external_report_sha256": hashlib.sha256(input_bytes).hexdigest(),
        },
        "subject": {
            "binary": runtime.get("native_extension_resolved_path")
            or runtime.get("native_extension_path"),
            "sha256": runtime.get("native_extension_sha256"),
        },
        "configuration": {
            "environment": {},
            "external_report_format": input_format,
            "external_report_schema_version": document.get("schema_version"),
            "external_report_summary": document.get(
                "summary", document.get("counts", {})
            ),
            "case_selection": selection,
        },
        "references": {
            "external_report": {
                key: document[key]
                for key in (
                    "suite_source_lock",
                    "suite_commit",
                    "manifest",
                    "inventory",
                    "writer_sbml_version",
                    "simulation",
                    "official_conformance",
                )
                if key in document
            },
            "libroadrunner": {"version": runtime.get("roadrunner_version")},
        },
        "issue_inventory": issue_inventory,
        "issue_coverage": reporting.issue_coverage(capabilities, results, issues),
        "capabilities": capabilities,
        "corpus": [],
        "results": results,
        "failure_clusters": reporting.cluster_failures(results),
        "history": {
            "comparable": False,
            "reason": "no retained external-report baseline supplied",
        },
        "existing_lanes": {},
    }
    report["investigation_tasks"] = reporting.investigation_tasks(
        report, input_path.parent / "external-replay"
    )
    for task in report["investigation_tasks"]:
        task["replay_status"] = (
            "PREPARED_NOT_EXECUTED" if task["reproduce_command"] else "NOT_TESTED"
        )
        task["replay_requirements"] = [
            "Check out the recorded source revision and restore its runtime/native identities before replay.",
            "Restore the pinned suite/cache and use a fresh replay directory; retained paths may be unavailable on this host.",
        ]
        if not task["reproduce_command"]:
            task["replay_requirements"].append(
                "The retained report lacks a complete bounded scientific replay recipe; inspect its original command and cache provenance."
            )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--input-format", choices=("ssts", "biomodels"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--issues-json", type=Path)
    args = parser.parse_args(argv)
    try:
        input_bytes = args.report.read_bytes()
        report = json.loads(input_bytes)
    except (OSError, ValueError) as exc:
        print(f"::error title=Missing conformance evidence::{_escape(exc)}")
        return 1
    if args.input_format:
        if not isinstance(report, dict):
            print("::error title=Invalid external report::report must be an object")
            return 1
        if args.output_dir is None:
            parser.error("external report triage requires --output-dir")
        output = args.output_dir.resolve()
        protected = {
            args.report.resolve(),
            output / "report.json",
            output / "input-report.json",
            output / "investigation-tasks.json",
            output / "issue-coverage.json",
            output / "report.md",
        }
        if args.issues_json:
            protected.add(args.issues_json.resolve())
        if args.summary.resolve() in protected:
            parser.error("summary cannot overwrite retained report evidence")
        if (
            output == args.report.resolve()
            or output / "report.json" == args.report.resolve()
        ):
            parser.error("external report output cannot overwrite its input")
        if output.exists() and any(output.iterdir()):
            parser.error("external report output directory must be empty")
        issue_bytes = None
        issue_snapshot = None
        if args.issues_json:
            try:
                issue_bytes = args.issues_json.read_bytes()
                issue_snapshot = json.loads(issue_bytes)
                if not isinstance(issue_snapshot, list):
                    raise ValueError("issue snapshot must be a list")
                from .reporting import issue_coverage

                issue_coverage([], [], issue_snapshot)
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                parser.error(f"invalid issue snapshot: {exc}")
        reported_revision = _external_revision(report)
        if args.revision and reported_revision != args.revision:
            print(
                "::error title=External report identity mismatch::"
                + _escape(
                    f"expected BNG3 revision {args.revision!r}, report records {reported_revision!r}"
                )
            )
            return 1
        try:
            triage = _external_report(
                report,
                args.input_format,
                args.report,
                input_bytes,
                issue_snapshot,
                issue_bytes,
                output,
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"::error title=Invalid external report::{_escape(exc)}")
            return 1
        output.mkdir(parents=True, exist_ok=True)
        (output / "input-report.json").write_bytes(input_bytes)
        if issue_bytes is not None:
            (output / "issues-input.json").write_bytes(issue_bytes)
        (output / "report.json").write_text(
            json.dumps(triage, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        (output / "investigation-tasks.json").write_text(
            json.dumps(triage["investigation_tasks"], indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (output / "issue-coverage.json").write_text(
            json.dumps(triage["issue_coverage"], indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        from .reporting import markdown

        (output / "report.md").write_text(markdown(triage), encoding="utf-8")
        return publish(triage, args.summary, strict=args.strict, revision=args.revision)
    if args.output_dir or args.issues_json:
        parser.error("--output-dir and --issues-json require --input-format")
    return publish(report, args.summary, strict=args.strict, revision=args.revision)


if __name__ == "__main__":
    raise SystemExit(main())
