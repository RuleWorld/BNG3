"""Contracts for generated format and model-reuse consumer stages.

These stages expose cross-component failures for the generated integration
campaign. They are detectors, not product fixes or broad equivalence claims.
"""

from __future__ import annotations

OPERATIONS = ("bngir-v01", "bngir-v02", "bngl-reload", "sbml-reload", "reuse")

# Each persisted worker check carries the issue set that it can help diagnose.
# Keep the lists narrow enough that reports remain useful for issue triage.
CHECKS = {
    "bngir-v01": ("semantic-equality", "network", "simulation"),
    "bngir-v02": ("semantic-equality", "network", "simulation"),
    "bngl-reload": ("semantic-equality", "network", "simulation"),
    "sbml-reload": ("export", "rr-consumer", "trajectory"),
    "reuse": ("original", "mutation-fresh", "reset", "seeded-repeat"),
}

ISSUES = {
    "bngir-v01": (153, 154, 155, 156),
    "bngir-v02": (153, 154, 155, 156),
    "bngl-reload": (138, 154, 163),
    "sbml-reload": (143, 159, 163),
    "reuse": (138, 141, 143),
}


def expected_check_ids(case_ids):
    """Return the required per-case check IDs independently of execution."""
    return [
        f"{case}:{operation}:{check}"
        for case in case_ids
        for operation in OPERATIONS
        for check in CHECKS[operation]
    ]


def validate_checks(case_id, operation, checks):
    """Validate worker evidence without turning unsupported into a pass."""
    expected = set(CHECKS[operation])
    seen = set()
    errors = []
    for row in checks:
        name = row.get("name")
        if name in seen:
            errors.append(f"duplicate check {name!r}")
        seen.add(name)
        if row.get("id") != f"{case_id}:{operation}:{name}":
            errors.append(f"invalid check identity for {name!r}")
        if row.get("status") not in {
            "PASS",
            "FAIL",
            "UNSUPPORTED",
            "NOT_TESTED",
            "HARNESS_ERROR",
        }:
            errors.append(f"invalid status for {name!r}")
        if not isinstance(row.get("detail"), str):
            errors.append(f"missing detail for {name!r}")
        if "first_difference" not in row:
            errors.append(f"missing first_difference for {name!r}")
        if row.get("issue_ids") != list(ISSUES[operation]):
            errors.append(f"invalid issue links for {name!r}")
    if seen != expected:
        errors.append(
            f"check set mismatch: missing={sorted(expected - seen)}, "
            f"extra={sorted(seen - expected)}"
        )
    return errors


def status_from_checks(case_id, operation, checks):
    """Return a strict operation status from the required granular checks."""
    if validate_checks(case_id, operation, checks):
        return "HARNESS_ERROR"
    statuses = {row["status"] for row in checks}
    if "HARNESS_ERROR" in statuses:
        return "HARNESS_ERROR"
    if "FAIL" in statuses:
        return "FAIL"
    if "UNSUPPORTED" in statuses:
        return "UNSUPPORTED"
    if "NOT_TESTED" in statuses:
        return "NOT_TESTED"
    return "PASS"
