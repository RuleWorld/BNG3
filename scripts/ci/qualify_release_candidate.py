"""Check that required main-branch workflows passed for one exact commit."""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-json", type=Path, required=True)
    parser.add_argument("--sbml-runs-json", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()

    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error("--sha must be a full lowercase Git commit SHA")
    try:
        payload = json.loads(args.runs_json.read_text(encoding="utf-8"))
        missing = qualify_workflow_runs(payload, args.sha, REQUIRED_WORKFLOWS)
        sbml_payload = json.loads(args.sbml_runs_json.read_text(encoding="utf-8"))
        missing.extend(
            qualify_workflow_runs(
                sbml_payload,
                args.sha,
                ["Official SBML conformance subset"],
                event="workflow_dispatch",
            )
        )
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
    print(
        "Required exact-main workflow runs passed for candidate SHA "
        f"{args.sha} (four push workflows and official SBML manual evidence)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
