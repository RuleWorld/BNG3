"""Check disposition of every imported C++ contract; never infer execution."""

import argparse
import json
import re
from pathlib import Path


def audit(root: Path, manifest: dict) -> dict:
    roots = [
        "tests/energy/tests/cpp",
        "tests/architecture_contracts/nfcore2",
        "tests/architecture_contracts/nfnext",
    ]
    actual = {
        p.relative_to(root).as_posix()
        for directory in roots
        for p in (root / directory).rglob("*.cpp")
        if "reference" not in p.parts
    }
    entries = manifest["contracts"]
    listed = [entry["path"] for entry in entries]
    failures = []
    if len(listed) != len(set(listed)):
        failures.append("duplicate contract paths")
    if actual != set(listed):
        failures.append(
            f"unclassified or missing contracts: {sorted(actual ^ set(listed))}"
        )
    counts = {}
    for entry in entries:
        status = entry["status"]
        if status not in {
            "required",
            "reference",
            "blocked-api",
            "design-only",
            "auxiliary",
        }:
            failures.append(f"unknown disposition: {entry['path']}")
            continue
        counts[status] = counts.get(status, 0) + 1
        if entry["path"] not in actual:
            continue
        text = (root / entry["path"]).read_text()
        # These simple macros occur on one line in the imported corpus.
        uncommented = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
        empty = re.findall(
            r"\b(?:TEST|TEST_CASE|CONTRACT_CASE)\s*\([^\n{}]*\)\s*\{\s*\}", uncommented
        )
        if empty and status != "design-only":
            failures.append(f"empty assertions outside design notes: {entry['path']}")
        if status in {"required", "reference"}:
            if not entry.get("target"):
                failures.append(f"no executable target: {entry['path']}")
            cmake = (
                (root / "tests/energy/cmake/energy_tests.cmake").read_text()
                if status == "required"
                else (root / "tests/architecture_contracts/CMakeLists.txt").read_text()
            )
            if Path(entry["path"]).name not in cmake:
                failures.append(f"executable source absent from CMake: {entry['path']}")
    return {
        "passed": not failures,
        "file_dispositions": counts,
        "failures": failures,
        "note": "Inventory only. Blocked and design-only contracts are not test passes.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[3]
    )
    args = parser.parse_args()
    manifest = json.loads(
        (args.root / "provenance/architecture-contracts.json").read_text()
    )
    report = audit(args.root, manifest)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
