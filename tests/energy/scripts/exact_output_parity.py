#!/usr/bin/env python3
"""Exact file/trajectory parity gate for cases expected to preserve RNG structure."""

from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compare(a: Path, b: Path) -> dict:
    ha, hb = sha256(a), sha256(b)
    return {
        "passed": ha == hb,
        "a": str(a),
        "b": str(b),
        "sha256_a": ha,
        "sha256_b": hb,
        "size_a": a.stat().st_size,
        "size_b": b.stat().st_size,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("a", type=Path)
    p.add_argument("b", type=Path)
    args = p.parse_args()
    r = compare(args.a, args.b)
    print(json.dumps(r, indent=2))
    return 0 if r["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
