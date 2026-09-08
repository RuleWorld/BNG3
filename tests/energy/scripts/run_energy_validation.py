#!/usr/bin/env python3
"""Small orchestration wrapper for local/CI energy validation."""

from __future__ import annotations
import argparse, json, subprocess, sys, os
from pathlib import Path


def run(cmd: list[str]) -> dict:
    p = subprocess.run(cmd, text=True, capture_output=True)
    return {
        "command": cmd,
        "returncode": p.returncode,
        "stdout": p.stdout,
        "stderr": p.stderr,
        "passed": p.returncode == 0,
    }


def run_ctest(build: Path, label: str) -> dict:
    return run(
        [
            "ctest",
            "--test-dir",
            str(build),
            "--output-on-failure",
            "--no-tests=error",
            "-L",
            "^" + label + "$",
        ]
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--source", type=Path, default=Path("."))
    ap.add_argument("--future", action="store_true")
    ap.add_argument("--python-only", action="store_true")
    args = ap.parse_args()
    os.environ["PYTHONPATH"] = str(args.source.resolve() / "tests/energy")
    results = []
    if not args.python_only:
        results.append(run_ctest(args.build, "energy"))
        if args.future:
            results.append(run_ctest(args.build, "energy-future"))
    results.append(
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                str(args.source / "tests/energy/tests/python"),
            ]
        )
    )
    report = {"passed": all(r["passed"] for r in results), "steps": results}
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
