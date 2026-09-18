#!/usr/bin/env python3
"""Fail when backend-independent/lowered layers acquire forbidden source dependencies.

This is intentionally a ratchet rather than a claim that every legacy execution
path has already migrated. Existing AST-facing compatibility files are listed in
``provenance/architecture/ast_compat_allowlist.txt``. New files are not allowed
to join that list implicitly.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "provenance" / "architecture" / "ast_compat_allowlist.txt"
INCLUDE_RE = re.compile(
    r'^\s*#\s*include\s*[<"]((?:ast|parser)/[^>"]+)[>"]', re.MULTILINE
)
REPARSE_PATTERNS = (
    re.compile(r"\bPattern::parse\s*\("),
    re.compile(r"\bBNGLexer\b"),
    re.compile(r"\bBNGParser\b"),
    re.compile(r"\bparse_string\b"),
)


def load_allowlist() -> set[str]:
    entries: set[str] = set()
    if not ALLOWLIST_PATH.exists():
        return entries
    for line in ALLOWLIST_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.add(line)
    return entries


def source_files() -> list[Path]:
    roots = [
        ROOT / "cpp" / name for name in ("engine", "io", "actions", "nfsim", "nfnext")
    ]
    result: list[Path] = []
    for base in roots:
        if not base.exists():
            continue
        result.extend(
            path
            for path in base.rglob("*")
            if path.suffix in {".cpp", ".hpp", ".hh", ".h"}
        )
    return sorted(result)


def is_strict(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return (
        rel.startswith("cpp/nfnext/")
        or "FromCompiled" in path.name
        or "from_bng" in path.name
        or "NetworkPlan" in path.name
    )


def main() -> int:
    allow = load_allowlist()
    errors: list[str] = []
    observed_legacy: set[str] = set()

    for path in source_files():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(errors="replace")
        forbidden_includes = INCLUDE_RE.findall(text)
        if forbidden_includes:
            if is_strict(path):
                errors.append(
                    f"{rel}: strict compiled/backend layer includes source-layer header(s): {', '.join(forbidden_includes)}"
                )
            elif rel not in allow:
                errors.append(
                    f"{rel}: new AST/parser dependency is not in the explicit compatibility allowlist"
                )
            else:
                observed_legacy.add(rel)

        if is_strict(path):
            reparsers = [
                pattern.pattern for pattern in REPARSE_PATTERNS if pattern.search(text)
            ]
            # The compile -> NFIR adapter may refer to Pattern values, but must never
            # reparse text or instantiate the BNGL parser.
            if reparsers:
                errors.append(
                    f"{rel}: strict compiled/backend layer contains source reparse marker(s): {', '.join(reparsers)}"
                )

    stale = sorted(allow - observed_legacy)
    if stale:
        errors.append(
            "compatibility allowlist contains stale entries (remove them as files migrate): "
            + ", ".join(stale)
        )

    if errors:
        print("BNG3 architecture dependency check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(
        f"BNG3 architecture dependency check passed ({len(observed_legacy)} explicit compatibility files)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
