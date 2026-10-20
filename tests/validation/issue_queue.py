"""Join exact-revision observations to issues without inferring issue completion.

This is read-only evidence triage. Approval decisions, unresolved upstream drift,
and unexecuted claims stay visible; the tool never closes issues or approves locks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from . import campaign, inventory

ROOT = Path(__file__).resolve().parents[2]
FAILURES = {"FAIL", "HARNESS_ERROR", "TIMEOUT", "INVALID_INPUT"}


def acceptance_criteria(issue):
    """Retain live issue criteria separately from broad issue-linked evidence.

    A maintainer checkbox and a passing related contract are both useful,
    but neither establishes execution of the entire acceptance sentence.
    """
    criteria, active = [], False
    for raw_line in (issue.get("body") or "").splitlines():
        line = raw_line.strip()
        if line.strip("#* ").lower() == "acceptance criteria":
            active = True
            continue
        if not active:
            continue
        if line.startswith(("#", "**")):
            break
        match = re.match(r"[-*] \[([ xX])\] (.+)", line)
        if match:
            criteria.append(
                dict(
                    id=f"issue:{issue['number']}:acceptance:{len(criteria) + 1}",
                    text=match.group(2),
                    maintainer_checked=match.group(1).lower() == "x",
                    evidence_status="UNVERIFIED",
                )
            )
    return criteria


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
                    "supported_execution",
                    "evidence_kind",
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
        evidence, diagnostics = {}, {}
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
                if row["status"] == "PASS" and (
                    row.get("supported_execution") is False
                    or row.get("evidence_kind") == "diagnostic-only"
                ):
                    diagnostics[key] = row
                else:
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
                diagnostic_control_ids=sorted(diagnostics),
                diagnostic_control_outcomes=dict(
                    sorted(
                        Counter(row["status"] for row in diagnostics.values()).items()
                    )
                ),
                acceptance_criteria=acceptance_criteria(dict(issue, number=number)),
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


def obligation_inventory(issues, catalog=None):
    """Bind reviewed scope to live text; additions and changed scope stay visible."""
    catalog = catalog or json.loads(
        (ROOT / "provenance/issue-obligations.json").read_text()
    )
    known = {row["number"]: row for row in catalog["issues"]}
    obligations = []
    for issue in issues:
        number = issue["number"]
        body = issue.get("body") or ""
        digest = hashlib.sha256(body.encode()).hexdigest()
        entry = known.get(number, {})
        current = entry.get("body_sha256") == digest
        criteria = acceptance_criteria(issue)
        texts = [row["text"] for row in criteria] or [
            body or issue.get("title", "Scope absent")
        ]
        reviewed = entry.get("obligations", [])
        for item in reviewed:
            row = dict(
                item, issue=number, scope_status="CURRENT" if current else "STALE_SCOPE"
            )
            if not current:
                row["unmapped_scope"] = list(row.get("unmapped_scope", [])) + [
                    "Live issue body differs from reviewed scope; reconcile before demonstrating acceptance."
                ]
            obligations.append(row)
        for text in texts:
            if current and any(row.get("criterion") == text for row in reviewed):
                continue
            identity = hashlib.sha256(text.encode()).hexdigest()[:16]
            obligations.append(
                dict(
                    id=f"issue:{number}:unmapped:{identity}",
                    issue=number,
                    criterion=text,
                    scope=text,
                    scope_status="UNMAPPED",
                    dependencies=[],
                    boundaries=[],
                    required_checks=[],
                    test_references=[],
                    completion_condition="Maintainer-reviewed mapping and named evidence required.",
                    decisions=[
                        "Map remaining live scope without narrowing acceptance."
                    ],
                    unmapped_scope=[text],
                )
            )
    ids = [row["id"] for row in obligations]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate obligation identity")
    return obligations


def _identity_value(report, path):
    value = report
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _report_status(report, revision):
    if not isinstance(report, dict):
        raise ValueError("evidence report must be an object")
    source = report.get("source")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("revision"), str)
        or not re.fullmatch("[0-9a-f]{40}", source["revision"])
        or source.get("dirty") is not False
    ):
        return "UNVERIFIABLE"
    return "STALE" if source["revision"] != revision else None


def assess_obligations(obligations, reports, revision):
    """Audit exact leaf checks; missing evidence is never inferred from issue links."""
    observations, audit, conflicts = {}, [], set()
    for index, report in enumerate(reports):
        source = report.get("source", {})
        reason = _report_status(report, revision)
        if reason:
            audit.append(dict(report=index, status=reason, source=source))
            continue
        seen = set()
        for row in report.get("results", []):
            key = row.get("id")
            if not key or row.get("status") not in campaign.STATUSES:
                raise ValueError("invalid result identity/status")
            if key in seen:
                conflicts.add(key)
                audit.append(
                    dict(
                        report=index,
                        id=key,
                        status="CONFLICT",
                        reason="duplicate leaf identity",
                    )
                )
            seen.add(key)
            if row.get("aggregate"):
                continue
            evidence = dict(
                observation=row,
                candidate_identity=source,
                oracle_identities=report.get("references", {}),
            )
            if key in observations and observations[key][0] != evidence:
                conflicts.add(key)
                audit.append(
                    dict(
                        report=index,
                        id=key,
                        status="CONFLICT",
                        reason="different exact-revision observations or identities",
                    )
                )
            observations[key] = (evidence, report)
    assessed = []
    for obligation in obligations:
        for name in ("id", "criterion", "scope", "completion_condition"):
            if not isinstance(obligation.get(name), str) or not obligation[name]:
                raise ValueError("missing obligation field: " + name)
        for name in (
            "dependencies",
            "boundaries",
            "required_checks",
            "test_references",
            "decisions",
            "unmapped_scope",
        ):
            if not isinstance(obligation.get(name), list):
                raise ValueError("invalid obligation list: " + name)
        required_checks = obligation["required_checks"]
        if len({c["id"] for c in required_checks}) != len(required_checks):
            raise ValueError("duplicate required check identity")
        for check in required_checks:
            if check.get("evidence_kind") not in {
                "supported-execution",
                "diagnostic-only",
                "disposition",
                "native-bngir-semantic-control",
            } or not check.get("expectation"):
                raise ValueError(
                    "required check needs evidence kind and independent expectation"
                )
    ids = [o["id"] for o in obligations]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate obligation identity")
    for obligation in obligations:
        manual_requirements = []
        for check in obligation["required_checks"]:
            if check["evidence_kind"] == "disposition":
                manual_requirements.append(
                    dict(
                        id=f"{obligation['id']}:manual:{len(manual_requirements) + 1}",
                        kind="disposition",
                        criterion=obligation["criterion"],
                        text=check["expectation"],
                    )
                )
        for decision in obligation["decisions"]:
            manual_requirements.append(
                dict(
                    id=f"{obligation['id']}:manual:{len(manual_requirements) + 1}",
                    kind="human-decision",
                    criterion=obligation["criterion"],
                    text=decision,
                )
            )
        for scope in obligation["unmapped_scope"]:
            manual_requirements.append(
                dict(
                    id=f"{obligation['id']}:manual:{len(manual_requirements) + 1}",
                    kind="scope-reconciliation",
                    criterion=obligation["criterion"],
                    text=scope,
                )
            )
        if (
            obligation.get("scope_status") == "STALE_SCOPE"
            and not obligation["unmapped_scope"]
        ):
            manual_requirements.append(
                dict(
                    id=f"{obligation['id']}:manual:{len(manual_requirements) + 1}",
                    kind="scope-reconciliation",
                    criterion=obligation["criterion"],
                    text="Reconcile the live issue text with this reviewed scope.",
                )
            )
        checks = []
        for required in obligation["required_checks"]:
            if required["evidence_kind"] == "disposition":
                continue
            key = required["id"]
            record = dict(required, status="NOT_TESTED", missing_evidence=[])
            if key in conflicts:
                record["status"] = "CONFLICT"
            elif key in observations:
                evidence, report = observations[key]
                row = evidence["observation"]
                record.update(evidence)
                record["status"] = row["status"]
                if row["status"] == "PASS":
                    kind = required["evidence_kind"]
                    if kind in {
                        "supported-execution",
                        "native-bngir-semantic-control",
                    } and (
                        row.get("supported_execution") is not True
                        or row.get("evidence_kind") != kind
                    ):
                        record["missing_evidence"].append(
                            "explicit supported-execution evidence"
                        )
                    elif (
                        kind != "supported-execution"
                        and row.get("evidence_kind") != kind
                    ):
                        record["missing_evidence"].append("evidence_kind:" + kind)
                if row["status"] not in {"NOT_TESTED", "UNSUPPORTED", "INVALID_INPUT"}:
                    for path in required.get("identity_requirements", []):
                        if not _identity_value(report, path):
                            record["missing_evidence"].append(path)
                    if record["missing_evidence"]:
                        record["status"] = "EVIDENCE_GAP"
            else:
                record["missing_evidence"].append(key)
            checks.append(record)
        for check in checks:
            check["executed"] = (
                bool(check.get("observation")) and check["status"] != "NOT_TESTED"
            )
        statuses = {c["status"] for c in checks}
        if checks:
            technical_status = "DEMONSTRATED"
        else:
            technical_status = (
                "NOT_APPLICABLE" if manual_requirements else "EVIDENCE_GAP"
            )
        for candidate in (
            "NOT_TESTED",
            "EVIDENCE_GAP",
            "UNSUPPORTED",
            "INVALID_INPUT",
            "TIMEOUT",
            "FAIL",
            "HARNESS_ERROR",
            "CONFLICT",
        ):
            if candidate in statuses:
                technical_status = candidate
        if technical_status == "DEMONSTRATED" and statuses != {"PASS"}:
            technical_status = "EVIDENCE_GAP"
        status = "DECISION_REQUIRED" if manual_requirements else technical_status
        assessed.append(
            dict(
                obligation,
                status=status,
                technical_status=technical_status,
                decision_status=("REQUIRED" if manual_requirements else "NONE"),
                manual_requirements=manual_requirements,
                checks=checks,
                test_reference_status=(
                    "RELEVANT_TEST_EXISTS"
                    if obligation.get("test_references")
                    else "NO_TEST_REFERENCE"
                ),
                missing_evidence=[m for c in checks for m in c["missing_evidence"]],
                untested_routes=[
                    dict(
                        check=c["id"],
                        boundaries=obligation["boundaries"],
                        feature_combinations=obligation.get(
                            "feature_combinations",
                            [
                                "Only explicitly named check scope; broader combinations unspecified."
                            ],
                        ),
                    )
                    for c in checks
                    if not c["executed"]
                ],
            )
        )
    # Fixed-point dependency audit also blocks cycles; do not interpret a cycle as proof.
    demonstrated = set()
    while True:
        added = {
            o["id"]
            for o in assessed
            if o["status"] == "DEMONSTRATED"
            and o["decision_status"] != "REQUIRED"
            and set(o["dependencies"]) <= demonstrated
        } - demonstrated
        if not added:
            break
        demonstrated.update(added)
    for row in assessed:
        row["blocked_dependencies"] = sorted(set(row["dependencies"]) - demonstrated)
        if (
            row["status"] == "DEMONSTRATED"
            and row["decision_status"] != "REQUIRED"
            and row["id"] not in demonstrated
        ):
            row["status"] = "BLOCKED"
    return dict(obligations=assessed, evidence_audit=audit)


def select_campaign(obligations, *, findings=(), max_families=3, active_issues=None):
    """Choose plans from existing generators; this never authorizes execution."""
    if active_issues is not None:
        obligations = [o for o in obligations if o.get("issue") in active_issues]
        findings = [
            dict(
                row,
                related_issues=sorted(
                    set(row.get("related_issues", [])) & active_issues
                ),
            )
            for row in findings
            if set(row.get("related_issues", [])) & active_issues
        ]
    if type(max_families) is not int or not 0 <= max_families <= 10:
        raise ValueError("campaign family budget must be between zero and ten")
    from .integrated_cases import generated_cases
    from .integrated import expected_contract_ids
    from .bngir_adversarial import check_ids as adversarial_check_ids
    from .bngir_format_contracts import check_ids as format_check_ids
    from .bngir_reconstruction_contracts import check_ids as reconstruction_check_ids
    from .netrule_execution import check_ids as netrule_check_ids
    from .netrule_execution import cases as netrule_cases
    from .bngsim_boundary import check_ids as boundary_check_ids

    check_ids = [
        *adversarial_check_ids(),
        *format_check_ids(),
        *reconstruction_check_ids(),
    ]

    cases = generated_cases(full=False)
    families = []
    for family in ("decay", "reversible", "dimerization"):
        selected = [case for case in cases if case["family"] == family]
        families.append(
            dict(
                id="generated-" + family,
                case_ids=[c["id"] for c in selected],
                check_ids=expected_contract_ids(
                    selected,
                    include_boundaries=False,
                    include_graph_identity=False,
                    include_bngir_adversarial=False,
                    include_quantity_laws=False,
                    include_export_format_tier=False,
                    include_netrule_execution=False,
                    include_bngsim_boundary=False,
                ),
                runner="tests.validation.integrated",
                budget=dict(
                    cases=len(selected), stage_timeout_seconds=60, ensemble_runs=32
                ),
                limits="PR representatives only; no full corpus, lifecycle concurrency, or universal physical-unit qualification.",
            )
        )
    families.append(
        dict(
            id="native-bngir-adversarial",
            case_ids=[],
            check_ids=check_ids,
            runner="tests.validation.integrated",
            budget=dict(checks=len(check_ids), stage_timeout_seconds=60),
            limits="Bounded generated native reader shapes; no complete migration or arbitrary graph coverage.",
        )
    )
    families.append(
        dict(
            id="network-rule-execution",
            case_ids=[case["id"] for case in netrule_cases()],
            check_ids=netrule_check_ids(),
            runner="tests.validation.integrated",
            budget=dict(checks=len(netrule_check_ids()), stage_timeout_seconds=120),
            limits=(
                "Single-molecule rule shapes without bonds, compartments or "
                "delete-molecules; no legacy network-rule path is retired by "
                "this evidence and other rule shapes remain unqualified."
            ),
        )
    )
    from .integrated_marginals import source_law_check_ids
    from .integrated_cases import source_law_cases
    from .export_format_tier import check_ids as export_format_tier_check_ids

    families.append(
        dict(
            id="quantity-source-laws",
            case_ids=[case["id"] for case in source_law_cases()],
            check_ids=source_law_check_ids(),
            runner="tests.validation.integrated",
            budget=dict(
                cases=len(source_law_cases()),
                ensemble_runs=32,
                stage_timeout_seconds=900,
            ),
            limits="Finite prelowered physical-law and bare BNGL count controls; no unit-annotation ingestion or joint-law qualification.",
        )
    )
    families.append(
        dict(
            id="export-format-tier",
            case_ids=[],
            check_ids=export_format_tier_check_ids(),
            runner="tests.validation.integrated",
            budget=dict(
                checks=len(export_format_tier_check_ids()),
                stage_timeout_seconds=300,
            ),
            limits="Bounded generated export-format tier: BNGL/NET/SBML round trips with independent consumers and the eBNGL energy refusal boundary; no exhaustive format matrix and no structural/graph exporter qualification.",
        )
    )
    families.append(
        dict(
            id="bngsim-boundary",
            case_ids=[],
            check_ids=boundary_check_ids(),
            runner="tests.validation.integrated",
            budget=dict(checks=len(boundary_check_ids()), stage_timeout_seconds=300),
            limits="Generated finite-network models with an independent closed-form law; the BNGsim route itself needs a build with the adapter linked.",
        )
    )
    selected = []
    for family in families:
        available = set(family["check_ids"])
        targets = [
            o
            for o in obligations
            if o.get("status") != "DEMONSTRATED"
            and any(c["id"] in available for c in o["required_checks"])
        ]
        known = [
            r
            for r in findings
            if r.get("id") in available
            and not r.get("aggregate")
            and r.get("status") in {"FAIL", "HARNESS_ERROR", "TIMEOUT"}
        ]
        if not targets and not known:
            continue
        family.update(
            obligation_ids=sorted(o["id"] for o in targets),
            issues=sorted(
                {o.get("issue", int(o["id"].split(":")[1])) for o in targets}
                | {number for row in known for number in row.get("related_issues", [])}
            ),
            known_finding_ids=sorted({r["id"] for r in known}),
            reason="Existing family contains uncovered exact obligation checks or named failing observations; finding issue links are investigation hints only and establish no additional obligation coverage.",
            authorization="PLAN_ONLY",
            complete_corpus_coverage=False,
        )
        family["selection_arguments"] = (
            ["--bngir-adversarial-only"]
            if family["id"] == "native-bngir-adversarial"
            else (
                ["--quantity-laws-only"]
                if family["id"] == "quantity-source-laws"
                else (
                    ["--export-format-tier-only"]
                    if family["id"] == "export-format-tier"
                    else (
                        (
                            ["--netrule-execution-only"]
                            if family["id"] == "network-rule-execution"
                            else [
                                argument
                                for case_id in family["case_ids"]
                                for argument in ("--case", case_id)
                            ]
                        )["--bngsim-boundary-only"]
                        if family["id"] == "bngsim-boundary"
                        else [
                            argument
                            for case_id in family["case_ids"]
                            for argument in ("--case", case_id)
                        ]
                    )
                )
            )
        )
        family["confirmed_failures"] = sum(o.get("status") == "FAIL" for o in targets)
        selected.append(family)
    return sorted(
        selected,
        key=lambda f: (
            -f["confirmed_failures"],
            -len(f["known_finding_ids"]),
            -len(f["issues"]),
            -len(f["obligation_ids"]),
            f["id"],
        ),
    )[:max_families]


def acceptance_dashboard(queue, assessment, campaigns):
    for row in queue:
        obligations = [
            o for o in assessment["obligations"] if o.get("issue") == row["number"]
        ]
        row["obligations"] = obligations
        row["obligation_outcomes"] = dict(Counter(o["status"] for o in obligations))
        row["demonstrated_obligations"] = [
            o["id"]
            for o in obligations
            if o["status"] == "DEMONSTRATED" and o["decision_status"] != "REQUIRED"
        ]
        row["remaining_obligations"] = [
            o["id"]
            for o in obligations
            if o["status"] != "DEMONSTRATED" or o["decision_status"] == "REQUIRED"
        ]
        row["selected_families"] = [
            f["id"] for f in campaigns if row["number"] in f["issues"]
        ]
        row["confirmed_failures"] = [
            c["id"] for o in obligations for c in o["checks"] if c["status"] == "FAIL"
        ]
        row["unexecuted_checks"] = [
            c["id"] for o in obligations for c in o["checks"] if not c["executed"]
        ]
        row["unsupported_boundaries"] = [
            dict(check=c["id"], boundaries=o["boundaries"])
            for o in obligations
            for c in o["checks"]
            if c["status"] == "UNSUPPORTED"
        ]
        row["decisions_required"] = [
            dict(
                obligation=o["id"],
                decisions=o["decisions"],
                unmapped_scope=o["unmapped_scope"],
                manual_requirements=o["manual_requirements"],
            )
            for o in obligations
            if o["manual_requirements"]
        ]
        row["ranking_basis"] = dict(
            confirmed_failures=sum(
                check["status"] == "FAIL" for o in obligations for check in o["checks"]
            ),
            remaining=len(row["remaining_obligations"]),
            shared_issues=len(
                {
                    i
                    for f in campaigns
                    if row["number"] in f["issues"]
                    for i in f["issues"]
                }
            ),
        )
        row["ranking_explanation"] = (
            "Confirmed failing obligations first, then shared selected-family impact, then concrete remaining obligations; decisions and unmapped scope remain blocking."
        )
    ranked = sorted(
        (row for row in queue if row["state"] == "OPEN"),
        key=lambda r: (
            -r["ranking_basis"]["confirmed_failures"],
            -r["ranking_basis"]["shared_issues"],
            -r["ranking_basis"]["remaining"],
            r["number"],
        ),
    )
    for index, row in enumerate(ranked, 1):
        row["rank"] = index
    inactive = sorted(
        (row for row in queue if row["state"] != "OPEN"),
        key=lambda row: row["number"],
    )
    for row in inactive:
        row["rank"] = None
    return ranked + inactive


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
    parser.add_argument(
        "--obligations-json",
        type=Path,
        default=ROOT / "provenance/issue-obligations.json",
    )
    parser.add_argument("--max-families", type=int, default=3)
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
        catalog = json.loads(args.obligations_json.read_text())
        obligations = obligation_inventory(issues, catalog)
        assessment = assess_obligations(obligations, reports, args.revision)
        conflicts = {
            a["id"] for a in assessment["evidence_audit"] if a["status"] == "CONFLICT"
        }
        usable = [
            dict(
                r,
                results=[
                    row for row in r.get("results", []) if row["id"] not in conflicts
                ],
            )
            for r in reports
            if _report_status(r, args.revision) is None
        ]
        campaigns = select_campaign(
            assessment["obligations"],
            findings=[row for r in usable for row in r.get("results", [])],
            max_families=args.max_families,
            active_issues={
                issue["number"] for issue in issues if issue.get("state") == "OPEN"
            },
        )
        queue = acceptance_dashboard(
            build_queue(issues, usable, args.revision), assessment, campaigns
        )
        report = dict(
            schema_version=1,
            revision=args.revision,
            issue_snapshot_sha256=inventory.sha256(args.issues_json),
            issue_snapshot_scope="provided snapshot; collection completeness not inferred",
            evidence_reports=[
                dict(path=str(p), sha256=inventory.sha256(p)) for p in args.report
            ],
            queue=queue,
            acceptance=assessment,
            campaign_selection=campaigns,
            obligations_sha256=inventory.sha256(args.obligations_json),
            authorization="Existing campaign limits remain in force; selections are plans only.",
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
        for filename, value in (
            ("obligation-assessment.json", assessment),
            ("campaign-selection.json", campaigns),
        ):
            (args.output_dir / filename).write_text(json.dumps(value, indent=2) + "\n")
        from .ci_report import acceptance_markdown

        lines = acceptance_markdown(report).splitlines()
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
