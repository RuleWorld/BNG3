"""Deterministic tracking and portable delegation for existing validation reports.

No commands from reports are executed here. Similar symptoms remain separate
until a human establishes shared cause. Reviewed baselines affect only this
additional novelty gate, never the original scientific validation result.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil

from . import campaign, reporting

ROOT = Path(__file__).resolve().parents[2]
BAD = reporting.BAD
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def normalize(value, report_root=None):
    """Normalize only known relocation roots; retain numbers and semantic IDs."""
    text = json.dumps(value, sort_keys=True, allow_nan=False)
    roots = [(str(ROOT), "<WORKSPACE>")]
    if report_root:
        roots.append((str(Path(report_root).resolve()), "<REPORT>"))
    for source, replacement in sorted(roots, key=lambda pair: -len(pair[0])):
        text = re.sub(re.escape(source) + r"(?=$|/)", replacement, text)
    return json.loads(text)


def comparison_key(report, report_root=None):
    # An explicit producer key includes its own runtime/corpus qualification.
    # Otherwise retain full config, input digests, oracle identities and runtime.
    key = report.get("comparison_key") or digest(
        normalize(
            {
                "configuration": report.get("configuration"),
                "inputs": report.get("inputs"),
                "references": report.get("references"),
                "platform": report.get("platform"),
                "generated_by": report.get("generated_by"),
            },
            report_root,
        )
    )
    if not isinstance(key, str) or not _SHA256.fullmatch(key):
        raise ValueError("comparison key must be a SHA-256 digest")
    return key


def _leaves(report):
    result = {}
    for row in report.get("results", []):
        if (
            not isinstance(row.get("id"), str)
            or row.get("status") not in campaign.STATUSES
        ):
            raise ValueError("invalid result identity/status")
        if row["id"] in result:
            raise ValueError("duplicate result identity: " + row["id"])
        result[row["id"]] = row
    return {key: row for key, row in result.items() if not row.get("aggregate")}


def _category(row):
    if (
        row.get("evidence_kind") == "diagnostic-only"
        or row.get("supported_execution") is False
    ):
        return (
            "DIAGNOSTIC_CONTRACT_FAILURE"
            if row["status"] in BAD
            else "DIAGNOSTIC_CONTROL"
        )
    return {
        "HARNESS_ERROR": "INFRASTRUCTURE_FAILURE",
        "TIMEOUT": "RESOURCE_LIMIT_UNCERTAIN",
        "FAIL": "APPLICATION_OR_CONTRACT_FAILURE",
        "INVALID_INPUT": "INVALID_TEST_INPUT",
        "UNSUPPORTED": "UNSUPPORTED_INPUT",
        "NOT_TESTED": "EVIDENCE_GAP",
        "PASS": "PASS",
    }[row["status"]]


def _fingerprint(row, report_root):
    return digest(
        normalize(
            {
                "case_id": row["id"],
                "stage": row.get("stage"),
                "check": row.get("check"),
                "status": row["status"],
                "observation": row.get(
                    "first_difference",
                    row.get("failure_summary") or row.get("detail", ""),
                ),
                "category": _category(row),
            },
            report_root,
        )
    )


def _baseline_entries(baseline):
    if baseline is None:
        return {}
    if (
        not isinstance(baseline, dict)
        or baseline.get("schema_version") != 1
        or not isinstance(baseline.get("entries"), list)
    ):
        raise ValueError("invalid reviewed baseline schema")
    entries = {}
    for entry in baseline["entries"]:
        if not isinstance(entry, dict):
            raise ValueError("reviewed baseline entries must be objects")
        evidence = entry.get("evidence", [])
        fingerprint = entry.get("fingerprint")
        key = entry.get("comparison_key")
        if not isinstance(evidence, list) or not _SHA256.fullmatch(
            str(fingerprint or "")
        ):
            raise ValueError("known baseline requires valid fingerprint and evidence")
        if not _SHA256.fullmatch(str(key or "")):
            raise ValueError("known baseline requires a SHA-256 comparison key")
        revisions, report_hashes = set(), set()
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError("baseline evidence records must be objects")
            report_hash = item.get("report_sha256")
            revision = item.get("source_revision")
            if (
                item.get("fingerprint") != fingerprint
                or item.get("comparison_key") != key
                or not isinstance(report_hash, str)
                or not _SHA256.fullmatch(report_hash)
                or not isinstance(revision, str)
                or not _REVISION.fullmatch(revision)
            ):
                raise ValueError(
                    "baseline evidence has invalid hash, revision, fingerprint or configuration"
                )
            report_hashes.add(report_hash)
            revisions.add(revision)
        if len(report_hashes) < 2 or len(revisions) != 1:
            raise ValueError(
                "known baseline requires two matching reproduction evidence records"
            )
        if (
            not isinstance(entry.get("case_id"), str)
            or not entry["case_id"]
            or type(entry.get("issue")) is not int
            or entry["issue"] < 1
            or any(
                not isinstance(entry.get(k), str) or not entry[k].strip()
                for k in ("reviewed_by", "reason")
            )
        ):
            raise ValueError(
                "known baseline requires explicit review and issue reference"
            )
        identity = (entry["comparison_key"], entry["case_id"], entry["fingerprint"])
        if identity in entries:
            raise ValueError("duplicate baseline fingerprint")
        entries[identity] = entry
    return entries


def _validate_previous(previous):
    if previous is None:
        return
    if (
        not isinstance(previous, dict)
        or previous.get("schema_version") != 1
        or not isinstance(previous.get("report_sha256"), str)
        or not _SHA256.fullmatch(previous["report_sha256"])
        or not isinstance(previous.get("comparison_key"), str)
        or not _SHA256.fullmatch(previous["comparison_key"])
    ):
        raise ValueError("invalid previous triage ledger identity")
    source = previous.get("source")
    if (
        not isinstance(source, dict)
        or source.get("dirty") is not False
        or not isinstance(source.get("revision"), str)
        or not _REVISION.fullmatch(source["revision"])
    ):
        raise ValueError("previous triage ledger has dirty or unverifiable source")
    observations = previous.get("observations")
    if not isinstance(observations, dict):
        raise ValueError("previous triage ledger observations must be an object")
    for case_id, observation in observations.items():
        if (
            not isinstance(case_id, str)
            or not isinstance(observation, dict)
            or observation.get("status") not in campaign.STATUSES
            or not isinstance(observation.get("fingerprint"), str)
            or not _SHA256.fullmatch(observation["fingerprint"])
        ):
            raise ValueError("previous triage ledger has invalid observation identity")


def _replicate_identity(report, report_root):
    subject = report.get("subject")
    if (
        not isinstance(subject, dict)
        or not isinstance(subject.get("sha256"), str)
        or not _SHA256.fullmatch(subject["sha256"])
    ):
        raise ValueError("replicate identity requires a pinned subject SHA-256")
    return digest(
        normalize(
            {
                "subject": subject,
                "comparison_key": comparison_key(report, report_root),
                "references": report.get("references"),
                "inputs": report.get("inputs"),
                "configuration": report.get("configuration"),
                "platform": report.get("platform"),
            },
            report_root,
        )
    )


def analyze(report, *, previous=None, baseline=None, replicates=(), report_root=None):
    rows = _leaves(report)
    key = comparison_key(report, report_root)
    report_hash = digest(report)
    _validate_previous(previous)
    trials = [(report_hash, report, rows)]
    seen = {report_hash}
    replicate_identity = (
        _replicate_identity(report, report_root) if replicates else None
    )
    for repeat in replicates:
        repeat_hash = digest(repeat)
        if repeat_hash in seen:
            raise ValueError("duplicate replicate report is not a new execution")
        seen.add(repeat_hash)
        if (
            repeat.get("source") != report.get("source")
            or _replicate_identity(repeat, report_root) != replicate_identity
        ):
            raise ValueError(
                "replicate revision/configuration/oracle/subject identity differs"
            )
        trials.append((repeat_hash, repeat, _leaves(repeat)))
    known = _baseline_entries(baseline)
    comparable = bool(previous and previous.get("comparison_key") == key)
    old = previous.get("observations", {}) if comparable else {}
    source = report.get("source")
    clean = (
        isinstance(source, dict)
        and source.get("dirty") is False
        and isinstance(source.get("revision"), str)
        and _REVISION.fullmatch(source["revision"]) is not None
    )
    errors = [] if clean else ["source identity is dirty or unverifiable"]
    expected = report.get("expected_contract_ids", [])
    all_ids = {r["id"] for r in report.get("results", [])}
    errors += ["missing contract: " + name for name in sorted(set(expected) - all_ids)]
    observations, findings = {}, []
    for case_id, row in sorted(rows.items()):
        fingerprint = _fingerprint(row, report_root)
        observation = {
            "status": row["status"],
            "fingerprint": fingerprint,
            "stage": row.get("stage"),
            "category": _category(row),
            "issues": sorted(set(row.get("related_issues", []))),
        }
        observations[case_id] = observation
        if row["status"] not in BAD:
            continue
        prior = old.get(case_id)
        novelty = "UNBASELINED" if not comparable else "NEW_FAILURE"
        if prior:
            if prior["status"] == "PASS":
                novelty = "REGRESSION"
            elif prior["status"] in BAD:
                novelty = (
                    "REPEATED"
                    if prior["fingerprint"] == fingerprint
                    else "CHANGED_FAILURE"
                )
            elif prior["status"] == "UNSUPPORTED":
                novelty = "NEWLY_ADMITTED_FAILURE"
        baseline_entry = known.get((key, case_id, fingerprint))
        if baseline_entry and baseline_entry["issue"] not in observation["issues"]:
            raise ValueError("known baseline issue is not mapped to the observed case")
        if baseline_entry and novelty != "REGRESSION":
            novelty = "KNOWN"
        evidence, outcomes, mismatches = [], set(), False
        for trial_hash, trial, trial_rows in trials:
            match = trial_rows.get(case_id)
            if match:
                outcomes.add(match["status"])
                trial_fingerprint = _fingerprint(match, report_root)
                mismatches |= trial_fingerprint != fingerprint
                if trial_fingerprint == fingerprint:
                    evidence.append(
                        {
                            "report_sha256": trial_hash,
                            "source_revision": trial.get("source", {}).get("revision"),
                            "fingerprint": trial_fingerprint,
                            "comparison_key": key,
                        }
                    )
        reproduction = "NOT_REPLAYED"
        if len(trials) > 1:
            reproduction = (
                "NONDETERMINISTIC"
                if mismatches
                else "REPRODUCED" if len(evidence) >= 2 else "INCOMPLETE_REPLAY"
            )
        finding = dict(
            observation,
            case_id=case_id,
            novelty=novelty,
            reproduction=reproduction,
            reproduction_evidence=evidence,
            observed_outcomes=sorted(outcomes),
            confirmed_root_cause=None,
            confidence="observed-contract-only",
            severity="UNASSESSED",
            repair_eligible=clean
            and row["status"] == "FAIL"
            and observation["category"] == "APPLICATION_OR_CONTRACT_FAILURE"
            and reproduction == "REPRODUCED",
            first_seen=prior.get("first_seen", report_hash) if prior else report_hash,
            last_seen=report_hash,
        )
        observation["first_seen"] = finding["first_seen"]
        findings.append(finding)
    coverage_regressions = sorted(
        case_id
        for case_id, row in old.items()
        if row["status"] == "PASS"
        and observations.get(case_id, {}).get("status")
        in (None, "NOT_TESTED", "UNSUPPORTED")
    )
    unresolved = any(
        r["status"] != "PASS"
        for r in rows.values()
        if r["status"] not in BAD
        and not (
            r["status"] == "NOT_TESTED" and r.get("applicability") == "no-observables"
        )
    )
    failure = (
        errors
        or not rows
        or coverage_regressions
        or unresolved
        or any(
            f["novelty"] != "KNOWN"
            or f["reproduction"] == "NONDETERMINISTIC"
            or f["category"] != "APPLICATION_OR_CONTRACT_FAILURE"
            for f in findings
        )
    )
    return {
        "schema_version": 1,
        "source": report.get("source"),
        "report_sha256": report_hash,
        "comparison_key": key,
        "history_comparable": comparable,
        "observations": observations,
        "findings": findings,
        "evidence_errors": errors,
        "coverage_regressions": coverage_regressions,
        "outcome_counts": dict(Counter(r["status"] for r in rows.values())),
        "gate": "FAIL" if failure else "PASS",
    }


def _artifact_paths(row, task):
    evidence = row.get("evidence", [])
    paths = (list(evidence) if isinstance(evidence, list) else []) + task.get(
        "receipts", []
    )
    for receipt in task.get("recorded_commands", []):
        paths += [a["path"] for a in receipt.get("artifacts", []) if a.get("path")]
    return sorted({p for p in paths if isinstance(p, str)})


def write_bundle(
    report_path,
    output,
    *,
    previous=None,
    baseline=None,
    replicates=(),
    issues=None,
    max_file_bytes=2_000_000,
    max_packet_bytes=12_000_000,
    max_artifacts=128,
    max_report_bytes=50_000_000,
    max_tasks=200,
):
    report_path, output = Path(report_path).resolve(), Path(output).resolve()
    if any(
        type(limit) is not int or limit < 1
        for limit in (
            max_file_bytes,
            max_packet_bytes,
            max_artifacts,
            max_report_bytes,
            max_tasks,
        )
    ):
        raise ValueError("triage artifact limits must be positive integers")
    if output.exists() and any(output.iterdir()):
        raise ValueError("triage output directory must be empty")
    if output == report_path.parent or output in report_path.parents:
        raise ValueError("triage output cannot overwrite input evidence")
    if report_path.stat().st_size > max_report_bytes:
        raise ValueError("input report exceeds the triage report byte limit")
    report = json.loads(report_path.read_text())
    ledger = analyze(
        report,
        previous=previous,
        baseline=baseline,
        replicates=replicates,
        report_root=report_path.parent,
    )
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(report_path, output / "input-report.json")
    tasks = {
        t["case_id"]: t
        for t in reporting.investigation_tasks(report, report_path.parent)
    }
    rows = _leaves(report)
    packaged_tasks = 0
    for finding in ledger["findings"]:
        task = tasks.get(finding["case_id"])
        if task is None:
            continue
        if packaged_tasks >= max_tasks:
            finding["task_package"] = None
            finding["repair_eligible"] = False
            ledger["evidence_errors"].append(
                f"task package limit {max_tasks} exceeded; omitted {finding['case_id']}"
            )
            continue
        packaged_tasks += 1
        directory = output / "tasks" / finding["fingerprint"][:24]
        directory.mkdir(parents=True)
        finding["task_package"] = str(directory.relative_to(output))
        packet = dict(
            task,
            **{
                k: finding[k]
                for k in ("fingerprint", "novelty", "reproduction", "repair_eligible")
            },
        )
        packet.update(
            expected=f"Pass the named contract {finding['case_id']} against its recorded oracle and configuration.",
            report_sha256=ledger["report_sha256"],
            missing_evidence=[],
            retained_evidence=[],
        )
        used = 0
        artifact_paths = _artifact_paths(rows[finding["case_id"]], task)
        packet["missing_evidence"].extend(artifact_paths[max_artifacts:])
        for item in artifact_paths[:max_artifacts]:
            source = Path(item)
            if not source.is_absolute():
                source = report_path.parent / source
            resolved = source.resolve()
            if (
                not resolved.is_relative_to(report_path.parent)
                or not resolved.is_file()
                or resolved.stat().st_size > max_file_bytes
                or used + resolved.stat().st_size > max_packet_bytes
            ):
                packet["missing_evidence"].append(item)
                continue
            relative = resolved.relative_to(report_path.parent)
            destination = directory / "evidence" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved, destination)
            used += resolved.stat().st_size
            packet["retained_evidence"].append(
                {
                    "original": item,
                    "path": str(destination.relative_to(directory)),
                    "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                }
            )
        command = packet.get("reproduce_command") or []
        packet["repair_eligible"] &= bool(command) and not packet["missing_evidence"]
        finding["repair_eligible"] = packet["repair_eligible"]
        if packet["missing_evidence"]:
            ledger["evidence_errors"].append(
                f"missing, outside or oversized evidence for {finding['case_id']}"
            )
        (directory / "task.json").write_text(
            json.dumps(packet, indent=2, allow_nan=False) + "\n"
        )
        prompt = f"""Repair only the observed contract {finding['case_id']} at revision {task['source_revision']}.
Read task.json and the retained evidence first. Root cause is unconfirmed.
Issue references: {task['related_issues']}. Likely inspection paths (hints): {task['source_locations']}.
Expected: {packet['expected']}
Observed: {json.dumps(task['observation'], sort_keys=True)}
Replay status: {finding['reproduction']}; ready for assignment: {packet['repair_eligible']}.
Reproduction cwd: {task['reproduce_cwd']}. Restore the source, package, binary and independent oracle identities in task.json.
Command: {shlex.join(command)}
Environment: {json.dumps(task['reproduce_environment'], sort_keys=True)}
Missing or oversized evidence: {packet['missing_evidence']}.
Use an isolated branch. Reproduce before editing. If replay is unavailable or inconsistent, report the blocker; do not invent expected behavior.
Do not change tolerances, goldens, budgets, unsupported guards, or unrelated application code.
Add a focused regression, pass the named contract and its neighboring checks, and submit one isolated PR.
Acceptance: {' '.join(task['acceptance_criteria'])}
"""
        (directory / "repair-prompt.md").write_text(prompt)
        manifest = [
            {
                "path": str(p.relative_to(directory)),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in sorted(directory.rglob("*"))
            if p.is_file()
        ]
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    coverage = reporting.issue_coverage(
        report.get("capabilities", []), report["results"], issues
    )
    for row in coverage:
        relevant = [f for f in ledger["findings"] if row["number"] in f["issues"]]
        row["failure_classes"] = sorted({f["stage"] for f in relevant})
        row["detected_failure_ids"] = [f["case_id"] for f in relevant]
        row["repair_task_packages"] = [
            f["task_package"] for f in relevant if f.get("task_package")
        ]
        row["closure_eligible"] = False
    (output / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
    ledger["generated_at"] = datetime.now(timezone.utc).isoformat()
    if ledger["evidence_errors"]:
        ledger["gate"] = "FAIL"
    (output / "ledger.json").write_text(
        json.dumps(ledger, indent=2, allow_nan=False) + "\n"
    )
    lines = [
        "# Validation triage",
        "",
        f"Novelty/evidence gate: {ledger['gate']}. Original validator outcomes remain authoritative.",
        f"Outcomes: {ledger['outcome_counts']}. Findings: {len(ledger['findings'])}.",
        "",
    ]
    lines += [
        f"- {f['case_id']}: {f['novelty']}; {f['category']}; {f['reproduction']}; packet {f.get('task_package', 'unavailable')}"
        for f in ledger["findings"]
    ]
    lines += ["- " + error for error in ledger["evidence_errors"]]
    (output / "summary.md").write_text("\n".join(lines) + "\n")
    return ledger


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--replicate", type=Path, action="append", default=[])
    parser.add_argument("--issues-json", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    def read(path):
        return json.loads(path.read_text()) if path else None

    try:
        ledger = write_bundle(
            args.report,
            args.output,
            previous=read(args.previous),
            baseline=read(args.baseline),
            replicates=[read(p) for p in args.replicate],
            issues=read(args.issues_json),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"triage infrastructure error: {exc}\n")
    print(
        json.dumps(
            {
                "gate": ledger["gate"],
                "findings": len(ledger["findings"]),
                "repair_eligible": sum(
                    f["repair_eligible"] for f in ledger["findings"]
                ),
            }
        )
    )
    return int(args.strict and ledger["gate"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
