"""Record the #471 protected-expectation and mutation-control evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tests/validation/policy/mutation-baseline.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if head != args.revision or dirty:
        parser.error("tamper evidence requires the requested clean revision")
    proc = subprocess.run(
        [
            sys.executable,
            "tests/validation/policy/run_antigaming.py",
            "--root",
            str(ROOT),
            "--base",
            args.base,
            "--head",
            args.revision,
            "--check",
            "release-protected-expectations",
            "--check",
            "release-no-product-fixture-names",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    baseline = json.loads(BASELINE.read_bytes())
    verdict = "pass" if (
        proc.returncode == 0
        and baseline.get("status") == "verified"
        and baseline.get("caught", 0) >= baseline.get("denominator", 1)
        and baseline.get("denominator", 0) > 0
    ) else "fail"
    report = {
        "schema_version": 1,
        "check_id": "release-oracle-tamper",
        "evaluated_revision": args.revision,
        "working_tree_dirty": False,
        "result": verdict,
        "detail": proc.stdout.strip(),
        "protected_checks": ["release-protected-expectations", "release-no-product-fixture-names"],
        "mutation": {
            "source_revision": baseline.get("revision"),
            "baseline_sha256": hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
            "caught": baseline.get("caught"),
            "denominator": baseline.get("denominator"),
            "score": (
                f"{baseline.get('caught')}/{baseline.get('denominator')}"
                if baseline.get("denominator")
                else "unavailable"
            ),
            "mutants": baseline.get("mutants", []),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"tamper: {verdict}; mutation score {report['mutation']['score']}")
    return int(verdict != "pass")


if __name__ == "__main__":
    raise SystemExit(main())
