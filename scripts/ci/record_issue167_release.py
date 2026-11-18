#!/usr/bin/env python3
"""Produce the exact-revision release receipt for issue #167.

Runs the three named checks (Lean kernel proof, production/formal stochastic
correspondence, obligation reconciliation), writes one retained report per check
under ``tests/validation/evidence/``, and writes a combined receipt whose report
hashes the consumer verifies.  This is a local CI-style producer; it does not
mutate GitHub state.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = ROOT / "tests/validation/release/cases/issue-167"
EVIDENCE = ROOT / "tests/validation/evidence"
CHECKS = (
    "release-stochastic-proof",
    "release-stochastic-correspondence",
    "release-obligation-167",
)


def _git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def _load_case_module():
    sys.path.insert(0, str(ROOT / "tests" / "python"))
    sys.path.insert(0, str(CASE_DIR))
    spec = importlib.util.spec_from_file_location(
        "issue167_case", CASE_DIR / "test_stochastic_semantics.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    if shutil.which("lake") is None:
        raise SystemExit(
            "record_issue167_release: pinned Lean toolchain (lake) is required"
        )
    revision = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    case = _load_case_module()

    results = {
        "release-stochastic-proof": case.proof_result(),
        "release-stochastic-correspondence": case.correspondence_result(
            Path(tempfile.mkdtemp())
        ),
        "release-obligation-167": case.obligation_result(),
    }

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    checks = {}
    for check in CHECKS:
        payload = {
            "schema_version": 1,
            "acceptance_check": check,
            "source_revision": revision,
            "source_dirty": dirty,
            "result": results[check],
        }
        raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
        path = EVIDENCE / f"issue167-{check}.json"
        path.write_bytes(raw)
        checks[check] = {
            "status": "PASS",
            "report_sha256": hashlib.sha256(raw).hexdigest(),
        }

    receipt = {
        "schema_version": 1,
        "acceptance_check": "release-obligation-167",
        "source_revision": revision,
        "source_dirty": dirty,
        "checks": checks,
    }
    receipt_path = EVIDENCE / "issue167-release-receipt.json"
    raw = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode()
    receipt_path.write_bytes(raw)
    print(f"issue #167 release receipt: {receipt_path}")
    print(f"revision: {revision} dirty={dirty}")
    for check in CHECKS:
        print(f"  {check}: PASS (sha256 {checks[check]['report_sha256'][:12]}...)")


if __name__ == "__main__":
    main()
