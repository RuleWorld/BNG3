"""Actionable reports without promoting test counts into support claims."""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from .campaign import STATUSES

BAD = {"FAIL", "TIMEOUT", "HARNESS_ERROR"}


def attach_coverage(capabilities: list[dict], results: list[dict]) -> None:
    for capability in capabilities:
        matched = []
        for result in results:
            explicit = capability["id"] in result.get("capabilities", [])
            mapped = any(
                test.replace("/", ".").removesuffix(".py") in result["id"]
                or (
                    result.get("test_file")
                    and (
                        result["test_file"] == test
                        or result["test_file"].startswith(test.rstrip("/") + "/")
                    )
                )
                for test in capability["existing_tests"]
            )
            if explicit or mapped:
                matched.append(result)
        executed = [r for r in matched if r["status"] != "NOT_TESTED"]
        capability["coverage"] = "PARTIAL" if executed else "NOT_TESTED"
        capability["result_counts"] = dict(Counter(r["status"] for r in matched))
        capability["evidence_ids"] = [r["id"] for r in matched]
        for result in matched:
            result["mapped_capabilities"] = sorted(
                set(result.get("mapped_capabilities", [])) | {capability["id"]}
            )
            result["related_issues"] = sorted(
                set(result.get("related_issues", []))
                | set(capability.get("issues", []))
            )
            if capability.get("implementation"):
                result["source_locations"] = sorted(
                    set(result.get("source_locations", []))
                    | {capability["implementation"]["path"]}
                )


def cluster_failures(results: list[dict]) -> list[dict]:
    groups = {}
    for row in results:
        if row["status"] not in BAD:
            continue
        signature = re.sub(r"\b\d+(?:\.\d+)?\b", "#", row.get("detail", "")[:1000])
        key = hashlib.sha256(
            (row["status"] + row["stage"] + signature).encode()
        ).hexdigest()[:16]
        group = groups.setdefault(
            key,
            {
                "id": key,
                "status": row["status"],
                "first_observed_stage": row["stage"],
                "signature": signature,
                "cases": [],
                "capabilities": [],
                "diagnosis_confidence": "signature-only",
                "confirmed_root_cause": None,
            },
        )
        group["cases"].append(row["id"])
        group["capabilities"] = sorted(
            set(group["capabilities"])
            | set(row.get("capabilities", []))
            | set(row.get("mapped_capabilities", []))
        )
    for group in groups.values():
        group["priority_score"] = (
            3 if group["status"] == "HARNESS_ERROR" else 2
        ) * len(group["cases"]) + len(group["capabilities"])
        group["next_action"] = (
            "Verify inputs/reference identity"
            if group["status"] == "HARNESS_ERROR"
            else "Reproduce earliest recorded divergence; minimize while preserving the same signature"
        )
    return sorted(groups.values(), key=lambda g: (-g["priority_score"], g["id"]))


def history(current: dict, previous: dict | None) -> dict:
    if previous is None:
        return {"comparable": False, "reason": "no baseline"}
    if current["comparison_key"] != previous.get("comparison_key"):
        return {
            "comparable": False,
            "reason": "configuration, corpus, tests or reference identity changed",
        }
    old = {r["id"]: r["status"] for r in previous["results"]}
    new = {r["id"]: r["status"] for r in current["results"]}
    return {
        "comparable": True,
        "new_failures": sorted(
            k for k in new if new[k] in BAD and old.get(k) == "PASS"
        ),
        "resolved": sorted(k for k in old if old[k] in BAD and new.get(k) == "PASS"),
        "newly_executed": sorted(new.keys() - old.keys()),
        "no_longer_executed": sorted(old.keys() - new.keys()),
    }


def markdown(report: dict) -> str:
    counts = Counter(r["status"] for r in report["results"])
    claims = [c for c in report["capabilities"] if c["kind"] == "semantic-claim"]

    def safe(value):
        return str(value).replace("|", "&#124;").replace("\n", " ").replace("<", "&lt;")

    lines = [
        "# BNG3 conformance evidence",
        "",
        f"Source: `{report['source']['revision']}`; dirty: `{report['source']['dirty']}`.",
        "",
        "Reporting only. Test outcomes, implementation support, legacy agreement, mathematical contracts and scientific qualification are separate.",
        "",
        "| Outcome | Cases |",
        "| --- | ---: |",
    ]
    lines += [f"| {status} | {counts[status]} |" for status in STATUSES]
    lines += [
        "",
        f"Discovered {len(report['capabilities'])} implementation/semantic entries and {len(report['corpus'])} model artifacts. Discovery is not exhaustive semantic qualification.",
        "",
        "## Capability coverage",
        "",
        "| Capability | Support | Coverage | Test outcomes | Issues |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {c['id']} | {c['support']} | {c['coverage']} | {safe(c['result_counts'])} | {', '.join('#' + str(i) for i in c['issues'])} |"
        for c in claims
    ]
    lines += [
        "",
        "## Compatibility matrix",
        "",
        "| Case / component | Reference / question | First observed stage | Outcome |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| {safe(r['id'])} | {safe(r.get('reference', r.get('question', 'functional-contract')))} | {r['stage']} | {r['status']} |"
        for r in report["results"]
        if r["stage"] != "test"
    ]
    lines += [
        "",
        "## Investigation queue",
        "",
        "Signatures suggest similar symptoms; they do not establish shared causes.",
        "",
    ]
    for group in report["failure_clusters"][:25]:
        lines += [
            f"- **{group['status']} / {group['first_observed_stage']}**, {len(group['cases'])} cases: {safe(group['signature'])[:400]}. {group['next_action']}."
        ]
    lines += [
        "",
        "## Regression history",
        "",
        safe(report["history"]),
        "",
        "## Performance",
        "",
        "Wall times in command receipts are diagnostic timings, not controlled benchmark results. Separate benchmark lanes and their qualification limits:",
        "",
    ]
    measurements = [r for r in report["results"] if r["stage"] == "performance"]
    if measurements:
        lines += [
            "| Model | Outcome | Parse median ms | Generation median ms |",
            "| --- | --- | ---: | ---: |",
        ]
        lines += [
            f"| {safe(r['id'])} | {r['status']} | {r['measurements'].get('parse_ms')} | {r['measurements'].get('generate_ms')} |"
            for r in measurements
        ]
        lines += [
            "",
            "These measurements cover fresh parse/generation repetitions. Independent speed comparisons, memory, scaling and other phases remain unqualified.",
            "",
        ]
    lines += [
        f"- {name}: `{path}` — existing separate lane; consult its evidence."
        for name, path in report["existing_lanes"].items()
    ]
    lines += [
        "",
        "Reproduction commands, model and artifact hashes, individual test outcomes, source locations, reference identities, coverage gaps and full failure details are in `report.json` and the adjacent evidence directories.",
        "",
    ]
    return "\n".join(lines)
