"""The curated BioModels hold and the retention of its results (#162).

Issue #162 keeps the full curated BioModels run on hold until the user
explicitly resumes it, and asks that the flat, atomized and cross-engine
results be retained afterwards with separate pass, unsupported, failed,
timed-out and invalid-source categories.

This module keeps the hold in effect and checks the part that can be
executed now:

``stop-in-effect``
    The recorded hold is still in force.  The check is a *diagnostic*: it
    performs no corpus run, contacts no BioModels endpoint and claims no
    category count, so a reader cannot mistake the hold for a result.

``corpus-pin``
    The pinned corpus plan is retained: the manifest keeps its query, its
    snapshot date and its expected record counts, and the recorded plan
    names that same manifest.

``result-retention``
    The retention machinery that will keep the results keeps the five
    categories separate and binds them to the corpus and to the hashes they
    came from.  The check exercises that machinery on a generated report
    with one record per category, so the contract is proved before the
    corpus is resumed and not only afterwards.

An invalid source document is a source defect, not an unsupported feature
and not a parity failure.  The retention machinery keeps it in its own
category so a retained result says which of the five it is.
"""

from __future__ import annotations

import json
from pathlib import Path

ISSUES = (162,)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "provenance" / "published-biomodels.json"
RELEASE_AUDIT = ROOT / "docs" / "release-audit-2026-10-19.json"

# The named checks of this operation.
CHECKS = ("stop-in-effect", "corpus-pin", "result-retention")

# The obligation of issue #162 that a named executable check closes.
OBLIGATION_CHECK = "after-resumption-retain-current-flat-atomized-and-cross-engine-r"

# The five result categories the retained results have to keep separate.
CATEGORIES = ("passed", "unsupported", "failed", "timeout", "invalid_source")

# The campaign status of every category.
CAMPAIGN_STATUS = {
    "passed": "PASS",
    "unsupported": "UNSUPPORTED",
    "failed": "FAIL",
    "timeout": "TIMEOUT",
    "invalid_source": "INVALID_INPUT",
}


def check_ids():
    """Stable expected check identities for the BioModels hold operation."""
    ids = [f"biomodels-hold:{name}" for name in CHECKS]
    ids.append(f"qualification:issue:162:{OBLIGATION_CHECK}")
    return ids


def _row(check, status, detail, **evidence):
    row = dict(
        check=check,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
        question="curated-biomodels-hold-and-result-retention",
        **evidence,
    )
    if status in {"PASS", "FAIL"}:
        row.setdefault("evidence_kind", "supported-execution")
        row.setdefault("supported_execution", True)
    else:
        row.setdefault("evidence_kind", "diagnostic-only")
        row.setdefault("supported_execution", False)
    return row


def _audit_row() -> dict:
    """The recorded plan of the curated BioModels work."""
    document = json.loads(RELEASE_AUDIT.read_text(encoding="utf-8"))
    for row in document["issues"]:
        if row.get("number") == 162:
            return row
    raise ValueError("the release audit does not record issue #162")


def _generated_report() -> dict:
    """A generated BioModels report with one record per result category."""
    corpus_manifest = "provenance/published-biomodels.json"
    corpus_digest = (
        "sha256:" + __import__("hashlib").sha256(MANIFEST.read_bytes()).hexdigest()
    )
    records = []
    for index, category in enumerate(CATEGORIES):
        model_id = f"BIOMODEL{index}"
        records.append(
            {
                "id": model_id,
                "format": "SBML",
                "status": category,
                "source_artifact": {
                    "format": "SBML",
                    "filename": f"{model_id}.xml",
                    "sha256": f"{index + 1:064x}",
                },
                "modes": [
                    {
                        "mode": "flat",
                        "status": category,
                        "core_passed": category == "passed",
                    },
                    {
                        "mode": "atomized",
                        "status": category,
                        "core_passed": category == "passed",
                    },
                ],
            }
        )
    return {
        "schema_version": 5,
        "corpus": {
            "manifest": corpus_manifest,
            "manifest_sha256": corpus_digest,
            "snapshot_date": "2026-09-15",
            "curation_query": "curationstatus:Manually curated",
            "expected_records": 1096,
            "expected_sbml_records": 1075,
            "expected_non_sbml_records": 21,
        },
        "records": records,
    }


def run(directory=None):
    """Keep the recorded hold in effect and check the result retention."""
    return assess(_audit_row(), json.loads(MANIFEST.read_text(encoding="utf-8")))


def assess(audit, manifest):
    """Assess the recorded hold, the pinned corpus and the retention.

    The recorded plan and the corpus manifest are passed in, so a test can
    mutate one and prove that the check refuses it.
    """
    from scripts.ci.sbml_campaign_inventory import biomodels_inventory
    from tests.validation import external_lanes

    results = []

    # The recorded hold stays in effect.  This row is a diagnostic: it claims
    # no result and no category count.
    problems = []
    if audit.get("classification") != "proposed deferral":
        problems.append("the recorded plan is not a deferral")
    if "stop" not in str(audit.get("assessment", "")).lower():
        problems.append("the recorded assessment does not preserve the stop")
    if audit.get("closure_eligible") is not False:
        problems.append("the recorded plan claims the issue is closable")
    remaining = set(audit.get("remaining_obligations") or [])
    expected_obligations = {
        "issue:162:keep-the-existing-full-biomodels-stop-in-effect-until-the-user-e",
        "issue:162:after-resumption-retain-current-flat-atomized-and-cross-engine-r",
    }
    if not expected_obligations <= remaining:
        problems.append("the recorded plan does not retain the open obligations")
    results.append(
        dict(
            _row(
                "stop-in-effect",
                "PASS" if not problems else "FAIL",
                (
                    "the recorded full BioModels stop is in effect; this check "
                    "runs no corpus and claims no category count"
                ),
                first_difference=None if not problems else dict(problems=problems),
                problems=problems,
                corpus_executed=False,
                classification=audit.get("classification"),
                assessment=audit.get("assessment"),
                remaining_obligations=sorted(remaining),
                # The hold is a diagnostic: it is never a supported execution.
                evidence_kind="diagnostic-only",
                supported_execution=False,
            ),
            id="biomodels-hold:stop-in-effect",
            check="stop-in-effect",
        )
    )

    # The pinned corpus plan is retained and named by the recorded plan.
    problems = []
    for key in (
        "curation_query",
        "sbml_query",
        "snapshot_date",
        "expected_total_records",
        "expected_sbml_records",
        "expected_non_sbml_records",
    ):
        if not manifest.get(key):
            problems.append(f"the corpus manifest does not record {key}")
    if audit.get("source_path") != MANIFEST.relative_to(ROOT).as_posix():
        problems.append("the recorded plan does not name the pinned corpus manifest")
    results.append(
        dict(
            _row(
                "corpus-pin",
                "PASS" if not problems else "FAIL",
                (
                    "the pinned corpus plan is retained and the recorded plan "
                    "names it"
                ),
                first_difference=None if not problems else dict(problems=problems),
                problems=problems,
                corpus_manifest=MANIFEST.relative_to(ROOT).as_posix(),
                corpus_sha256="sha256:"
                + __import__("hashlib").sha256(MANIFEST.read_bytes()).hexdigest(),
                snapshot_date=manifest.get("snapshot_date"),
                expected_total_records=manifest.get("expected_total_records"),
            ),
            id="biomodels-hold:corpus-pin",
            check="corpus-pin",
        )
    )

    # The retention machinery keeps the five categories separate and binds
    # the results to the corpus and to the hashes they came from.
    report = _generated_report()
    problems = []
    inventory = biomodels_inventory(report)
    counts = inventory.get("category_counts") or {}
    for category in CATEGORIES:
        if counts.get(category) != 1:
            problems.append(f"the {category} category is not retained separately")
    if len(inventory.get("cases") or []) != len(CATEGORIES):
        problems.append("a retained case is missing")
    for case in inventory.get("cases") or []:
        if not case.get("source_sha256"):
            problems.append(f"{case.get('id')} does not retain its source hash")
    corpus = inventory.get("corpus") or {}
    if not corpus.get("manifest") or not corpus.get("manifest_sha256"):
        problems.append("the retained results are not bound to the corpus")
    if corpus.get("expected_records") != 1096:
        problems.append("the retained results do not record the corpus counts")
    lane_rows = external_lanes.biomodel_results(report)
    observed = {row["status"] for row in lane_rows}
    for category in CATEGORIES:
        if CAMPAIGN_STATUS[category] not in observed:
            problems.append(f"the {category} category is merged with another one")
    results.append(
        dict(
            _row(
                "result-retention",
                "PASS" if not problems else "FAIL",
                (
                    "the retained results keep the pass, unsupported, failed, "
                    "timed-out and invalid-source categories separate and stay "
                    "bound to the corpus and to their source hashes"
                ),
                first_difference=None if not problems else dict(problems=problems),
                problems=problems,
                category_counts=counts,
                campaign_statuses=sorted(observed),
                corpus=corpus,
            ),
            id="biomodels-hold:result-retention",
            check="result-retention",
        )
    )

    failures = [row["id"] for row in results if row["status"] == "FAIL"]
    obligation = dict(
        _row(
            OBLIGATION_CHECK,
            "FAIL" if failures else "PASS",
            (
                "the retention machinery keeps the flat, atomized and "
                "cross-engine results in five separate categories and binds "
                "them to the corpus and to the hashes they came from"
            ),
            categories=list(CATEGORIES),
            campaign_status={
                category: CAMPAIGN_STATUS[category] for category in CATEGORIES
            },
            corpus_executed=False,
            # The corpus is on hold, so the qualification of this family is a
            # diagnostic: it never claims a supported corpus execution.
            evidence_kind="diagnostic-only",
            supported_execution=False,
        ),
        id=f"qualification:issue:162:{OBLIGATION_CHECK}",
        check=OBLIGATION_CHECK,
    )
    if failures:
        obligation["detail"] = (
            "the retained results do not keep the required categories separate: "
            + ", ".join(sorted(failures))
        )
        obligation["first_difference"] = dict(failed_checks=sorted(failures))
    results.append(obligation)
    return results


def run_worker(directory):
    """Execute the operation in the integrated worker and return its rows."""
    return run(Path(directory) if directory else None)
