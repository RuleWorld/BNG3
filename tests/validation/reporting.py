"""Actionable reports without promoting test counts into support claims."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
import re
from collections import Counter

from .campaign import STATUSES

BAD = {"FAIL", "TIMEOUT", "HARNESS_ERROR"}


def attach_coverage(capabilities: list[dict], results: list[dict]) -> None:
    for capability in capabilities:
        matched = []
        for result in results:
            explicit = capability["id"] in result.get("capabilities", [])

            def matches(test):
                path, _, node = test.partition("::")
                file_match = path.replace("/", ".").removesuffix(".py") in result[
                    "id"
                ] or (
                    result.get("test_file")
                    and (
                        result["test_file"] == path
                        or result["test_file"].startswith(path.rstrip("/") + "/")
                    )
                )
                name = result.get("name", result["id"])
                node_match = (
                    not node
                    or ("::" + node) in name
                    and (name.endswith("::" + node) or ("::" + node + "[") in name)
                )
                return file_match and node_match

            mapped = any(matches(test) for test in capability["existing_tests"])
            if explicit or mapped:
                matched.append(result)
        executed = [r for r in matched if r["status"] != "NOT_TESTED"]
        capability["coverage"] = "PARTIAL" if executed else "NOT_TESTED"
        capability["result_counts"] = dict(Counter(r["status"] for r in matched))
        capability["evidence_ids"] = [r["id"] for r in matched]
        for result in matched:
            result["mapped_capabilities"] = sorted(
                set(result.get("mapped_capabilities", [])) | {capability["id"]}
            )
            result["related_issues"] = sorted(
                set(result.get("related_issues", []))
                | set(capability.get("issues", []))
            )
            if capability.get("implementation"):
                result["source_locations"] = sorted(
                    set(result.get("source_locations", []))
                    | {capability["implementation"]["path"]}
                )


def issue_coverage(
    capabilities: list[dict], results: list[dict], issues: list[dict] | None = None
) -> list[dict]:
    """Roll up observed leaf evidence; neither closed issues nor PASS imply done.

    Without a supplied issue snapshot the denominator is only mapped issues,
    not the repository backlog. Callers retain the snapshot and its digest.
    """
    metadata = {}
    for issue in issues or []:
        if not isinstance(issue, dict):
            raise ValueError("issue snapshot entries must be objects")
        number = issue.get("number")
        if type(number) is not int or number < 1 or number in metadata:
            raise ValueError("issue snapshot requires unique positive integer numbers")
        if "title" in issue and not isinstance(issue["title"], str):
            raise ValueError("issue snapshot titles must be strings")
        if "state" in issue and issue["state"] not in {"OPEN", "CLOSED"}:
            raise ValueError("issue snapshot state must be OPEN or CLOSED")
        metadata[number] = issue
    identities = [result["id"] for result in results]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate result identities cannot be issue evidence")
    if any(result["status"] not in STATUSES for result in results):
        raise ValueError("unknown result status cannot be issue evidence")
    claims = [c for c in capabilities if c.get("kind") == "semantic-claim"]
    numbers = set(metadata)
    for row in claims:
        numbers.update(row.get("issues", []))
    for row in results:
        numbers.update(row.get("related_issues", []))

    rows = []
    for number in sorted(numbers):
        mapped = [c for c in claims if number in c.get("issues", [])]
        mapped_ids = {
            identity for c in mapped for identity in c.get("evidence_ids", [])
        }
        evidence = [
            r
            for r in results
            if not r.get("aggregate")
            and (r["id"] in mapped_ids or number in r.get("related_issues", []))
        ]
        executed = {r["id"] for r in evidence if r["status"] != "NOT_TESTED"}
        rows.append(
            {
                "number": number,
                "title": metadata.get(number, {}).get("title"),
                "state": metadata.get(number, {}).get("state"),
                "coverage": "PARTIAL" if executed else "NOT_TESTED",
                "capabilities": sorted(c["id"] for c in mapped),
                "test_references": sorted(
                    {p for c in mapped for p in c.get("existing_tests", [])}
                ),
                "evidence_ids": sorted(r["id"] for r in evidence),
                "result_counts": dict(
                    sorted(Counter(r["status"] for r in evidence).items())
                ),
                "unexecuted_capabilities": sorted(
                    c["id"]
                    for c in mapped
                    if not (set(c.get("evidence_ids", [])) & executed)
                ),
                "remaining_qualification": {
                    c["id"]: c["missing_tests"]
                    for c in mapped
                    if c.get("missing_tests")
                },
            }
        )
    return rows


def cluster_failures(results: list[dict]) -> list[dict]:
    groups = {}
    for row in results:
        if row["status"] not in BAD or row.get("aggregate"):
            continue
        signature = re.sub(
            r"\b\d+(?:\.\d+)?\b",
            "#",
            (row.get("failure_summary") or row.get("detail", ""))[:1000],
        )
        key = hashlib.sha256(
            (row["status"] + row["stage"] + signature).encode()
        ).hexdigest()[:16]
        group = groups.setdefault(
            key,
            {
                "id": key,
                "status": row["status"],
                "first_observed_stage": row["stage"],
                "signature": signature,
                "cases": [],
                "capabilities": [],
                "diagnosis_confidence": "signature-only",
                "confirmed_root_cause": None,
            },
        )
        group["cases"].append(row["id"])
        group["capabilities"] = sorted(
            set(group["capabilities"])
            | set(row.get("capabilities", []))
            | set(row.get("mapped_capabilities", []))
        )
    for group in groups.values():
        group["priority_score"] = (
            3 if group["status"] == "HARNESS_ERROR" else 2
        ) * len(group["cases"]) + len(group["capabilities"])
        group["next_action"] = (
            "Verify inputs/reference identity"
            if group["status"] == "HARNESS_ERROR"
            else "Reproduce earliest recorded divergence; minimize while preserving the same signature"
        )
    return sorted(groups.values(), key=lambda g: (-g["priority_score"], g["id"]))


def history(current: dict, previous: dict | None) -> dict:
    if previous is None:
        return {"comparable": False, "reason": "no baseline"}
    if current["comparison_key"] != previous.get("comparison_key"):
        return {
            "comparable": False,
            "reason": "configuration, corpus, tests or reference identity changed",
        }

    def leaf_statuses(report):
        statuses = {}
        for row in report["results"]:
            if row.get("aggregate"):
                continue
            if row["id"] in statuses:
                raise ValueError("duplicate history result identity: " + row["id"])
            statuses[row["id"]] = row["status"]
        return statuses

    old = leaf_statuses(previous)
    new = leaf_statuses(current)
    return {
        "comparable": True,
        "new_failures": sorted(
            k for k in new if new[k] in BAD and old.get(k) == "PASS"
        ),
        "resolved": sorted(k for k in old if old[k] in BAD and new.get(k) == "PASS"),
        "newly_executed": sorted(new.keys() - old.keys()),
        "no_longer_executed": sorted(old.keys() - new.keys()),
        # A newly admitted semantic failure differs from a broken harness.
        "newly_admitted_failures": sorted(
            k for k in new if old.get(k) == "UNSUPPORTED" and new[k] == "FAIL"
        ),
        "unsupported_to_supported": sorted(
            k for k in new if old.get(k) == "UNSUPPORTED" and new[k] == "PASS"
        ),
        "coverage_regressions": sorted(
            k
            for k in old
            if old[k] == "PASS" and new.get(k) in {None, "NOT_TESTED", "UNSUPPORTED"}
        ),
    }


def _obligation_list(obligations):
    if obligations is None:
        return []
    if isinstance(obligations, dict):
        if "obligations" in obligations:
            obligations = obligations["obligations"]
        else:
            acceptance = obligations.get("acceptance", {})
            obligations = (
                acceptance.get("obligations", [])
                if isinstance(acceptance, dict)
                else []
            )
    if not isinstance(obligations, list):
        raise ValueError("obligations must be a list or an obligations object")
    return [item for item in obligations if isinstance(item, dict)]


def _identity_present(requirement, check, report):
    """Resolve explicit dotted identity paths without guessing aliases."""
    if not isinstance(requirement, str) or not requirement:
        return False
    pieces = requirement.split(".")
    roots = {
        "source": check.get("candidate_identity", report.get("source", {})),
        "candidate_identity": check.get("candidate_identity", report.get("source", {})),
        "references": check.get("oracle_identities", report.get("references", {})),
        "oracle_identities": check.get(
            "oracle_identities", report.get("references", {})
        ),
    }
    value = roots.get(pieces[0])
    if value is None:
        return False
    for piece in pieces[1:]:
        if not isinstance(value, dict) or piece not in value:
            return False
        value = value[piece]
    return value is not None and value != ""


def _affected_obligations(row, obligations, report):
    """Attach only obligations whose evaluated check ID exactly names the leaf."""
    affected = []
    for obligation in obligations:
        checks = obligation.get("checks", [])
        required = obligation.get("required_checks", [])
        if not isinstance(checks, list):
            continue
        exact = [
            check
            for check in checks
            if isinstance(check, dict)
            and check.get("id") == row.get("id")
            and check.get("status") in BAD
        ]
        if not exact:
            continue
        check = exact[0]
        required_by_id = {
            item.get("id"): item
            for item in required
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        required_ids = [
            item.get("id")
            for item in required
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        evaluated_by_id = {
            item.get("id"): item
            for item in checks
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        missing_checks = {
            check_id
            for check_id in required_ids
            if check_id not in evaluated_by_id
            or evaluated_by_id[check_id].get("status") in {"NOT_TESTED", "UNSUPPORTED"}
        }
        declared_missing = obligation.get("missing_evidence", [])
        if isinstance(declared_missing, list):
            missing_checks.update(
                item
                for item in declared_missing
                if isinstance(item, str) and item in required_by_id
            )
        missing_identities = set()
        for check_id in required_ids:
            metadata = required_by_id[check_id]
            evaluated = evaluated_by_id.get(check_id)
            if evaluated is None:
                continue
            requirements = metadata.get("identity_requirements", [])
            if not isinstance(requirements, list):
                continue
            for identity in requirements:
                if not _identity_present(identity, evaluated, report):
                    missing_identities.add(f"{check_id}:{identity}")
            gaps = evaluated.get("missing_evidence", [])
            if isinstance(gaps, list):
                missing_identities.update(
                    gap.removeprefix("identity:")
                    for gap in gaps
                    if isinstance(gap, str) and gap.startswith("identity:")
                )
        if isinstance(declared_missing, list):
            for gap in declared_missing:
                if isinstance(gap, str) and "." in gap:
                    missing_identities.add(gap)
        metadata = required_by_id.get(row.get("id"), check)
        boundary = (
            check.get("first_observed_boundary")
            or check.get("boundary")
            or row.get("stage")
        )
        affected.append(
            {
                "id": obligation.get("id"),
                "required_check": row.get("id"),
                "evidence_kind": metadata.get("evidence_kind"),
                "expectation": metadata.get("expectation"),
                "missing_required_checks": sorted(missing_checks),
                "missing_identities": sorted(missing_identities),
                "missing_evidence": (
                    sorted(item for item in declared_missing if isinstance(item, str))
                    if isinstance(declared_missing, list)
                    else []
                ),
                "first_observed_boundary": boundary,
                "retained_reproducer_status": "PENDING_PACKET_RETENTION",
                "candidate_identity": check.get("candidate_identity"),
                "oracle_identities": check.get("oracle_identities"),
            }
        )
    return affected


def investigation_tasks(
    report: dict, directory: Path, *, obligations=None
) -> list[dict]:
    """One bounded work packet per observed leaf failure; no inferred diagnosis."""
    obligations = _obligation_list(
        report.get("acceptance", {}).get("obligations", [])
        if obligations is None and isinstance(report.get("acceptance"), dict)
        else obligations
    )
    tasks = []
    for row in report["results"]:
        if row["status"] not in BAD or row.get("aggregate"):
            continue
        # A suite exit duplicates its named failing cases. Preserve the receipt
        # on those cases rather than asking a second agent to diagnose exit=1.
        if row["id"].endswith(":process") and any(
            r is not row
            and r["status"] in BAD
            and r.get("receipt") == row.get("receipt")
            for r in report["results"]
        ):
            continue
        check = row.get("check", row["stage"])
        explicit_command = row.get("command")
        command = (
            list(explicit_command)
            if isinstance(explicit_command, list)
            and all(isinstance(part, str) for part in explicit_command)
            else []
        )
        if not command and row.get("model"):
            root = Path(__file__).resolve().parents[2]
            command = [
                sys.executable,
                str(root / "scripts/validate.py"),
                "--tier",
                "smoke",
                "--suite",
                "harness",
                "--models",
                row["model"],
                "--bng-cpp",
                report["subject"]["binary"],
                "--report-dir",
                str(
                    directory.parent
                    / ("replay-" + hashlib.sha256(row["id"].encode()).hexdigest()[:12])
                ),
            ]
            config = report["configuration"]
            for option, key in (
                ("--network-iterations", "network_iterations"),
                ("--max-aggregate", "max_aggregate"),
                ("--case-timeout", "case_timeout"),
            ):
                if key in config:
                    command += [option, str(config[key])]
            ref = report["references"].get("bionetgen", {})
            if ref:
                command += ["--bng2-root", ref["path"]]
                if ref.get("network_binary_sha256"):
                    command += ["--bng2-network-sha256", ref["network_binary_sha256"]]
            if config.get("net_reload"):
                command += ["--net-reload"]
            if config.get("simulate"):
                command += [
                    "--simulate",
                    "--simulation-end",
                    str(config["simulation_protocol"]["t_end"]),
                    "--simulation-steps",
                    str(config["simulation_protocol"]["n_steps"]),
                ]
        elif (
            not command and row.get("test_file", "").endswith(".py") and row.get("name")
        ):
            node = row["test_file"] + (
                "::" + row["name"].split("::", 1)[1] if "::" in row["name"] else ""
            )
            command = [sys.executable, "-m", "pytest", node, "-q"]
            if row["test_file"].startswith("tests/validation/"):
                command[3:3] = ["-c", "tests/validation/pytest.ini"]
                command += ["--bng-cpp", report["subject"]["binary"]]
        elif not command and row.get("command"):
            command = row["command"]
        replay_env = {"BNG3_CI_STRICT_ORACLES": "1"}
        replay_env.update(
            {
                key: value
                for key, value in report["configuration"].get("environment", {}).items()
                if value is not None
            }
        )
        reference = report["references"].get("bionetgen", {})
        if reference:
            replay_env.update(
                BNG2_PERL=reference["script"],
                BNGPATH=str(Path(reference["script"]).parent),
                PERL=reference.get("interpreter", "perl"),
            )
            if reference.get("network_binary_sha256"):
                replay_env["BNG2_NETWORK_SHA256"] = reference["network_binary_sha256"]
        receipts = list(row.get("receipts", [])) + (
            [row["receipt"]] if row.get("receipt") else []
        )
        recorded = []
        receipt_records = []
        for receipt in receipts:
            if not isinstance(receipt, (str, Path)):
                receipt_records.append(
                    {
                        "path": repr(receipt),
                        "resolved_path": None,
                        "status": "malformed",
                        "error": "receipt path must be a string or path",
                    }
                )
                continue
            path = Path(receipt)
            resolved = path if path.is_absolute() else directory / path
            record = {"path": str(receipt), "resolved_path": str(resolved)}
            try:
                value = json.loads(resolved.read_text())
            except FileNotFoundError:
                record.update(status="missing", error="receipt file not found")
            except json.JSONDecodeError as exc:
                record.update(status="malformed", error=f"invalid JSON: {exc}")
            except UnicodeError as exc:
                record.update(
                    status="malformed", error=f"invalid receipt encoding: {exc}"
                )
            except OSError as exc:
                record.update(status="error", error=f"could not read receipt: {exc}")
            else:
                if not isinstance(value, dict):
                    record.update(
                        status="malformed", error="receipt JSON must be an object"
                    )
                else:
                    record["status"] = "loaded"
                    recorded.append(value)
            receipt_records.append(record)
        task = dict(
            id=hashlib.sha256(row["id"].encode()).hexdigest()[:16],
            case_id=row["id"],
            check=check,
            stage=row["stage"],
            status=row["status"],
            model=row.get("model"),
            source_revision=report["source"]["revision"],
            source=report["source"],
            source_dirty=report["source"].get("dirty"),
            subject=report["subject"],
            references=report["references"],
            configuration=report["configuration"],
            platform=report.get("platform"),
            diagnosis_confidence="observed-contract-failure",
            confirmed_root_cause=None,
            observation=row.get(
                "first_difference", row.get("failure_summary") or row.get("detail", "")
            ),
            evidence=row.get("evidence", []),
            affected_obligations=_affected_obligations(row, obligations, report),
            receipts=receipts,
            recorded_commands=recorded,
            receipt_records=receipt_records,
            reproduce_command=command,
            reproduce_environment=replay_env,
            reproduce_cwd=str(Path(__file__).resolve().parents[2]),
            source_locations=row.get("source_locations", []),
            related_issues=row.get("related_issues", []),
            acceptance_criteria=[
                f"Reproduce and pass {row['id']} ({check}) against the same independent reference and declared configuration.",
                "Retain a focused regression plus its controlled mutation; run neighboring contracts without changing tolerances, goldens, budgets or unsupported guards.",
                "Confirm the first divergent artifact before proposing a product fix; similar signatures are hypotheses only.",
            ],
            scope="Investigate this named contract and its direct prerequisites; do not modify unrelated capabilities.",
        )
        tasks.append(task)
    return tasks


def markdown(report: dict) -> str:
    counts = Counter(r["status"] for r in report["results"])
    claims = [c for c in report["capabilities"] if c["kind"] == "semantic-claim"]

    def safe(value):
        return str(value).replace("|", "&#124;").replace("\n", " ").replace("<", "&lt;")

    lines = [
        "# BNG3 conformance evidence",
        "",
        f"Source: `{report['source']['revision']}`; dirty: `{report['source']['dirty']}`.",
        "",
        "Reporting only. Test outcomes, implementation support, legacy agreement, mathematical contracts and scientific qualification are separate.",
        "",
        "| Outcome | Cases |",
        "| --- | ---: |",
    ]
    lines += [f"| {status} | {counts[status]} |" for status in STATUSES]
    lines += [
        "",
        f"Discovered {len(report['capabilities'])} implementation/semantic entries and {len(report['corpus'])} model artifacts. Discovery is not exhaustive semantic qualification.",
        "",
        "## Capability coverage",
        "",
        "| Capability | Support | Coverage | Test outcomes | Issues |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {c['id']} | {c['support']} | {c['coverage']} | {safe(c['result_counts'])} | {', '.join('#' + str(i) for i in c['issues'])} |"
        for c in claims
    ]
    lines += [
        "",
        "## Issue evidence coverage",
        "",
        "Closed issues and passing tests do not establish complete acceptance. "
        "PARTIAL means some mapped leaf evidence was executed. "
        f"Inventory scope: `{report.get('issue_inventory', {}).get('scope', 'mapped-only')}`.",
        "",
        "| Issue | Title | Recorded state | Coverage | Mapped claims | Unexecuted claims | Outcomes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| #{row['number']} | {safe(row.get('title') or '')} | {safe(row.get('state') or 'unknown')} | "
        f"{row['coverage']} | {len(row['capabilities'])} | {len(row['unexecuted_capabilities'])} | {safe(row['result_counts'])} |"
        for row in report.get("issue_coverage", [])
    ]
    lines += [
        "",
        "## Compatibility matrix",
        "",
        "| Case / component | Reference / question | First observed stage | Outcome |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| {safe(r['id'])} | {safe(r.get('reference', r.get('question', 'functional-contract')))} | {r['stage']} | {r['status']} |"
        for r in report["results"]
        if r["stage"] != "test"
    ]
    lines += [
        "",
        "## Investigation queue",
        "",
        "Signatures suggest similar symptoms; they do not establish shared causes.",
        "",
    ]
    for task in report.get("investigation_tasks", [])[:50]:
        lines += [
            f"- **{safe(task['case_id'])} / {task['status']}**: {safe(task['observation'])[:600]}. Packet `{task['id']}` in `investigation-tasks.json`; inspect {', '.join('`'+p+'`' for p in task['source_locations']) or 'recorded source/test location'}. Pass this exact check against its pinned reference; preserve neighboring checks."
        ]
    for group in report["failure_clusters"][:25]:
        lines += [
            f"- **{group['status']} / {group['first_observed_stage']}**, {len(group['cases'])} cases: {safe(group['signature'])[:400]}. {group['next_action']}."
        ]
    lines += [
        "",
        "## Regression history",
        "",
        safe(report["history"]),
        "",
        "## Performance",
        "",
        "Wall times in command receipts are diagnostic timings, not controlled benchmark results. Separate benchmark lanes and their qualification limits:",
        "",
    ]
    measurements = [r for r in report["results"] if r["stage"] == "performance"]
    if measurements:
        lines += [
            "| Model | Outcome | Parse median ms | Generation median ms |",
            "| --- | --- | ---: | ---: |",
        ]
        lines += [
            f"| {safe(r['id'])} | {r['status']} | {r['measurements'].get('parse_ms')} | {r['measurements'].get('generate_ms')} |"
            for r in measurements
        ]
        lines += [
            "",
            "These measurements cover fresh parse/generation repetitions. Independent speed comparisons, memory, scaling and other phases remain unqualified.",
            "",
        ]
    lines += [
        f"- {name}: `{path}` — existing separate lane; consult its evidence."
        for name, path in report["existing_lanes"].items()
    ]
    lines += [
        "",
        "Reproduction commands, model and artifact hashes, individual test outcomes, source locations, reference identities, coverage gaps and full failure details are in `report.json` and the adjacent evidence directories.",
        "",
    ]
    return "\n".join(lines)
