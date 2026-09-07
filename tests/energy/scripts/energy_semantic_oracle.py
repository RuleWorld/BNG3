#!/usr/bin/env python3
"""Backend-independent literal oracle for local energy plans."""

from __future__ import annotations
import argparse, json, math
from pathlib import Path


def delta_g(base: float, mask: int, terms: list[dict]) -> float:
    value = float(base)
    for term in terms:
        req = int(term["mask"])
        if req <= 0:
            raise ValueError("term mask must be positive")
        if mask & req == req:
            value += float(term["energy"])
    return value


def arrhenius(delta: float, phi: float, rt: float, forward: bool) -> float:
    if not math.isfinite(rt) or rt <= 0:
        raise ValueError("RT must be finite and positive")
    slope = phi if forward else phi - 1.0
    return math.exp(-slope * delta / rt)


def enumerate_plan(case: dict) -> list[dict]:
    n = int(case["condition_count"])
    if n < 0 or n > 20:
        raise ValueError("oracle enumeration capped at 20 conditions")
    rows = []
    for mask in range(1 << n):
        dg = delta_g(case.get("base", 0.0), mask, case.get("terms", []))
        rows.append(
            {
                "mask": mask,
                "delta_g": dg,
                "forward_factor": arrhenius(dg, case["phi"], case["RT"], True),
                "reverse_factor": arrhenius(dg, case["phi"], case["RT"], False),
            }
        )
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("case", type=Path)
    args = p.parse_args()
    case = json.loads(args.case.read_text(encoding="utf-8"))
    print(json.dumps(enumerate_plan(case), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
