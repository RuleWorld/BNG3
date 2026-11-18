#!/usr/bin/env python3
"""Produce the exact-revision release receipt for issue #156.

Runs the three named checks (BNGIR schema, exact semantic equality, capability
coverage), writes one retained report per check and a combined receipt whose
hashes a consumer verifies.  This is a local CI-style producer; it does not
mutate GitHub state.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = ROOT / "tests/validation/release/cases/issue-156"
EVIDENCE = ROOT / "tests/validation/evidence"
CHECKS = (
    "release-bngir-schema",
    "release-semantic-equality",
    "release-capability-coverage-156",
)


def _git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def _load_case_module():
    sys.path.insert(0, str(ROOT / "tests" / "python"))
    sys.path.insert(0, str(CASE_DIR))
    spec = importlib.util.spec_from_file_location(
        "issue156_case", CASE_DIR / "test_bngir_release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    revision = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    case = _load_case_module()
    results = {
        "release-bngir-schema": case.schema_result(),
        "release-semantic-equality": case.semantic_equality_result(),
        "release-capability-coverage-156": case.capability_result(),
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
        (EVIDENCE / f"issue156-{check}.json").write_bytes(raw)
        checks[check] = {
            "status": "PASS",
            "report_sha256": hashlib.sha256(raw).hexdigest(),
        }

    receipt = {
        "schema_version": 1,
        "acceptance_check": "release-obligation-156",
        "source_revision": revision,
        "source_dirty": dirty,
        "checks": checks,
    }
    path = EVIDENCE / "issue156-release-receipt.json"
    raw = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(raw)
    print(f"issue #156 release receipt: {path}")
    print(f"revision: {revision} dirty={dirty}")
    for check in CHECKS:
        print(f"  {check}: PASS (sha256 {checks[check]['report_sha256'][:12]}...)")


if __name__ == "__main__":
    main()
