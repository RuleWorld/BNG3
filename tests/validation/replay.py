"""Bounded semantic replays for reports produced in the current trusted checkout.

Only commands with a fresh --report-dir and machine-readable named leaf output
are supported. Exit codes alone never establish reproduction. Imported/downloaded
reports should be packaged with triage, not executed with this opt-in tool.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from . import campaign, inventory, triage

ROOT = Path(__file__).resolve().parents[2]


def verify_configuration(original, replayed):
    before = copy.deepcopy(original.get("configuration", {}))
    after = copy.deepcopy(replayed.get("configuration", {}))
    cases_before, cases_after = before.pop("cases", []), after.pop("cases", [])
    if before != after:
        raise ValueError("replay configuration differs")
    if not all(case in cases_before for case in cases_after) or (
        cases_before and not cases_after
    ):
        raise ValueError("replay selected case configuration differs")


def verify_identity(report):
    source = report.get("source", {})
    if report.get("input_changes_during_run"):
        raise ValueError("original report records changed inputs during execution")
    if source.get("dirty") is not False or campaign.git(ROOT, "status", "--porcelain"):
        raise ValueError("replay requires a clean recorded source checkout")
    if campaign.git(ROOT, "rev-parse", "HEAD") != source.get("revision"):
        raise ValueError("replay source revision differs")
    subject = report.get("subject", {})
    if not subject.get("binary") or not subject.get("sha256"):
        raise ValueError("replay subject identity missing")
    campaign.verify_digest(Path(subject["binary"]), subject["sha256"])
    for name, reference in report.get("references", {}).items():
        if not all(reference.get(key) for key in ("path", "revision", "repository")):
            raise ValueError("replay reference identity incomplete: " + name)
        campaign.verify_source(Path(reference["path"]), reference)
        for path, sha in (
            ("binary", "sha256"),
            ("script", "script_sha256"),
            ("network_binary", "network_binary_sha256"),
        ):
            if reference.get(path):
                if not reference.get(sha):
                    raise ValueError("replay reference digest missing: " + name)
                campaign.verify_digest(Path(reference[path]), reference[sha])
    for relative, expected in report.get("inputs", {}).items():
        campaign.verify_digest(ROOT / relative, expected)


def execute_case(report, row, directory, *, timeout):
    command = row.get("command")
    if not (
        isinstance(command, list)
        and command
        and all(isinstance(x, str) for x in command)
        and command.count("--report-dir") == 1
        and command.index("--report-dir") < len(command) - 1
    ):
        return {
            "case_id": row["id"],
            "status": "UNSUPPORTED_REPLAY",
            "report": None,
            "detail": "no exact report-producing command; manual named-check replay required",
        }
    directory = Path(directory).resolve()
    if directory.exists():
        raise ValueError("replay attempt directory must be fresh")
    output = directory / "output"
    command = list(command)
    command[command.index("--report-dir") + 1] = str(output)
    env = dict(os.environ, **report.get("configuration", {}).get("environment", {}))
    receipt = campaign.run_command(command, directory, timeout, cwd=ROOT, env=env)
    result = {
        "case_id": row["id"],
        "status": "UNVERIFIED",
        "report": None,
        "receipt": receipt,
        "detail": "no named check output",
    }
    path = output / "report.json"
    try:
        observed = json.loads(path.read_text())
        if observed.get("source") != report.get("source"):
            raise ValueError("replay source identity differs")
        verify_configuration(report, observed)
        for name in ("references", "inputs", "subject", "platform"):
            if observed.get(name) != report.get(name):
                raise ValueError("replay identity differs: " + name)
        observed_rows = triage._leaves(observed)
        original_rows = triage._leaves(report)
        check = observed_rows.get(row["id"])
        if check is None:
            raise ValueError("named check missing from replay report")
        if any(check.get(key) != row.get(key) for key in ("stage", "check")):
            raise ValueError("named check contract differs")
        repeated = dict(
            report,
            results=[
                actual
                for identity, actual in observed_rows.items()
                if identity in original_rows
            ],
            generated_at=datetime.now(timezone.utc).isoformat(),
            replay_evidence={
                "report_sha256": inventory.sha256(path),
                "receipt": str(directory / "command.json"),
                "source": observed["source"],
            },
        )
        result.update(
            status="OBSERVED",
            report=repeated,
            detail="actual named leaf retained; process exit is diagnostic only",
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["detail"] = str(exc)
    return result


def select_cases(report, *, max_cases):
    """Spend replay budget on distinct exact invocations, not duplicate symptoms."""
    seen, selected = set(), []
    for _, row in sorted(triage._leaves(report).items()):
        if row["status"] != "FAIL":
            continue
        command = row.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(x, str) for x in command)
        ):
            continue
        identity = tuple(command)
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(row)
        if len(selected) >= max_cases:
            break
    return selected


def run(report_path, output, *, max_cases=2, runs=1, timeout=40, budget=90):
    if not (
        1 <= max_cases <= 20
        and 1 <= runs <= 3
        and 0 < timeout <= 120
        and 0 < budget <= 600
    ):
        raise ValueError("replay budgets outside allowed bounds")
    report_path, output = Path(report_path).resolve(), Path(output).resolve()
    report = json.loads(report_path.read_text())
    verify_identity(report)
    if output.exists():
        raise ValueError("replay output directory must be fresh")
    output.mkdir(parents=True)
    selected = select_cases(report, max_cases=max_cases)
    start, attempts, replicate_paths = time.monotonic(), [], []
    # One semantic replay per unique invocation can qualify several failing leaves.
    # Selection remains bounded by case count; no process-code-only qualification.
    for row in selected:
        for _ in range(runs):
            remaining = budget - (time.monotonic() - start)
            if remaining <= 0:
                break
            directory = output / f"attempt-{len(attempts):03}"
            result = execute_case(
                report, row, directory, timeout=min(timeout, remaining)
            )
            repeated = result.pop("report")
            if repeated:
                path = output / f"replicate-{len(replicate_paths):03}.json"
                path.write_text(json.dumps(repeated, indent=2) + "\n")
                replicate_paths.append(path)
            attempts.append(result)
    verify_identity(report)
    manifest = {
        "schema_version": 1,
        "source": report["source"],
        "attempts": attempts,
        "replicate_reports": [str(p) for p in replicate_paths],
        "budget_seconds": budget,
        "elapsed_seconds": time.monotonic() - start,
        "claim": "named leaf reproduction only; no shared root cause or stochastic parity inferred",
    }
    (output / "replay.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--execute", action="store_true", help="execute trusted local report commands"
    )
    parser.add_argument("--max-cases", type=int, default=2)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=40)
    parser.add_argument("--budget", type=float, default=90)
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error(
            "execution requires --execute and a trusted current-checkout report"
        )
    try:
        ledger = run(
            args.report,
            args.output,
            max_cases=args.max_cases,
            runs=args.runs,
            timeout=args.timeout,
            budget=args.budget,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"replay infrastructure error: {exc}\n")
    print(
        json.dumps(
            {
                "attempts": len(ledger["attempts"]),
                "observed": len(ledger["replicate_reports"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
