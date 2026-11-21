"""Read-only publication check for the #174 CPU baseline artifact.

A published baseline is a scientific claim about speed *and* correctness: it
must carry runtime identity, the declared v2 component weights, one timing
series per component, and the correctness guards that make the timings
comparable. This module validates that shape; it never re-times anything and
never derives expected values from a BNG3 measurement. Negative fixtures show
that malformed artifacts are refused.
"""

from __future__ import annotations

import math
from pathlib import Path

COMPONENTS = ("netgen", "ssa_batch", "ode", "out_write", "py_import", "py_load")
WEIGHTS = {
    "netgen": 0.27,
    "ssa_batch": 0.33,
    "ode": 0.15,
    "out_write": 0.10,
    "py_import": 0.08,
    "py_load": 0.07,
}
GUARDS = (
    "netgen_sha",
    "ssa_events",
    "ode_digest",
    "out_write_hashes",
    "py_load_counts",
)
META = ("git", "host", "machine", "python", "cpu_count", "reps")


def _finite_numbers(values):
    return (
        isinstance(values, list)
        and len(values) >= 3
        and all(
            isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in values
        )
    )


def validate(document: dict) -> list[str]:
    """Return publication defects; empty means the artifact is publishable."""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["document must be an object"]
    meta = document.get("meta")
    if not isinstance(meta, dict):
        return ["missing meta block"]
    for key in META:
        if key not in meta or meta[key] in (None, "", []):
            errors.append(f"meta.{key} missing")
    if not isinstance(meta.get("reps"), int) or meta["reps"] < 3:
        errors.append("meta.reps must be an integer >= 3")

    weights = meta.get("weights")
    if weights != WEIGHTS:
        errors.append("meta.weights must equal the declared v2 weight set")
    elif not math.isclose(sum(weights.values()), 1.0, rel_tol=0, abs_tol=1e-9):
        errors.append("meta.weights do not sum to 1")

    components = document.get("components")
    if not isinstance(components, dict):
        return errors + ["missing components block"]
    for name in COMPONENTS:
        row = components.get(name)
        if not isinstance(row, dict) or not _finite_numbers(row.get("reps")):
            errors.append(f"components.{name}.reps missing or non-finite")
            continue
        if len(row["reps"]) != meta.get("reps"):
            errors.append(f"components.{name}.reps count != meta.reps")
        for stat in ("min", "median", "mean", "stdev"):
            value = row.get(stat)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                errors.append(f"components.{name}.{stat} non-finite")
        if not (row["min"] <= row["median"] <= row["mean"]):
            errors.append(f"components.{name} order statistics inconsistent")

    guards = document.get("guards")
    if not isinstance(guards, dict):
        errors.append("missing guards block")
    else:
        for name in GUARDS:
            if name not in guards or guards[name] in (None, "", []):
                errors.append(f"guards.{name} missing")

    composite = document.get("composite")
    if not isinstance(composite, dict) or not _finite_numbers(composite.get("reps")):
        errors.append("composite.reps missing or non-finite")
    return errors


def validate_file(path: Path) -> list[str]:
    import json

    return validate(json.loads(path.read_text(encoding="utf-8")))
