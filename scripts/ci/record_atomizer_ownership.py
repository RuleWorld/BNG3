#!/usr/bin/env python3
"""Produce revision-bound ownership evidence for issue 164's module check.

Running a pytest file and reading its JUnit names is not evidence that the
checks ran against the tested revision or the intended module. This producer
verifies the checkout revision and cleanliness, executes the named ownership
contract, and emits a receipt that binds the result to HEAD and to the module
under test. The recipient recorder rejects any receipt whose revision differs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_TEST = "tests/validation/test_atomizer_module_ownership.py"
EXPECTED_TESTS = (
    "test_atomizer_transformation_ownership",
    "test_owned_entry_point_is_importable",
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--test", default=DEFAULT_TEST)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if head != args.source_revision:
        raise SystemExit(f"ownership evidence revision mismatch: {head}")
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    )
    if dirty and not args.allow_dirty:
        raise SystemExit("Issue 164 ownership evidence requires a clean checkout")

    with tempfile.TemporaryDirectory() as work:
        junit = Path(work) / "ownership.xml"
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", args.test, f"--junitxml={junit}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise SystemExit(
                f"ownership contract failed:\n{completed.stdout}\n{completed.stderr}"
            )
        junit_bytes = junit.read_bytes()
        root = ET.fromstring(junit_bytes)
        cases = {}
        for case in root.iter("testcase"):
            name = case.get("name", "").split("[")[0]
            bad = any(
                case.find(tag) is not None for tag in ("failure", "error", "skipped")
            )
            cases[name] = "FAIL" if bad else "PASS"
    missing = [name for name in EXPECTED_TESTS if cases.get(name) != "PASS"]
    if missing:
        raise SystemExit(f"ownership contract did not execute: {missing}")

    receipt = {
        "schema_version": 1,
        "source": {"revision": head, "dirty": dirty},
        "module": "python/bionetgen/atomizer/modern",
        "selector": args.test,
        "junit_sha256": hashlib.sha256(junit_bytes).hexdigest(),
        "results": [
            {
                "id": "release-atomizer-modules",
                "status": "PASS",
                "check": "release-atomizer-modules",
                "related_issues": [164],
                "evidence_kind": "supported-execution",
                "supported_execution": True,
                "stage": "atomizer-module-ownership",
                "detail": "One owning module per named Atomizer transformation, verified at this revision.",
                "selector": args.test,
            }
        ],
    }
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
