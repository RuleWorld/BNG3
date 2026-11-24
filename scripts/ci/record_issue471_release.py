"""Assemble exact-revision release evidence for issue #471 from its named checks.

The three consumers (oracle independence, oracle tamper, CI topology) run
separately.  This recorder only validates and joins their outputs; a failed or
missing consumer is retained as a failed result and never promoted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKS = (
    "release-oracle-independence",
    "release-oracle-tamper",
    "release-ci-topology",
)


def _read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def _result(check_id: str, status: str, detail: str, **extra) -> dict:
    return {
        "id": check_id,
        "status": status,
        "evidence_kind": "supported-execution",
        "supported_execution": status in {"PASS", "FAIL"},
        "related_issues": [471],
        "detail": detail,
        **extra,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--oracle-report", type=Path, required=True)
    parser.add_argument("--topology-report", type=Path, required=True)
    parser.add_argument("--tamper-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    if head != args.revision or dirty:
        parser.error("issue 471 evidence requires the requested clean revision")

    oracle = _read(args.oracle_report)
    topology = _read(args.topology_report)
    tamper = _read(args.tamper_report)
    if oracle.get("check_id") != "release-oracle-independence" or (
        str(oracle.get("revision") or oracle.get("evaluated_revision")) != args.revision
    ):
        parser.error("oracle report identity or revision is invalid")
    if topology.get("check_id") != "release-ci-topology" or (
        str(topology.get("evaluated_revision") or topology.get("revision"))
        != args.revision
    ):
        parser.error("topology report identity or revision is invalid")
    if tamper.get("check_id") != "release-oracle-tamper":
        parser.error("tamper report identity is invalid")

    oracle_status = "PASS" if oracle.get("result") == "pass" else "FAIL"
    topology_status = "PASS" if topology.get("result") == "pass" else "FAIL"
    tamper_status = "PASS" if tamper.get("result") == "pass" else "FAIL"

    inputs = [
        {
            "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in (args.oracle_report, args.topology_report, args.tamper_report)
    ]
    report = {
        "schema_version": 1,
        "source": {"revision": args.revision, "dirty": False},
        "check_id": "issue-471-release",
        "inputs": inputs,
        "references": {
            "oracle_gaps": oracle.get("findings", [])[:50],
            "topology_gaps": topology.get("acceptance_gaps", []),
            "mutation": tamper.get("mutation", {}),
        },
        "results": [
            _result(
                "release-oracle-independence",
                oracle_status,
                f"grounded rows {oracle.get('grounded_execution_rows', 0)}/{oracle.get('row_count', 0)}",
            ),
            _result(
                "release-oracle-tamper",
                tamper_status,
                tamper.get("detail", "protected expectation and mutation controls"),
            ),
            _result(
                "release-ci-topology",
                topology_status,
                f"audited workflows {len(topology.get('audited_workflows', []))}",
            ),
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in report["results"]:
        print(f"{row['id']}: {row['status']}")
    return int(any(row["status"] != "PASS" for row in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
