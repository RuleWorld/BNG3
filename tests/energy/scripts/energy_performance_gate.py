#!/usr/bin/env python3
"""Machine-readable performance promotion gate.

Input JSONs are expected to contain medians for identical benchmark cases.
No timing is done here; keeping measurement and policy separate makes the gate
reusable across CI hardware and local Rasi/uORF benchmark runners.
"""

from __future__ import annotations
import argparse, json, math
from pathlib import Path


def evaluate(base: dict, candidate: dict) -> dict:
    failures = []
    for record in (base, candidate):
        count = record["energy_reaction_classes"]
        if type(count) is not int or count <= 0:
            raise ValueError("reaction class count must be a positive integer")
    predicates = base.get("energy_predicates")
    if type(predicates) is not int or predicates < 0:
        raise ValueError("energy_predicates must be a nonnegative integer")
    if (
        "energy_predicates" in candidate
        and candidate["energy_predicates"] != predicates
    ):
        raise ValueError("benchmark predicate counts differ")
    for label, value in [
        ("baseline disabled", base["disabled_median_s"]),
        ("baseline nonenergy", base["nonenergy_median_s"]),
        ("baseline construction", base["energy_construction_median_s"]),
        ("candidate disabled", candidate["disabled_median_s"]),
        ("candidate nonenergy", candidate["nonenergy_median_s"]),
        ("candidate construction", candidate["energy_construction_median_s"]),
    ]:
        if (
            not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"{label} timing must be finite and positive")
    disabled_ratio = candidate["disabled_median_s"] / base["disabled_median_s"]
    nonenergy_ratio = candidate["nonenergy_median_s"] / base["nonenergy_median_s"]
    class_reduction = (
        base["energy_reaction_classes"] / candidate["energy_reaction_classes"]
    )
    construction_speedup = (
        base["energy_construction_median_s"] / candidate["energy_construction_median_s"]
    )
    if disabled_ratio > 1.02:
        failures.append(f"disabled overhead {disabled_ratio:.4f} > 1.02")
    if nonenergy_ratio > 1.03:
        failures.append(f"non-energy overhead {nonenergy_ratio:.4f} > 1.03")
    if int(base.get("energy_predicates", 0)) >= 6 and class_reduction < 16.0:
        failures.append(f"class reduction {class_reduction:.2f}x < 16x")
    if int(base.get("energy_predicates", 0)) >= 8 and construction_speedup < 4.0:
        failures.append(f"construction speedup {construction_speedup:.2f}x < 4x")
    return {
        "passed": not failures,
        "disabled_ratio": disabled_ratio,
        "nonenergy_ratio": nonenergy_ratio,
        "class_reduction": class_reduction,
        "construction_speedup": construction_speedup,
        "failures": failures,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("baseline", type=Path)
    p.add_argument("candidate", type=Path)
    args = p.parse_args()
    report = evaluate(
        json.loads(args.baseline.read_text()), json.loads(args.candidate.read_text())
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
