"""Run BNG3 compatibility contracts against a locked PyBioNetGen source tree."""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REQUIRED_SYMBOLS = {"bngmodel", "run", "sim_getter"}


def source_exports(source_root: Path) -> set[str]:
    """Collect public root imports from the source package without importing it."""

    init_path = source_root / "bionetgen" / "__init__.py"
    if not init_path.is_file():
        raise ValueError(f"PyBioNetGen package is missing: {init_path}")
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    exports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                exports.add(alias.asname or alias.name)
    return exports


def run_compatibility(source_root: Path, summary_file: Path | None = None) -> int:
    exports = source_exports(source_root)
    missing = REQUIRED_SYMBOLS - exports
    if missing:
        raise ValueError(
            "locked PyBioNetGen source no longer exports required symbols: "
            + ", ".join(sorted(missing))
        )

    env = os.environ.copy()
    env.setdefault("MPLBACKEND", "Agg")
    env.setdefault("SYMPY_USE_GMPY", "0")
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/python/test_compatibility_contract.py",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    result = subprocess.run(command, cwd=REPO, env=env, check=False)
    if summary_file:
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        with summary_file.open("a", encoding="utf-8") as stream:
            stream.write("### PyBioNetGen compatibility\n\n")
            stream.write(f"- Source checkout: `{source_root}`\n")
            stream.write(
                "- Source-derived root symbols: "
                + ", ".join(sorted(REQUIRED_SYMBOLS))
                + "\n"
            )
            stream.write(f"- Compatibility test return code: `{result.returncode}`\n\n")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--summary-file", type=Path)
    args = parser.parse_args()
    try:
        return run_compatibility(args.source_root.resolve(), args.summary_file)
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
