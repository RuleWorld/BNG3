"""The capability-union inventory of the supported surfaces (#137).

Issue #137 asks for the behaviour of BioNetGen, PyBioNetGen, the canonical
and the newer NFsim, the Atomizer and the optional tools to be inventoried,
and for every capability to carry a support status, an owner and an
acceptance gate with explicit exclusions.

This module reads the *generated* inventory - the same rows that
``python scripts/validate.py --inventory-only --report-dir <dir>`` writes to
``inventory.json`` - and asserts that the capability-union rows of that
inventory are complete:

* every capability the supported surfaces expose is present, and each of the
  six supported surfaces carries at least one capability;
* every capability carries a support status from the declared vocabulary and
  a recorded review owner;
* every capability carries a non-empty acceptance gate, and every executable
  entry of that gate names a check that exists in this repository;
* every capability records its exclusions explicitly, and a capability that
  is not fully implemented cannot leave them implicit.

The inventory records availability and the plan to qualify a capability.  It
does not approve a support policy: the per-row policy remains the maintainer
decision that issue #137 keeps open.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

from . import inventory

ISSUES = (137,)

ROOT = Path(__file__).resolve().parents[2]
UNION_PATH = ROOT / "provenance" / "capability-union.yml"
MATRIX_PATH = ROOT / "provenance" / "capability-matrix.yml"

# The supported surfaces the issue names.  Each one must be represented.
SURFACES = (
    "bionetgen",
    "pybionetgen",
    "nfsim",
    "nfsim-rasi",
    "atomizer",
    "optional-tool",
)

# The support-status vocabulary of the generated inventory.
SUPPORT = ("implemented", "partial", "unsupported", "unverified")

# The named checks of this operation.
CHECKS = (
    "surface-coverage",
    "support-status",
    "owner",
    "acceptance-gate",
    "explicit-exclusions",
    "unique-identity",
)

# The one obligation of issue #137 that a named executable check closes.
OBLIGATION_CHECK = "inventory-behavior-from-bionetgen-pybionetgen-canonical-newer-nf"


def _document(path: Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a mapping")
    return document


def union_document() -> dict:
    """The machine-readable capability-union inventory."""
    return _document(UNION_PATH)


def matrix_document() -> dict:
    """The implementation-status matrix the union inventory crosswalks."""
    return _document(MATRIX_PATH)


def generated_inventory() -> list[dict]:
    """The generated inventory, including the capability-union rows."""
    matrix = matrix_document()
    return inventory.discover_capabilities(
        ROOT, matrix["validation_capabilities"], inventory.load_union(ROOT)
    )


def union_rows() -> list[dict]:
    """The capability-union rows of the generated inventory."""
    return [
        row for row in generated_inventory() if row.get("kind") == "capability-union"
    ]


def check_ids():
    """Stable expected check identities for the capability-inventory operation."""
    ids = [f"capability-inventory:{name}" for name in CHECKS]
    ids.append(f"qualification:issue:137:{OBLIGATION_CHECK}")
    return ids


def _row(check, status, detail, **evidence):
    row = dict(
        check=check,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
        question="capability-union-inventory-versus-declared-policy",
        **evidence,
    )
    if status in {"PASS", "FAIL"}:
        row.setdefault("evidence_kind", "supported-execution")
        row.setdefault("supported_execution", True)
    else:
        row.setdefault("evidence_kind", "diagnostic-only")
        row.setdefault("supported_execution", False)
    return row


def _gate_entries(row):
    """The executable entries of an acceptance gate.

    A gate entry either names a check that exists in this repository or
    records that the gate is a maintainer decision.  A gate that names a
    check that does not exist is not a gate.
    """
    executable = []
    decisions = []
    for entry in row["acceptance_gate"]:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"{row['id']} has an empty acceptance gate entry")
        if entry.startswith("decision:"):
            decisions.append(entry)
            continue
        executable.append(entry)
    return executable, decisions


def run(directory=None):
    """Assert the generated capability inventory against the declared policy."""
    rows = generated_inventory()
    union = [row for row in rows if row.get("kind") == "capability-union"]
    return assess(union, union_document(), matrix_document())


def assess(union, document, matrix):
    """Assess the capability-union rows of the generated inventory.

    The rows are passed in, so a test can mutate one and prove that the
    check refuses it.
    """
    matrix_rows = {entry["id"] for entry in matrix["rows"]}
    crosswalked = {
        row.get("matrix_row") for row in union if row.get("matrix_row") is not None
    }
    uncrosswalked = sorted(matrix_rows - crosswalked)
    surfaces = {row["surface"] for row in union}
    missing_surfaces = sorted(set(SURFACES) - surfaces)
    extra_surfaces = sorted(surfaces - set(SURFACES))
    results = []

    results.append(
        dict(
            _row(
                "surface-coverage",
                (
                    "PASS"
                    if not missing_surfaces and not extra_surfaces and not uncrosswalked
                    else "FAIL"
                ),
                (
                    "every supported surface is inventoried and every "
                    "implementation-status row is crosswalked"
                ),
                first_difference=(
                    None
                    if not missing_surfaces and not extra_surfaces and not uncrosswalked
                    else dict(
                        missing_surfaces=missing_surfaces,
                        unexpected_surfaces=extra_surfaces,
                        uncrosswalked_matrix_rows=uncrosswalked,
                    )
                ),
                surfaces=sorted(surfaces),
                missing_surfaces=missing_surfaces,
                uncrosswalked_matrix_rows=uncrosswalked,
                capabilities=len(union),
            ),
            id="capability-inventory:surface-coverage",
            check="surface-coverage",
        )
    )

    invalid_support = sorted(
        row["id"] for row in union if row.get("support") not in SUPPORT
    )
    results.append(
        dict(
            _row(
                "support-status",
                "PASS" if not invalid_support else "FAIL",
                (
                    "every inventoried capability carries a support status from "
                    "the declared vocabulary"
                ),
                first_difference=(
                    None
                    if not invalid_support
                    else dict(invalid_support=invalid_support)
                ),
                support_counts={
                    status: sum(1 for row in union if row.get("support") == status)
                    for status in SUPPORT
                },
                invalid_support=invalid_support,
            ),
            id="capability-inventory:support-status",
            check="support-status",
        )
    )

    missing_owner = sorted(
        row["id"]
        for row in union
        if not str(row.get("owner") or "").strip()
        or not str(row.get("owner_assignment") or "").strip()
    )
    results.append(
        dict(
            _row(
                "owner",
                "PASS" if not missing_owner else "FAIL",
                (
                    "every inventoried capability records a review owner and the "
                    "state of its assignment"
                ),
                first_difference=(
                    None if not missing_owner else dict(missing_owner=missing_owner)
                ),
                owners=sorted({row["owner"] for row in union}),
                pending_assignment=sorted(
                    row["id"]
                    for row in union
                    if row.get("owner_assignment") == "pending-maintainer"
                ),
                missing_owner=missing_owner,
            ),
            id="capability-inventory:owner",
            check="owner",
        )
    )

    broken_gates = []
    empty_gates = []
    decision_gates = []
    for row in union:
        if not row.get("acceptance_gate"):
            empty_gates.append(row["id"])
            continue
        try:
            executable, decisions = _gate_entries(row)
        except ValueError as exc:
            broken_gates.append(f"{row['id']}: {exc}")
            continue
        if decisions:
            decision_gates.append(row["id"])
        for entry in executable:
            path = entry.split("::")[0]
            if not (ROOT / path).exists():
                broken_gates.append(f"{row['id']}: {entry} does not exist")
    results.append(
        dict(
            _row(
                "acceptance-gate",
                "PASS" if not broken_gates and not empty_gates else "FAIL",
                (
                    "every inventoried capability names the checks that would "
                    "qualify it, and every named check exists"
                ),
                first_difference=(
                    None
                    if not broken_gates and not empty_gates
                    else dict(broken_gates=broken_gates, empty_gates=empty_gates)
                ),
                broken_gates=broken_gates,
                empty_gates=empty_gates,
                decision_gates=decision_gates,
            ),
            id="capability-inventory:acceptance-gate",
            check="acceptance-gate",
        )
    )

    implicit = sorted(
        row["id"]
        for row in union
        if row.get("support") != "implemented" and not row.get("exclusions")
    )
    results.append(
        dict(
            _row(
                "explicit-exclusions",
                "PASS" if not implicit else "FAIL",
                (
                    "every inventoried capability records its exclusions "
                    "explicitly, and a capability that is not fully implemented "
                    "cannot leave them implicit"
                ),
                first_difference=(
                    None if not implicit else dict(implicit_exclusions=implicit)
                ),
                implicit_exclusions=implicit,
                excluded_capabilities=sum(1 for row in union if row.get("exclusions")),
            ),
            id="capability-inventory:explicit-exclusions",
            check="explicit-exclusions",
        )
    )

    # The generated inventory keeps one identity per capability: a union row
    # that shadows a semantic claim would make the inventory ambiguous.
    identities = Counter(row["id"] for row in generated_inventory())
    duplicated = sorted(identity for identity, count in identities.items() if count > 1)
    results.append(
        dict(
            _row(
                "unique-identity",
                "PASS" if not duplicated else "FAIL",
                (
                    "every capability of the generated inventory keeps its own "
                    "identity, and a union row never shadows a semantic claim"
                ),
                first_difference=(
                    None if not duplicated else dict(duplicated_identities=duplicated)
                ),
                duplicated_identities=duplicated,
                capabilities=len(identities),
            ),
            id="capability-inventory:unique-identity",
            check="unique-identity",
        )
    )

    failures = [row["id"] for row in results if row["status"] == "FAIL"]
    obligation = dict(
        _row(
            OBLIGATION_CHECK,
            "FAIL" if failures else "PASS",
            (
                "the generated inventory records the behaviour of every "
                "supported surface with a support status, an owner, an "
                "acceptance gate and explicit exclusions"
            ),
            capabilities=len(union),
            surfaces=sorted(surfaces),
            policy_counts={
                policy: sum(1 for row in union if row.get("policy") == policy)
                for policy in document.get("policy_vocabulary", [])
            },
            inventory_status=document.get("status"),
        ),
        id=f"qualification:issue:137:{OBLIGATION_CHECK}",
        check=OBLIGATION_CHECK,
    )
    if failures:
        obligation["detail"] = "the capability inventory is incomplete: " + ", ".join(
            sorted(failures)
        )
        obligation["first_difference"] = dict(failed_checks=sorted(failures))
    results.append(obligation)
    return results


def run_worker(directory):
    """Execute the operation in the integrated worker and return its rows."""
    return run(Path(directory) if directory else None)
