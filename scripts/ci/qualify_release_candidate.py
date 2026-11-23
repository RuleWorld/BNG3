"""Check that required main-branch workflows passed for one exact commit."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

REQUIRED_WORKFLOWS = (
    "CI",
    "Cross-tool parity",
    "Lean semantic kernel",
    "CodeQL",
)


def _workflow_runs(payload: Any) -> list[dict[str, Any]]:
    """Normalize one API page or the list of pages emitted by `gh api --slurp`."""

    pages = payload if isinstance(payload, list) else [payload]
    runs: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(
            page.get("workflow_runs"), list
        ):
            raise ValueError("expected GitHub Actions workflow-runs response")
        runs.extend(run for run in page["workflow_runs"] if isinstance(run, dict))
    return runs


def qualify_workflow_runs(
    payload: Any,
    candidate_sha: str,
    required_workflows: tuple[str, ...] | list[str],
    *,
    event: str = "push",
) -> list[str]:
    """Return workflows without a successful run for the event on exact main SHA."""

    runs = _workflow_runs(payload)
    missing = []
    for workflow in required_workflows:
        passed = any(
            run.get("name") == workflow
            and run.get("head_sha") == candidate_sha
            and run.get("head_branch") == "main"
            and run.get("event") == event
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            for run in runs
        )
        if not passed:
            missing.append(workflow)
    return missing


SBML_WORKFLOW = "Official SBML conformance subset"
SBML_RECEIPTS = {
    159: {"release-ssts", "release-ssts-coverage", "release-obligation-159"},
    160: {
        "release-sbml-core-comp",
        "release-sbml-source-fidelity",
        "release-capability-coverage-160",
    },
}


def _read_artifact(directory: Path, name: str) -> tuple[dict, str]:
    paths = list(directory.rglob(name))
    if len(paths) != 1:
        raise ValueError(f"expected one {name}, found {len(paths)}")
    raw = paths[0].read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def verify_sbml_evidence(directory: Path, sha: str, biomodels_ids: set[str]) -> None:
    """Require the two full scientific lanes from the same workflow attempt."""
    ssts = directory / "ssts"
    suite, suite_hash = _read_artifact(ssts, "report.json")
    for key in ("source_provenance", "validation_harness_provenance"):
        source = suite[key]
        if (
            source["bng3_commit"] != sha
            or source["bng3_tracked_worktree_clean"] is not True
        ):
            raise ValueError(f"SSTS {key} does not match the candidate")
    records = [(row["category"], row["id"]) for row in suite["records"]]
    counts = Counter(category for category, _ in records)
    inventory = suite["full_suite_inventory"]
    if (
        suite["partial_run"] is not False
        or suite["case_selection"]["strategy"] != "full-inventory"
        or suite["stochastic_seed_base"] != 1000000
        or len(set(records)) != len(records)
        or len(records) != inventory["total"]
        or len(records) != suite["selected_cases"]
        or set(counts) != {"semantic", "stochastic"}
        or any(counts[category] != inventory[category] for category in counts)
    ):
        raise ValueError("SSTS evidence does not cover the full pinned inventory")
    for issue, checks in SBML_RECEIPTS.items():
        receipt, _ = _read_artifact(ssts, f"issue{issue}-release-receipt.json")
        supported = {
            row["id"]
            for row in receipt["results"]
            if row["id"] in checks
            and row["status"] == "PASS"
            and row["supported_execution"] is True
            and row["receipt"]["report_sha256"] == suite_hash
        }
        if (
            receipt["source"] != {"revision": sha, "dirty": False}
            or checks != supported
        ):
            raise ValueError(f"Issue {issue} receipt does not qualify this SSTS report")

    biomodels = directory / "biomodels"
    corpus, _ = _read_artifact(biomodels, "corpus-inventory.json")
    measurement = corpus["measurement"]
    if measurement["base_commit"] != sha:
        raise ValueError("BioModels inventory revision does not match the candidate")
    if corpus["corpus"]["expected_total_records"] != len(biomodels_ids):
        raise ValueError("BioModels inventory size does not match the pinned corpus")
    for mode in ("flat", "atomized"):
        report, report_hash = _read_artifact(biomodels, f"{mode}-report.json")
        completeness = report["completeness"]
        ids = [row["id"] for row in report["records"]]
        if (
            report_hash != measurement["reports"][mode]["sha256"]
            or report["mode"] != mode
            or report["supported_surface_passed"] is not True
            or report["simulation_comparison_is_required"] is not True
            or completeness["counts_match"] is not True
            or completeness["partial_run"] is not False
            or len(set(ids)) != len(ids)
            or set(ids) != biomodels_ids
            or len(ids) != completeness["expected_records"]
        ):
            raise ValueError(f"BioModels {mode} evidence is incomplete or not passing")


def qualify_sbml_runs(
    payload: Any, evidence_dir: Path, sha: str, biomodels_ids: set[str]
) -> None:
    for run in _workflow_runs(payload):
        if qualify_workflow_runs(
            {"workflow_runs": [run]}, sha, [SBML_WORKFLOW], event="workflow_dispatch"
        ):
            continue
        run_id, attempt = run.get("id"), run.get("run_attempt")
        if type(run_id) is not int or type(attempt) is not int:
            continue
        try:
            verify_sbml_evidence(
                evidence_dir / str(run_id) / str(attempt), sha, biomodels_ids
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"SBML run {run_id}, attempt {attempt}: {exc}", file=sys.stderr)
            continue
        return
    raise ValueError("no successful exact-main run retained both full SBML lanes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-json", type=Path, required=True)
    parser.add_argument("--sbml-runs-json", type=Path, required=True)
    parser.add_argument("--sbml-evidence-dir", type=Path, required=True)
    parser.add_argument("--biomodels-inventory", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()

    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error("--sha must be a full lowercase Git commit SHA")
    try:
        payload = json.loads(args.runs_json.read_text(encoding="utf-8"))
        missing = qualify_workflow_runs(payload, args.sha, REQUIRED_WORKFLOWS)
        sbml_payload = json.loads(args.sbml_runs_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Cannot qualify release candidate: {exc}", file=sys.stderr)
        return 2

    if missing:
        print(
            "Release blocked; missing successful completed exact-main workflow run for "
            f"SHA {args.sha}: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 1
    try:
        inventory = json.loads(args.biomodels_inventory.read_text(encoding="utf-8"))
        model_ids = {row["id"] for row in inventory["models"]}
        if (
            not model_ids
            or len(model_ids) != inventory["matches"]
            or len(model_ids) != len(inventory["models"])
        ):
            raise ValueError("invalid pinned BioModels membership")
        qualify_sbml_runs(sbml_payload, args.sbml_evidence_dir, args.sha, model_ids)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Release blocked: {exc}.", file=sys.stderr)
        return 1
    print(
        "Required exact-main workflow runs passed for candidate SHA "
        f"{args.sha} (four push workflows and full SBML and BioModels evidence)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
