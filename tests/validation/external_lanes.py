"""Adapters for existing SBML and benchmark reports; no shared PASS inference."""

from __future__ import annotations

import json
import sys

from .campaign import run_command

STATUS = {
    "passed": "PASS",
    "failed": "FAIL",
    "unsupported": "UNSUPPORTED",
    "timeout": "TIMEOUT",
    "invalid_source": "INVALID_INPUT",
    "not_run": "NOT_TESTED",
}


def sbml_results(document):
    rows = []
    for record in document.get("records", []):
        for stage, value, capability, question in (
            (
                "official-conformance",
                record.get("official_conformance", {}),
                "sbml.native-import",
                "official-reference-conformance",
            ),
            ("import-roundtrip", record, "atomizer.core-lowering", "format-semantics"),
            (
                "cross-engine-simulation",
                record.get("simulation_comparison", {}),
                "simulation.ode",
                "independent-numerical-agreement",
            ),
        ):
            status = STATUS.get(value.get("status"), "HARNESS_ERROR")
            if stage == "cross-engine-simulation" and isinstance(
                value.get("passed"), bool
            ):
                status = "PASS" if value["passed"] else "FAIL"
            elif (
                stage == "cross-engine-simulation"
                and not value
                and record.get("status")
                in {"unsupported", "failed", "timeout", "invalid_source"}
            ):
                status = "NOT_TESTED"
            rows.append(
                {
                    "id": f"ssts:{record.get('category')}:{record.get('id')}:{stage}",
                    "stage": stage,
                    "status": status,
                    "detail": value.get("reason", value.get("error", "")),
                    "capabilities": [capability],
                    "question": question,
                    "reference": (
                        "sbml-test-suite"
                        if stage == "official-conformance"
                        else (
                            "libroadrunner"
                            if stage == "cross-engine-simulation"
                            else "roundtrip"
                        )
                    ),
                }
            )
    return rows


def benchmark_results(document):
    return [
        {
            "id": "benchmark:" + record["model"],
            "stage": "performance",
            "status": "PASS" if record["status"] == "ok" else "FAIL",
            "detail": record.get("error", ""),
            "question": "performance-measurement-only",
            "measurements": record,
        }
        for record in document.get("models", [])
    ]


def run_existing_lane(name, root, directory, env, *, sbml_suite=None, timeout=7200):
    work = directory / "lanes" / name
    output = work / "results.json"
    if name == "performance":
        command = [
            sys.executable,
            str(root / "benchmarks/run_benchmarks.py"),
            "--models",
            "simple_system",
            "blbr",
            "--generation-only",
            "--repeats",
            "5",
            "--json",
            str(output),
            "--markdown",
            str(work / "results.md"),
        ]
        adapter = benchmark_results
    else:
        if sbml_suite is None:
            return [
                {
                    "id": name,
                    "stage": "reference-preflight",
                    "status": "HARNESS_ERROR",
                    "detail": "full tier requires --sbml-suite (locked official suite checkout)",
                }
            ]
        command = [
            sys.executable,
            str(root / "scripts/ci/validate_sbml_test_suite.py"),
            "--suite-dir",
            str(sbml_suite.resolve()),
            "--json",
            str(output),
            "--isolate-cases",
            "--jobs",
            "4",
            "--case-timeout",
            "60",
        ]
        adapter = sbml_results
    receipt = run_command(
        command, work, timeout, required=["results.json"], env=env, cwd=root
    )
    rows = []
    try:
        rows = adapter(json.loads(output.read_text()))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        receipt.update(status="HARNESS_ERROR", detail=str(exc))
    if not rows or receipt["status"] != "PASS":
        rows.append(
            {
                "id": name + ":process",
                "stage": "lane-execution",
                "status": (
                    receipt["status"]
                    if receipt["status"] != "PASS"
                    else "HARNESS_ERROR"
                ),
                "detail": receipt["detail"] or "empty report",
            }
        )
    return rows
