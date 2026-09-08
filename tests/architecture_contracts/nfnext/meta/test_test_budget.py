#!/usr/bin/env python3
"""Meta-test: keep NFnext test code at least 1.5x production C++ LOC.

The metric intentionally excludes generated files, benchmark drivers, docs, and
CMake. It counts nonblank/non-comment physical lines in include/src versus tests.
Future-contract tests count because they are executable specifications written
before implementation, exactly as required by the TDD policy.
"""
from __future__ import annotations
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
MIN_RATIO = 1.5
SUFFIXES = {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h"}


def files_under(*parts: str):
    base = ROOT.joinpath(*parts)
    for p in base.rglob("*"):
        if p.is_file() and p.suffix in SUFFIXES:
            yield p


def logicalish_loc(path: Path) -> int:
    count = 0
    in_block = False
    for raw in path.read_text(errors="replace").splitlines():
        s = raw.strip()
        if not s:
            continue
        if in_block:
            if "*/" in s:
                in_block = False
                s = s.split("*/", 1)[1].strip()
                if not s:
                    continue
            else:
                continue
        if s.startswith("/*"):
            if "*/" not in s[2:]:
                in_block = True
            continue
        if s.startswith("//"):
            continue
        count += 1
    return count


def main() -> int:
    prod = list(files_under("src")) + list(files_under("include"))
    tests = list(files_under("tests"))
    prod_loc = sum(logicalish_loc(p) for p in prod)
    test_loc = sum(logicalish_loc(p) for p in tests)
    ratio = float("inf") if prod_loc == 0 else test_loc / prod_loc
    print(f"production_loc={prod_loc}")
    print(f"test_loc={test_loc}")
    print(f"test_to_production_ratio={ratio:.3f}")
    print(f"required_ratio={MIN_RATIO:.3f}")
    if ratio < MIN_RATIO:
        print("FAIL: NFnext test budget fell below required 1.5x", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
