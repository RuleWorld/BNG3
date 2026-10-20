"""The corpus selection, its justification and its reconciliation (#181).

Issue #181 asks for the 106 selected models and the separate 71-model
workflow to be reconciled with the accepted capability inventory, and for the
justified NF, format and stress selections to be expanded and the currently
empty tiers to be populated with budgets and owners.

This module checks the *recorded* selection, which is the part that can be
executed without a maintainer decision:

* the selected models, the retained 71-model workflow and the accepted
  selections agree with each other.  The accepted set is empty by record -
  no tier membership has been approved - and the reconciliation explains the
  difference between the frozen 100-model workflow and the current 106
  models instead of leaving it implicit;
* every selection is justified with a recorded reason, and the reason is
  re-derived from the model file, so a stale or hand-written reason fails;
* an empty selection is reported rather than hidden: every tier records its
  justification, its owner and its budget, and an empty tier records why it
  is empty.

Populating the format and stress tiers with models stays a maintainer
decision: the RuleHub selectors and their budgets are not approved, so the
empty tiers are reported with the recorded reason and the recorded owner
instead of being filled with an unapproved selection.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import corpus

ISSUES = (181,)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "provenance" / "corpus" / "selection.json"
PARITY_REPORT = ROOT / "tests" / "validation" / "evidence" / "parity-report.json"

TIERS = ("s", "p", "nf", "expr", "x", "b")

# The harness accessor of every tier: the manifest and the harness have to
# select the same models.
_TIER_ACCESSORS = {
    "s": corpus.tier_s,
    "p": corpus.tier_p,
    "nf": corpus.tier_nf,
    "expr": corpus.tier_expr,
    "x": corpus.tier_x,
    "b": corpus.tier_b,
}

# The named checks of this operation.
CHECKS = (
    "selection-agreement",
    "tier-justification",
    "empty-tier-reporting",
)

# The two obligations of issue #181 that a named executable check closes.
OBLIGATION_CHECKS = (
    "reconcile-106-selected-models-and-the-separate-71-model-workflow",
    "expand-justified-nf-format-and-stress-selections-populate-curren",
)


def manifest() -> dict:
    """The committed corpus selection manifest."""
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def check_ids():
    """Stable expected check identities for the corpus-selection operation."""
    ids = [f"corpus-selection:{name}" for name in CHECKS]
    ids.extend(f"qualification:issue:181:{name}" for name in OBLIGATION_CHECKS)
    return ids


def _row(check, status, detail, **evidence):
    row = dict(
        check=check,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
        question="corpus-selection-versus-recorded-reconciliation",
        **evidence,
    )
    if status in {"PASS", "FAIL"}:
        row.setdefault("evidence_kind", "supported-execution")
        row.setdefault("supported_execution", True)
    else:
        row.setdefault("evidence_kind", "diagnostic-only")
        row.setdefault("supported_execution", False)
    return row


def _retained_workflow() -> dict:
    """The retained 71-model Tier-P workflow, as recorded in the evidence."""
    report = json.loads(PARITY_REPORT.read_text(encoding="utf-8"))
    followup = report["matched_network_only_followup"]
    run = followup["required_post_fix_full_run"]
    source = report["source"]["selection_reconciliation"]
    return {
        "tested_head": run["tested_head"],
        "selection_manifest_sha256": run["selection_manifest_sha256"],
        "selected_model_count": source["tested_frozen_tier_p_count"],
        "result": run["result"],
        "failure_categories": run["failure_categories"],
        "unselected_on_disk_models": source["unselected_on_disk_models"],
    }


def _failure_models(workflow) -> list[str]:
    models = []
    for category in workflow["failure_categories"].values():
        models.extend(category["models"])
    return sorted(set(models))


def run(directory=None):
    """Assert the recorded corpus selection against its justification."""
    return assess(manifest(), _retained_workflow())


def assess(document, workflow):
    """Assess the recorded selection against the retained workflow.

    The document and the workflow are passed in, so a test can mutate one
    and prove that the check refuses it.
    """
    records = {record["id"]: record for record in document["records"]}
    tiers = document["tiers"]
    reconciliation = document["reconciliation"]
    accepted = document["accepted_selections"]
    results = []

    # The selected models, the retained workflow and the accepted selections
    # have to agree with each other.
    selected = sorted(tiers["p"])
    added = sorted(entry["id"] for entry in reconciliation["added_models"])
    unselected = sorted(workflow["unselected_on_disk_models"])
    failures = _failure_models(workflow)
    problems = []
    if added != unselected:
        problems.append(
            "the recorded additions differ from the additions of the retained evidence"
        )
    if len(selected) != workflow["selected_model_count"] + len(added):
        problems.append(
            "the selected count is not the tested count plus the recorded additions"
        )
    for model_id in added:
        if model_id not in selected:
            problems.append(f"the added model {model_id!r} is not selected")
    for model_id in failures:
        if model_id not in selected:
            problems.append(f"the failed model {model_id!r} is not selected")
    if accepted.get("approved_tiers") or accepted.get("approved_models"):
        problems.append(
            "the manifest records an approved selection, which no maintainer "
            "decision supports"
        )
    if document.get("selection_status") != "pending-maintainer-approval":
        problems.append("the selection status does not record the pending approval")
    if reconciliation.get("tested_head") != workflow["tested_head"]:
        problems.append("the recorded workflow head differs from the retained evidence")
    if (
        reconciliation.get("selection_manifest_sha256")
        != workflow["selection_manifest_sha256"]
    ):
        problems.append(
            "the recorded selection digest differs from the retained evidence"
        )
    results.append(
        dict(
            _row(
                "selection-agreement",
                "PASS" if not problems else "FAIL",
                (
                    "the selected models, the retained 71-model workflow and the "
                    "accepted selections agree with each other"
                ),
                first_difference=None if not problems else dict(problems=problems),
                selected_models=len(selected),
                workflow_selected_models=workflow["selected_model_count"],
                added_models=added,
                failed_models=len(failures),
                workflow_result=workflow["result"],
                workflow_tested_head=workflow["tested_head"],
                workflow_selection_manifest_sha256=workflow[
                    "selection_manifest_sha256"
                ],
                accepted_selections=accepted,
                problems=problems,
            ),
            id="corpus-selection:selection-agreement",
            check="selection-agreement",
        )
    )

    # Every selection is justified with a recorded reason, and the reason is
    # re-derived from the model file.
    justifications = document.get("tier_justifications", {})
    missing_tier = [
        tier
        for tier in TIERS
        if not str(justifications.get(tier, {}).get("question") or "").strip()
        or not str(justifications.get(tier, {}).get("owner") or "").strip()
        or not str(justifications.get(tier, {}).get("capability") or "").strip()
        or not justifications.get(tier, {}).get("budget")
    ]
    stale_reasons = []
    missing_reasons = []
    reasons = {}
    for model_id, record in records.items():
        selection = record.get("selection", {})
        reason = str(selection.get("reason") or "").strip()
        if not reason:
            missing_reasons.append(model_id)
            continue
        reasons.setdefault(reason, []).append(model_id)
        path = ROOT / record["path"]
        if not path.is_file():
            stale_reasons.append(f"{model_id}: the model file is missing")
            continue
        tier = record["tiers"][0]
        expected = corpus.selection_reason(
            path.read_text(encoding="utf-8", errors="replace"), tier, record["path"]
        )
        if reason != expected:
            stale_reasons.append(
                f"{model_id}: the recorded reason is not the derived one"
            )
    duplicated = sorted(reason for reason, models in reasons.items() if len(models) > 1)
    problems = []
    if missing_tier:
        problems.append("a tier has no recorded justification")
    if missing_reasons:
        problems.append("a selected model has no recorded reason")
    if stale_reasons:
        problems.append("a recorded reason does not match the model file")
    if duplicated:
        problems.append("two selected models share one recorded reason")
    results.append(
        dict(
            _row(
                "tier-justification",
                "PASS" if not problems else "FAIL",
                (
                    "every tier records its justification, its owner and its "
                    "budget, and every selected model records the reason why it "
                    "is selected"
                ),
                first_difference=(
                    None
                    if not problems
                    else dict(
                        problems=problems,
                        missing_tier_justification=missing_tier,
                        missing_reasons=missing_reasons,
                        stale_reasons=stale_reasons,
                        duplicated_reasons=duplicated,
                    )
                ),
                missing_tier_justification=missing_tier,
                missing_reasons=missing_reasons,
                stale_reasons=stale_reasons,
                duplicated_reasons=duplicated,
                justified_models=len(records),
            ),
            id="corpus-selection:tier-justification",
            check="tier-justification",
        )
    )

    # An empty selection is reported rather than hidden.
    empty = sorted(tier for tier in TIERS if not tiers[tier])
    problems = []
    for tier in TIERS:
        entry = justifications.get(tier, {})
        if not tiers[tier]:
            if not str(entry.get("empty_reason") or "").strip():
                problems.append(f"tier {tier} is empty without a recorded reason")
        elif entry.get("empty_reason"):
            problems.append(f"tier {tier} is populated but records an empty reason")
        accessor = _TIER_ACCESSORS.get(tier)
        if accessor is not None and sorted(accessor()) != sorted(tiers[tier]):
            problems.append(f"tier {tier} differs between the manifest and the harness")
    results.append(
        dict(
            _row(
                "empty-tier-reporting",
                "PASS" if not problems else "FAIL",
                (
                    "every empty tier is reported with the reason why it is empty, "
                    "its owner and its budget"
                ),
                first_difference=None if not problems else dict(problems=problems),
                empty_tiers=empty,
                problems=problems,
                tier_report=[
                    dict(
                        tier=tier,
                        models=len(tiers[tier]),
                        owner=justifications.get(tier, {}).get("owner"),
                        budget=justifications.get(tier, {}).get("budget"),
                        empty_reason=justifications.get(tier, {}).get("empty_reason"),
                    )
                    for tier in TIERS
                ],
            ),
            id="corpus-selection:empty-tier-reporting",
            check="empty-tier-reporting",
        )
    )

    failures = [row["id"] for row in results if row["status"] == "FAIL"]
    evidence = dict(
        selected_models=len(selected),
        empty_tiers=empty,
        tier_justifications=len(justifications),
        accepted_selection_status=accepted.get("status"),
    )
    reconcile = dict(
        _row(
            OBLIGATION_CHECKS[0],
            "FAIL" if failures else "PASS",
            (
                "the selected models, the separate 71-model workflow and the "
                "accepted selections are reconciled with each other"
            ),
            **evidence,
        ),
        id=f"qualification:issue:181:{OBLIGATION_CHECKS[0]}",
        check=OBLIGATION_CHECKS[0],
    )
    expand = dict(
        _row(
            OBLIGATION_CHECKS[1],
            "FAIL" if failures else "PASS",
            (
                "the NF, format and stress selections are justified, and the "
                "empty tiers carry their budget, their owner and the reason "
                "they are empty"
            ),
            **evidence,
        ),
        id=f"qualification:issue:181:{OBLIGATION_CHECKS[1]}",
        check=OBLIGATION_CHECKS[1],
    )
    if failures:
        for row in (reconcile, expand):
            row["status"] = "FAIL"
            row["detail"] = "the corpus selection is not reconciled: " + ", ".join(
                sorted(failures)
            )
            row["first_difference"] = dict(failed_checks=sorted(failures))
    results.extend([reconcile, expand])
    return results


def run_worker(directory):
    """Execute the operation in the integrated worker and return its rows."""
    return run(Path(directory) if directory else None)
