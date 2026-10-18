"""Join exact-revision observations to issues without inferring issue completion.

This is read-only evidence triage. Approval decisions, unresolved upstream drift,
and unexecuted claims stay visible; the tool never closes issues or approves locks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from . import campaign, inventory

ROOT = Path(__file__).resolve().parents[2]
FAILURES = {"FAIL", "HARNESS_ERROR", "TIMEOUT", "INVALID_INPUT"}


def build_queue(issues, reports, revision):
    if not isinstance(issues, list):
        raise ValueError("issue snapshot must be a list")
    metadata = {}
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("issue snapshot entries must be objects")
        number = issue.get("number")
        if type(number) is not int or number < 1 or number in metadata:
            raise ValueError("issue snapshot requires unique positive numbers")
        metadata[number] = issue
    observations, capability_issues, mapped, packet_ids = {}, {}, set(), {}
    for report in reports:
        if not isinstance(report, dict):
            raise ValueError("evidence report must be an object")
        if report.get("source", {}).get("dirty") is not False:
            raise ValueError(
                "dirty or unverifiable report cannot establish exact-revision evidence"
            )
        if report.get("source", {}).get("revision") != revision:
            raise ValueError(
                "report revision differs from requested issue-queue revision"
            )
        for capability in report.get("capabilities", []):
            if capability.get("kind") == "semantic-claim":
                numbers = set(capability.get("issues", []))
                capability_issues.setdefault(capability["id"], set()).update(numbers)
                mapped.update(numbers)
        for task in report.get("investigation_tasks", []):
            if task.get("case_id") and task.get("id"):
                packet_ids.setdefault(task["case_id"], set()).add(task["id"])
        seen_in_report = set()
        for row in report.get("results", []):
            if row.get("status") not in campaign.STATUSES or not row.get("id"):
                raise ValueError("invalid result identity/status")
            if row["id"] in seen_in_report:
                raise ValueError("duplicate result identity within a report")
            seen_in_report.add(row["id"])
            if row.get("aggregate"):
                continue
            # A successful command is not a successful semantic contract. Keep
            # failures actionable even if a crashing process emitted no checks.
            mapped.update(row.get("related_issues") or [])
            key = row["id"]
            observed = {
                k: row.get(k)
                for k in (
                    "status",
                    "stage",
                    "check",
                    "first_difference",
                    "related_issues",
                    "capabilities",
                    "test_file",
                )
            }
            if key in observations and observations[key] != observed:
                raise ValueError("conflicting exact-revision observations: " + key)
            observations[key] = observed
    result = []
    numbers = set(metadata) | mapped
    for row in observations.values():
        numbers.update(row.get("related_issues") or [])
    for number in sorted(numbers):
        issue = metadata.get(number, {})
        evidence = {}
        for key, row in observations.items():
            if row["status"] == "PASS" and not (
                row.get("check") or row.get("test_file")
            ):
                continue
            related = set(row.get("related_issues") or [])
            if not related:
                for capability in row.get("capabilities") or []:
                    related.update(capability_issues.get(capability, set()))
            if number in related:
                evidence[key] = row
        counts = Counter(row["status"] for row in evidence.values())
        decision = "maintainer/product decision" in (issue.get("body") or "")
        if FAILURES & counts.keys():
            disposition, action = "OBSERVED_FAILURE", "investigate-recorded-contract"
        elif decision:
            disposition, action = "DECISION_REQUIRED", "maintainer-scope-or-approval"
        elif counts.get("PASS"):
            disposition, action = (
                "PARTIAL_EXECUTION",
                "expand-named-acceptance-contracts",
            )
        elif number in mapped or evidence:
            disposition, action = "EVIDENCE_GAP", "add-or-execute-reusable-contract"
        else:
            disposition, action = "UNMAPPED", "map-acceptance-criteria-to-capabilities"
        result.append(
            dict(
                number=number,
                title=issue.get("title"),
                state=issue.get("state", "NOT_IN_SNAPSHOT"),
                disposition=disposition,
                next_action=action,
                outcomes=dict(sorted(counts.items())),
                evidence_ids=sorted(evidence),
                closure_eligible=False,
                maintainer_decision_required=decision,
                investigation_task_ids=sorted(
                    {
                        packet
                        for key in evidence
                        for packet in packet_ids.get(key, set())
                    }
                ),
            )
        )
    return result


def source_drift(lock, heads):
    rows = []
    for name, source in lock["sources"].items():
        if name == "bng3":
            continue
        observed = (heads or {}).get("sources", {}).get(name)
        status = "UNOBSERVED"
        if observed:
            observed_repository = (
                observed.get("repository", "").lower().removesuffix(".git")
            )
            if observed_repository != source["repository"].lower().removesuffix(".git"):
                raise ValueError("upstream repository identity differs: " + name)
            if observed.get("branch") != source["branch"]:
                raise ValueError("upstream branch identity differs: " + name)
            revision = observed.get("revision")
            if revision is None:
                status = "UNAVAILABLE"
            elif not isinstance(revision, str) or not re.fullmatch(
                "[0-9a-f]{40}", revision
            ):
                raise ValueError("invalid upstream revision: " + name)
            else:
                status = "MATCHES_LOCK" if revision == source["revision"] else "DRIFTED"
        rows.append(
            dict(
                source=name,
                locked_revision=source["revision"],
                observed_revision=(observed or {}).get("revision"),
                status=status,
                approval=source.get("status"),
                related_issues=[137, 179, 180],
            )
        )
    return rows


def collect_heads(lock, directory):
    sources = {}
    for name, source in lock["sources"].items():
        if name == "bng3":
            continue
        work = directory / name
        receipt = campaign.run_command(
            [
                "git",
                "ls-remote",
                "--refs",
                source["repository"],
                "refs/heads/" + source["branch"],
            ],
            work,
            20,
        )
        lines = (work / "stdout.log").read_text().splitlines()
        revision = None
        if receipt["status"] == "PASS" and len(lines) == 1:
            fields = lines[0].split()
            if len(fields) == 2 and fields[1] == "refs/heads/" + source["branch"]:
                revision = fields[0]
        sources[name] = dict(
            repository=source["repository"],
            branch=source["branch"],
            revision=revision,
            receipt=str(work / "command.json"),
        )
    return dict(sources=sources)


def provenance_debt(heads=None):
    from scripts.validate_provenance import validate_lock, validate_ledger
    from scripts.validate_reconciliation_tests import (
        CLAIM_CLASSIFICATIONS,
        evidence_inventory,
        load_ledgers,
        validate_test_references,
    )

    lock = json.loads((ROOT / "provenance/upstreams.lock.yml").read_text())
    errors, warnings = validate_lock(lock, require_approved=True, repository_root=ROOT)
    ledgers = load_ledgers(ROOT / "provenance/reconciliation")
    claims = []
    for path, ledger in ledgers:
        for entry in ledger.get("entries", []):
            if entry.get("classification") not in CLAIM_CLASSIFICATIONS:
                continue
            claims.append(
                dict(
                    source=ledger.get("source", path.stem),
                    source_revision=entry.get("source_revision"),
                    capability=entry.get("capability"),
                    tests=entry.get("tests", []),
                    evidence=(
                        "REFERENCE_ONLY" if entry.get("tests") else "NO_TEST_REFERENCE"
                    ),
                    execution_claim=False,
                    related_issues=[180],
                )
            )
    return dict(
        inputs={
            str(path.relative_to(ROOT)): inventory.sha256(path)
            for path in [
                ROOT / "provenance/upstreams.lock.yml",
                *[path for path, _ in ledgers],
            ]
        },
        strict_approval_errors=errors,
        warnings=warnings,
        source_drift=source_drift(lock, heads),
        reconciliation_inventory=evidence_inventory(ledgers),
        ledger_errors=[
            error for _, ledger in ledgers for error in validate_ledger(ledger, lock)
        ],
        stale_test_references=validate_test_references(ledgers, ROOT),
        reconciliation_claims=claims,
        approvals_modified=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues-json", type=Path, required=True)
    parser.add_argument("--report", action="append", type=Path, default=[])
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--upstream-heads", type=Path)
    parser.add_argument("--collect-upstream-heads", action="store_true")
    args = parser.parse_args(argv)
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("output directory must be empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.revision != campaign.git(ROOT, "rev-parse", "HEAD"):
            raise ValueError("requested revision differs from checked-out candidate")
        issues_bytes = args.issues_json.read_bytes()
        issues = json.loads(issues_bytes)
        reports = [json.loads(path.read_text()) for path in args.report]
        heads = (
            json.loads(args.upstream_heads.read_text()) if args.upstream_heads else None
        )
        if args.collect_upstream_heads:
            if heads is not None:
                raise ValueError(
                    "choose a supplied or collected upstream snapshot, not both"
                )
            lock = json.loads((ROOT / "provenance/upstreams.lock.yml").read_text())
            heads = collect_heads(lock, args.output_dir / "upstream-commands")
        queue = build_queue(issues, reports, args.revision)
        report = dict(
            schema_version=1,
            revision=args.revision,
            issue_snapshot_sha256=inventory.sha256(args.issues_json),
            issue_snapshot_scope="provided snapshot; collection completeness not inferred",
            evidence_reports=[
                dict(path=str(p), sha256=inventory.sha256(p)) for p in args.report
            ],
            queue=queue,
            provenance=provenance_debt(heads),
        )
        (args.output_dir / "issues-input.json").write_bytes(issues_bytes)
        if heads is not None:
            (args.output_dir / "upstream-heads.json").write_text(
                json.dumps(heads, indent=2) + "\n"
            )
        (args.output_dir / "issue-queue.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        lines = [
            "# Issue evidence queue",
            "",
            f"Candidate: `{args.revision}`. No issue is automatically qualified for closure.",
            "",
            "| Issue | Disposition | Executed outcomes | Next action |",
            "| --- | --- | --- | --- |",
        ]
        for row in queue:
            lines.append(
                f"| [#{row['number']}](https://github.com/RuleWorld/BNG3/issues/{row['number']}) | {row['disposition']} | {row['outcomes']} | {row['next_action']} |"
            )
        debt = report["provenance"]
        lines += [
            "",
            f"Strict approval blockers: {len(debt['strict_approval_errors'])}; stale reconciliation references: {len(debt['stale_test_references'])}.",
            "Reconciliation test references are source evidence, not proof of current execution. See issue-queue.json for named claims and upstream observations.",
            "",
        ]
        (args.output_dir / "issue-queue.md").write_text("\n".join(lines))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        (args.output_dir / "error.json").write_text(
            json.dumps(dict(status="HARNESS_ERROR", detail=str(exc)), indent=2) + "\n"
        )
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
