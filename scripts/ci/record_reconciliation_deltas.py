#!/usr/bin/env python3
"""Verify executed test evidence for non-not-applicable #180 reconciliation deltas.

Consumes exact-revision JUnit XML outputs (pytest and CTest), maps every
non-``not-applicable`` entry in ``provenance/reconciliation/{bionetgen,nfsim,
pybionetgen}.yml`` to its referenced test outcomes, and emits one non-aggregate
``reconciliation-delta[source,revision]`` result per ledger entry.

Fail-closed guarantees:
- Requires an exact, clean BNG3 revision (unless ``--allow-dirty`` is passed
  for offline unit tests) and an exact pin report matching ``upstreams.lock.yml``.
- Treats skipped, error, failed, or unexecuted tests as ``FAIL``.
- Treats JUnit ``<property name="semantic_result" value="..."/>`` values other
  than ``PASS`` as ``FAIL`` even if the pytest wrapper returned exit code 0.
- Keeps ``pending-port`` entries as honest ``FAIL`` / ``observed-failure``
  records rather than fabricating passes for unported differences.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
UPSTREAMS = ("bionetgen", "nfsim", "pybionetgen")
INCORPORATED_CLASSIFICATIONS = frozenset(
    {
        "incorporated-identically",
        "incorporated-equivalently",
        "superseded-by-bng3",
    }
)


@dataclass(frozen=True)
class ExecutedCase:
    """Single executed test case parsed from a JUnit XML report."""

    classname: str
    name: str
    file: str
    passed: bool
    semantic_failures: tuple[str, ...]


def _parse_semantic_failures(case: ET.Element) -> tuple[str, ...]:
    failures: list[str] = []
    for prop in case.findall("./properties/property"):
        prop_name = (prop.get("name") or "").strip()
        if prop_name == "semantic_result" or prop_name.endswith(".semantic_result"):
            value = (prop.get("value") or "").strip()
            if value != "PASS":
                failures.append(f"{prop_name}={value or '<empty>'}")
    return tuple(failures)


def parse_junit_cases(paths: list[Path]) -> list[ExecutedCase]:
    """Parse pytest and CTest JUnit XML reports into ``ExecutedCase`` records."""
    cases: list[ExecutedCase] = []
    for path in paths:
        if not path.is_file():
            raise ValueError(f"missing JUnit report: {path}")
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        for suite in suites:
            for case in suite.findall("testcase"):
                status_attr = (case.get("status") or "").strip().lower()
                has_problem = any(
                    case.find(tag) is not None
                    for tag in ("failure", "error", "skipped")
                )
                if status_attr and status_attr not in {"run", "passed", "pass"}:
                    has_problem = True
                semantic_failures = _parse_semantic_failures(case)
                cases.append(
                    ExecutedCase(
                        classname=(case.get("classname") or "").strip(),
                        name=(case.get("name") or "").strip(),
                        file=(case.get("file") or "").strip(),
                        passed=(not has_problem) and (not semantic_failures),
                        semantic_failures=semantic_failures,
                    )
                )
    return cases


def _match_python_ref(ref: str, cases: list[ExecutedCase]) -> list[ExecutedCase]:
    file_part, _, symbol_part = ref.partition("::")
    stem = Path(file_part).stem
    parts = symbol_part.split("::") if symbol_part else []
    fn_name = parts[-1] if parts else ""
    class_part = parts[-2] if len(parts) >= 2 else ""
    matched: list[ExecutedCase] = []
    for case in cases:
        base_name = case.name.split("[", 1)[0]
        if base_name != fn_name:
            continue
        module_tokens = case.classname.split(".")
        file_match = bool(
            case.file and (case.file == file_part or Path(case.file).stem == stem)
        )
        class_match = stem in module_tokens and (
            not class_part or class_part in module_tokens
        )
        if file_match or class_match:
            matched.append(case)
    return matched


def _match_cpp_ref(ref: str, cases: list[ExecutedCase]) -> list[ExecutedCase]:
    _, _, case_name = ref.partition("::")
    if not case_name:
        return []
    return [
        case
        for case in cases
        if case.name == case_name or case.name.endswith(f"::{case_name}")
    ]


def match_test_reference(ref: str, cases: list[ExecutedCase]) -> list[ExecutedCase]:
    """Return all executed JUnit cases corresponding to ledger ref ``ref``."""
    file_part, _, _ = ref.partition("::")
    if file_part.endswith(".py"):
        return _match_python_ref(ref, cases)
    return _match_cpp_ref(ref, cases)


def evaluate_ledger_deltas(
    *,
    ledgers: dict[str, dict[str, Any]],
    lock: dict[str, Any],
    pin_report: dict[str, Any],
    cases: list[ExecutedCase],
    revision: str,
) -> dict[str, Any]:
    """Evaluate every non-``not-applicable`` ledger entry against JUnit results."""
    source = {"revision": revision, "dirty": False}
    if pin_report.get("source") != source or pin_report.get("errors") != []:
        raise ValueError("pin report revision, cleanliness, or error state is invalid")
    pin_sources = pin_report.get("sources", {})
    if set(pin_sources) != set(UPSTREAMS):
        raise ValueError("pin report does not cover all three canonical upstreams")
    for name in UPSTREAMS:
        expected = lock["sources"][name]["revision"]
        details = pin_sources.get(name, {})
        if details.get("checkout_revision") != expected or details.get("errors") != []:
            raise ValueError(
                f"{name}: pin report checkout does not match locked revision"
            )

    results: list[dict[str, Any]] = []
    summary = {
        "total_non_applicable": 0,
        "passed": 0,
        "failed": 0,
        "pending_port": 0,
    }
    for name in sorted(UPSTREAMS):
        ledger = ledgers[name]
        for entry in ledger.get("entries", []):
            classification = str(entry.get("classification", ""))
            if classification == "not-applicable":
                continue
            summary["total_non_applicable"] += 1
            source_rev = str(entry.get("source_revision", ""))
            check_id = f"reconciliation-delta[{name},{source_rev}]"
            tests = list(entry.get("tests") or [])
            matched_tests: list[str] = []
            missing_tests: list[str] = []
            failed_tests: list[str] = []
            semantic_failures: list[str] = []
            for ref in tests:
                hits = match_test_reference(ref, cases)
                if not hits:
                    missing_tests.append(ref)
                    continue
                if all(hit.passed for hit in hits):
                    matched_tests.append(ref)
                else:
                    failed_tests.append(ref)
                    for hit in hits:
                        for sf in hit.semantic_failures:
                            semantic_failures.append(f"{ref}: {sf}")

            is_pending = classification == "pending-port"
            if is_pending:
                summary["pending_port"] += 1
            tests_ok = (
                bool(tests)
                and not missing_tests
                and not failed_tests
                and not semantic_failures
            )
            passed = (
                (not is_pending)
                and (classification in INCORPORATED_CLASSIFICATIONS)
                and tests_ok
            )
            if passed:
                summary["passed"] += 1
                detail = (
                    f"{classification}: {len(matched_tests)}/{len(tests)} "
                    "referenced checks passed"
                )
            else:
                summary["failed"] += 1
                reasons: list[str] = []
                if is_pending:
                    reasons.append("classification is pending-port")
                elif classification not in INCORPORATED_CLASSIFICATIONS:
                    reasons.append(f"unqualified classification: {classification}")
                if not tests:
                    reasons.append("no test references declared")
                if missing_tests:
                    reasons.append(f"unexecuted tests: {', '.join(missing_tests)}")
                if failed_tests:
                    reasons.append(f"failed tests: {', '.join(failed_tests)}")
                if semantic_failures:
                    reasons.append(
                        f"semantic_result failures: {'; '.join(semantic_failures)}"
                    )
                detail = "; ".join(reasons)

            results.append(
                {
                    "id": check_id,
                    "status": "PASS" if passed else "FAIL",
                    "evidence_kind": (
                        "supported-execution" if passed else "observed-failure"
                    ),
                    "supported_execution": passed,
                    "related_issues": [180],
                    "source": name,
                    "source_revision": source_rev,
                    "classification": classification,
                    "matched_tests": matched_tests,
                    "missing_tests": missing_tests,
                    "failed_tests": failed_tests,
                    "semantic_failures": semantic_failures,
                    "detail": detail,
                }
            )

    references = {
        name: {"revision": lock["sources"][name]["revision"]} for name in UPSTREAMS
    }
    return {
        "schema_version": 1,
        "acceptance_check": "reconciliation-delta-execution",
        "source": source,
        "references": references,
        "summary": summary,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--pin-report", type=Path, required=True)
    parser.add_argument("--junit", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"], text=True
        ).strip()
    )
    if head != args.revision or (dirty and not args.allow_dirty):
        parser.error("reconciliation delta verification requires a clean matching tree")

    lock = json.loads((root / "provenance/upstreams.lock.yml").read_bytes())
    pin_report = json.loads(args.pin_report.read_bytes())
    ledgers = {
        name: json.loads((root / f"provenance/reconciliation/{name}.yml").read_bytes())
        for name in UPSTREAMS
    }
    cases = parse_junit_cases(args.junit)
    report = evaluate_ledger_deltas(
        ledgers=ledgers,
        lock=lock,
        pin_report=pin_report,
        cases=cases,
        revision=args.revision,
    )
    report["inputs"] = [
        {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in [args.pin_report, *args.junit]
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = report["summary"]
    print(
        f"reconciliation deltas: {summary['passed']}/{summary['total_non_applicable']} "
        f"PASS ({summary['failed']} FAIL, {summary['pending_port']} pending-port)"
    )
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
