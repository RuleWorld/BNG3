#!/usr/bin/env python3
"""Conservative static checks for the standalone BNG3 Lean project.

This script is NOT a replacement for `lake build`.  It exists because some
packaging/CI environments may not have Lean installed.  It catches mundane
artifact problems early: broken local imports, unbalanced delimiters/comments,
and proof placeholders.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEAN_FILES = sorted(ROOT.rglob("*.lean"))

IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z0-9_.]+)\s*$")
PLACEHOLDER_RE = re.compile(r"\b(sorry|admit)\b|^\s*axiom\b", re.MULTILINE)


def local_module_path(module: str) -> Path | None:
    if module == "BNG":
        return ROOT / "BNG.lean"
    if module.startswith("BNG."):
        return ROOT / (module.replace(".", "/") + ".lean")
    return None


def scan_balancing(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    stack: list[tuple[str, int]] = []
    comment_depth = 0
    in_string = False
    escaped = False
    i = 0
    pairs = {")": "(", "]": "[", "}": "{"}

    while i < len(text):
        c = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if comment_depth:
            if c == "/" and nxt == "-":
                comment_depth += 1
                i += 2
                continue
            if c == "-" and nxt == "/":
                comment_depth -= 1
                i += 2
                continue
            i += 1
            continue

        if in_string:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
            i += 1
            continue

        if c == "-" and nxt == "-":
            nl = text.find("\n", i + 2)
            i = len(text) if nl == -1 else nl + 1
            continue
        if c == "/" and nxt == "-":
            comment_depth = 1
            i += 2
            continue
        if c == '"':
            in_string = True
            i += 1
            continue

        if c in "([{":
            stack.append((c, i))
        elif c in ")]}":
            if not stack or stack[-1][0] != pairs[c]:
                errors.append(f"unmatched {c!r} at byte {i}")
            else:
                stack.pop()
        i += 1

    if comment_depth:
        errors.append(f"unterminated block comment (depth {comment_depth})")
    if in_string:
        errors.append("unterminated string literal")
    for opener, pos in stack:
        errors.append(f"unclosed {opener!r} opened at byte {pos}")
    return errors


def main() -> int:
    errors: list[str] = []

    for path in LEAN_FILES:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)

        for line_no, line in enumerate(text.splitlines(), 1):
            m = IMPORT_RE.match(line)
            if not m:
                continue
            local = local_module_path(m.group(1))
            if local is not None and not local.exists():
                errors.append(f"{rel}:{line_no}: missing local import {m.group(1)} -> {local}")

        for err in scan_balancing(path):
            errors.append(f"{rel}: {err}")

        # Ignore documentation prose that literally discusses placeholder names
        # by scanning only non-comment, non-Markdown Lean source approximately.
        code_lines = []
        block_depth = 0
        for line in text.splitlines():
            stripped = line.lstrip()
            if block_depth == 0 and stripped.startswith("--"):
                continue
            # This is deliberately conservative; the full balancing scanner above
            # handles nested comments. Here we only avoid obvious doc-comment text.
            if stripped.startswith("/-"):
                block_depth += stripped.count("/-") - stripped.count("-/")
                continue
            if block_depth:
                block_depth += line.count("/-") - line.count("-/")
                continue
            code_lines.append(line)
        code = "\n".join(code_lines)
        if PLACEHOLDER_RE.search(code):
            errors.append(f"{rel}: contains sorry/admit/axiom placeholder in code")

    required = [
        ROOT / "BNG" / "Runtime.lean",
        ROOT / "BNG" / "Graph.lean",
        ROOT / "BNG" / "Operational.lean",
        ROOT / "BNG" / "ExtendedOperational.lean",
        ROOT / "BNG" / "Correspondence.lean",
        ROOT / "BNG" / "MutationCompiler.lean",
        ROOT / "BNG" / "MatcherSpec.lean",
        ROOT / "BNG" / "Species.lean",
        ROOT / "BNG" / "Network.lean",
        ROOT / "BNG" / "NFnextIR.lean",
        ROOT / "BNG" / "BNGIR.lean",
        ROOT / "BNG" / "Lowering.lean",
        ROOT / "tests" / "Smoke.lean",
        ROOT / "cpp_contract" / "nfnext_contract.cpp",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")

    umbrella = (ROOT / "BNG.lean").read_text(encoding="utf-8")
    for module in (
        "BNG.Runtime", "BNG.Graph", "BNG.Operational", "BNG.ExtendedOperational",
        "BNG.Correspondence", "BNG.MutationCompiler", "BNG.MatcherSpec",
        "BNG.Species", "BNG.Network", "BNG.NFnextIR", "BNG.BNGIR", "BNG.Lowering"
    ):
        if f"import {module}" not in umbrella:
            errors.append(f"BNG.lean does not import {module}")

    if errors:
        print("STATIC VALIDATION FAILED")
        for error in errors:
            print(" -", error)
        return 1

    print(f"STATIC VALIDATION PASSED ({len(LEAN_FILES)} Lean files checked)")
    print("Reminder: this does not replace `lake build` / Lean kernel checking.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
