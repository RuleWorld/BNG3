#!/usr/bin/env python3
"""Compare BNG/NFsim-style whitespace or CSV numeric tables by named column."""

from __future__ import annotations
import argparse, csv, json, math, re
from pathlib import Path


def load_table(path: Path) -> tuple[list[str], list[list[float]]]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            candidate = line[1:].strip()
            first = re.split(r"[,\s]+", candidate)[0].lower()
            if not lines and first == "time":
                lines.append(candidate)
            continue
        lines.append(line)
    if not lines:
        raise ValueError(f"{path}: empty table")
    split = (
        (lambda s: [x.strip() for x in s.split(",")])
        if "," in lines[0]
        else (lambda s: s.split())
    )
    header = split(lines[0])
    if (
        not header
        or header[0].lower() != "time"
        or len(set(header)) != len(header)
        or any(not x for x in header)
    ):
        raise ValueError(f"{path}: expected unique named columns beginning with time")
    rows = []
    for i, line in enumerate(lines[1:], 2):
        fields = split(line)
        if len(fields) != len(header):
            raise ValueError(
                f"{path}:{i}: expected {len(header)} columns, got {len(fields)}"
            )
        rows.append([float(x) for x in fields])
    if not rows:
        raise ValueError(f"{path}: table has no data rows")
    return header, rows


def compare(a: Path, b: Path, atol: float = 0.0, rtol: float = 0.0) -> dict:
    if any(not math.isfinite(x) or x < 0 for x in (atol, rtol)):
        raise ValueError("tolerances must be finite and nonnegative")
    ha, ra = load_table(a)
    hb, rb = load_table(b)
    failures = []
    if ha != hb:
        failures.append({"kind": "header", "a": ha, "b": hb})
        return {"passed": False, "failures": failures}
    if len(ra) != len(rb):
        failures.append({"kind": "row_count", "a": len(ra), "b": len(rb)})
        return {"passed": False, "failures": failures}
    max_abs = 0.0
    max_rel = 0.0
    for i, (xa, xb) in enumerate(zip(ra, rb)):
        for j, (va, vb) in enumerate(zip(xa, xb)):
            if not math.isfinite(va) or not math.isfinite(vb):
                failures.append(
                    {"kind": "nonfinite", "row": i, "column": ha[j], "a": va, "b": vb}
                )
                continue
            diff = abs(va - vb)
            scale = max(abs(va), abs(vb))
            rel = diff / scale if scale else 0.0
            max_abs = max(max_abs, diff)
            max_rel = max(max_rel, rel)
            if diff > atol + rtol * scale:
                failures.append(
                    {
                        "kind": "value",
                        "row": i,
                        "column": ha[j],
                        "a": va,
                        "b": vb,
                        "abs": diff,
                        "rel": rel,
                    }
                )
                if len(failures) >= 100:
                    break
        if len(failures) >= 100:
            break
    return {
        "passed": not failures,
        "rows": len(ra),
        "columns": ha,
        "max_abs": max_abs,
        "max_rel": max_rel,
        "failures": failures,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("a", type=Path)
    p.add_argument("b", type=Path)
    p.add_argument("--atol", type=float, default=0)
    p.add_argument("--rtol", type=float, default=0)
    x = p.parse_args()
    r = compare(x.a, x.b, x.atol, x.rtol)
    print(json.dumps(r, indent=2))
    return 0 if r["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
