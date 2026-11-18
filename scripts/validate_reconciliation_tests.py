#!/usr/bin/env python3
"""Check that reconciliation-ledger test references still resolve locally.

The ledgers deliberately allow empty ``tests`` arrays: those are visible
evidence gaps, not claims that this validator may fill. Populated references
are checked against Python test nodes, Catch2 test names, or CTest target names
so renames cannot silently leave stale provenance behind.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PureWindowsPath
from typing import Any

REPO = Path(__file__).resolve().parents[1]
LEDGER_DIR = REPO / "provenance" / "reconciliation"
CLAIM_CLASSIFICATIONS = {
    "incorporated-identically",
    "incorporated-equivalently",
    "superseded-by-bng3",
}


def _python_node_exists(source: str, node_path: list[str]) -> bool:
    if not node_path or not node_path[-1].startswith("test_"):
        return False
    try:
        nodes = ast.parse(source).body
    except SyntaxError:
        return False
    for index, name in enumerate(node_path):
        match = next(
            (
                node
                for node in nodes
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
                and node.name == name
            ),
            None,
        )
        if match is None:
            return False
        if index < len(node_path) - 1 and not isinstance(match, ast.ClassDef):
            return False
        nodes = getattr(match, "body", [])
    return True


def _source_tokens(source: str, *, cmake: bool = False) -> list[tuple[str, str]]:
    """Tokenize identifiers, punctuation, and quoted strings; discard comments."""
    tokens = []
    index = 0

    def bracket_argument_end(start: int) -> tuple[str, int] | None:
        if start >= len(source) or source[start] != "[":
            return None
        cursor = start + 1
        while cursor < len(source) and source[cursor] == "=":
            cursor += 1
        if cursor >= len(source) or source[cursor] != "[":
            return None
        delimiter = "]" + source[start + 1 : cursor] + "]"
        content_start = cursor + 1
        end = source.find(delimiter, content_start)
        if end < 0:
            return source[content_start:], len(source)
        return source[content_start:end], end + len(delimiter)

    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if cmake and char == "#":
            bracket = bracket_argument_end(index + 1)
            if bracket is not None:
                _, index = bracket
                continue
            end = source.find("\n", index)
            index = len(source) if end < 0 else end + 1
            continue
        if not cmake and source.startswith("//", index):
            end = source.find("\n", index)
            index = len(source) if end < 0 else end + 1
            continue
        if not cmake and source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        if char == '"' or not cmake and char == "'":
            quote = char
            index += 1
            value = []
            while index < len(source):
                if source[index] == "\\" and index + 1 < len(source):
                    value.append(source[index + 1])
                    index += 2
                elif source[index] == quote:
                    index += 1
                    break
                else:
                    value.append(source[index])
                    index += 1
            tokens.append(("string", "".join(value)))
            continue
        if cmake and char == "[":
            bracket = bracket_argument_end(index)
            if bracket is not None:
                value, index = bracket
                tokens.append(("string", value))
                continue
        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < len(source) and (
                source[index].isalnum() or source[index] == "_"
            ):
                index += 1
            tokens.append(("identifier", source[start:index]))
            continue
        tokens.append(("punctuation", char))
        index += 1
    return tokens


def _catch2_test_names(source: str) -> set[str]:
    tokens = _source_tokens(source)
    names = set()
    for index in range(len(tokens) - 2):
        if (
            tokens[index] == ("identifier", "TEST_CASE")
            and tokens[index + 1] == ("punctuation", "(")
            and tokens[index + 2][0] == "string"
        ):
            names.add(tokens[index + 2][1])
    return names


def _cmake_test_names(source: str) -> set[str]:
    tokens = _source_tokens(source, cmake=True)
    names = set()
    for index in range(len(tokens) - 1):
        if tokens[index] != ("identifier", "add_test") or tokens[index + 1] != (
            "punctuation",
            "(",
        ):
            continue
        depth = 1
        command = []
        for kind, value in tokens[index + 2 :]:
            if kind == "punctuation" and value == "(":
                depth += 1
            elif kind == "punctuation" and value == ")":
                depth -= 1
                if depth == 0:
                    break
            command.append((kind, value))
        for token_index, token in enumerate(command[:-1]):
            if token == ("identifier", "NAME"):
                kind, value = command[token_index + 1]
                if kind in {"identifier", "string"}:
                    names.add(value)
    return names


def resolve_test_reference(reference: str, repository_root: Path = REPO) -> str | None:
    """Return a diagnostic when an exact source test reference is stale."""
    if not isinstance(reference, str) or "::" not in reference:
        return "expected a repository-relative path followed by :: and a test name"
    raw_path, raw_node = reference.split("::", 1)
    if not raw_path or not raw_node:
        return "path and test name must both be non-empty"
    if Path(raw_path).is_absolute() or PureWindowsPath(raw_path).is_absolute():
        return "test reference path must be repository-relative"
    root = repository_root.resolve()
    path = (root / raw_path).resolve()
    if not path.is_relative_to(root):
        return "test reference escapes the repository root"
    if not path.is_file():
        return f"referenced test file does not exist: {raw_path}"

    if path.suffix == ".py":
        if not _python_node_exists(
            path.read_text(encoding="utf-8"), raw_node.split("::")
        ):
            return f"Python test node does not exist: {raw_node}"
        return None

    if path.suffix == ".cpp":
        if raw_node in _catch2_test_names(path.read_text(encoding="utf-8")):
            return None
        return f"Catch2 test case does not exist: {raw_node}"

    if path.name == "CMakeLists.txt":
        if raw_node in _cmake_test_names(path.read_text(encoding="utf-8")):
            return None
        return f"CTest target does not exist: {raw_node}"

    return f"unsupported test-reference file type: {path.suffix or '<none>'}"


def load_ledgers(directory: Path = LEDGER_DIR) -> list[tuple[Path, dict[str, Any]]]:
    ledgers = []
    for path in sorted(directory.glob("*.yml")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"cannot read reconciliation ledger {path}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise ValueError(f"reconciliation ledger root must be an object: {path}")
        ledgers.append((path, value))
    return ledgers


def evidence_inventory(
    ledgers: list[tuple[Path, dict[str, Any]]],
) -> dict[str, dict[str, int]]:
    """Count claims with and without test references without grading empty lists."""
    inventory = {}
    for path, ledger in ledgers:
        claims = [
            entry
            for entry in ledger.get("entries", [])
            if isinstance(entry, dict)
            and entry.get("classification") in CLAIM_CLASSIFICATIONS
        ]
        inventory[str(ledger.get("source", path.stem))] = {
            "claims": len(claims),
            "claims_with_test_refs": sum(bool(entry.get("tests")) for entry in claims),
            "claims_without_test_refs": sum(not entry.get("tests") for entry in claims),
            "test_references": sum(len(entry.get("tests") or []) for entry in claims),
        }
    return inventory


def validate_test_references(
    ledgers: list[tuple[Path, dict[str, Any]]], repository_root: Path = REPO
) -> list[str]:
    errors = []
    for path, ledger in ledgers:
        for index, entry in enumerate(ledger.get("entries", [])):
            if not isinstance(entry, dict):
                continue
            for reference in entry.get("tests", []) or []:
                issue = resolve_test_reference(reference, repository_root)
                if issue:
                    errors.append(
                        f"{path.name}: entries[{index}] {entry.get('source_revision')}: "
                        f"{reference!r}: {issue}"
                    )
    return errors


def audit_upstream_history(
    checkout: Path, ledger: dict[str, Any], accepted_revision: str
) -> dict[str, Any]:
    """Compare ledger commit coverage with the full pinned Git ancestry range."""

    def git_bytes(*args: str) -> bytes:
        return subprocess.run(
            ["git", "--no-replace-objects", "-C", str(checkout), *args],
            capture_output=True,
            check=True,
        ).stdout

    def git(*args: str) -> str:
        return git_bytes(*args).decode().strip()

    represented_revision = ledger["represented_revision"]
    errors: list[str] = []
    fixture_hashes: dict[str, str] = {}
    report = {
        "accepted_revision": accepted_revision,
        "represented_revision": represented_revision,
        "checkout_revision": None,
        "commits": [],
        "missing_commits": [],
        "unexpected_commits": [],
        "fixture_sha256": fixture_hashes,
        "errors": errors,
    }
    if ledger["cutoff_revision"] != accepted_revision:
        errors.append("ledger cutoff does not match the accepted revision")
    try:
        if Path(git("rev-parse", "--show-toplevel")).resolve() != checkout.resolve():
            errors.append("path is not the root of the upstream checkout")
            return report
        report["checkout_revision"] = git("rev-parse", "HEAD")
        if report["checkout_revision"] != accepted_revision:
            errors.append("checkout HEAD does not match the accepted revision")
        if git("status", "--porcelain=v1", "--untracked-files=all"):
            errors.append("checkout has local changes")
        if git("rev-parse", "--is-shallow-repository") != "false":
            errors.append("checkout has shallow history")
            return report
        git("merge-base", "--is-ancestor", represented_revision, accepted_revision)
        commits = set(
            git("rev-list", f"{represented_revision}..{accepted_revision}").splitlines()
        )
        ledger_commits = {entry["source_revision"] for entry in ledger["entries"]}
        report["commits"] = sorted(commits)
        report["missing_commits"] = sorted(commits - ledger_commits)
        report["unexpected_commits"] = sorted(ledger_commits - commits)
        fixtures = (
            git_bytes(
                "diff",
                "--name-only",
                "--no-renames",
                "--diff-filter=AM",
                "-z",
                represented_revision,
                accepted_revision,
                "--",
                "*.bngl",
                "*.net",
                "*.xml",
            )
            .decode()
            .split("\0")
        )
        for relative in filter(None, fixtures):
            path = checkout.resolve() / relative
            if path.resolve() != path or not path.is_file():
                errors.append(f"fixture is not a regular checkout file: {relative}")
                continue
            data = path.read_bytes()
            if data != git_bytes("cat-file", "blob", f"{accepted_revision}:{relative}"):
                errors.append(f"fixture differs from the accepted revision: {relative}")
                continue
            fixture_hashes[relative] = hashlib.sha256(data).hexdigest()
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = (
            exc.stderr.decode(errors="replace").strip()
            if isinstance(exc, subprocess.CalledProcessError)
            else str(exc)
        )
        errors.append(
            f"cannot establish upstream history: {exc}"
            + (f": {detail}" if detail else "")
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bionetgen", type=Path)
    parser.add_argument("--nfsim", type=Path)
    parser.add_argument("--pybionetgen", type=Path)
    parser.add_argument("--history-report", type=Path)
    args = parser.parse_args()
    sources = {
        name: getattr(args, name) for name in ("bionetgen", "nfsim", "pybionetgen")
    }
    verify_history = any(sources.values()) or args.history_report is not None
    if verify_history and not (all(sources.values()) and args.history_report):
        parser.error(
            "history audit requires all three source paths and --history-report"
        )
    try:
        ledgers = load_ledgers()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    inventory = evidence_inventory(ledgers)
    errors = validate_test_references(ledgers)
    for source, counts in inventory.items():
        print(
            f"{source}: {counts['claims']} incorporated/superseded claim entries; "
            f"{counts['claims_with_test_refs']} with test references; "
            f"{counts['claims_without_test_refs']} without; "
            f"{counts['test_references']} references checked"
        )
    if verify_history:
        lock = json.loads(
            (REPO / "provenance" / "upstreams.lock.yml").read_text(encoding="utf-8")
        )
        history = {}
        for _, ledger in ledgers:
            source = ledger["source"]
            if source not in sources or source in history:
                errors.append(f"unexpected or duplicate source ledger: {source}")
                continue
            audit = audit_upstream_history(
                sources[source], ledger, lock["sources"][source]["revision"]
            )
            history[source] = audit
            errors.extend(f"{source}: {error}" for error in audit["errors"])
            errors.extend(
                f"{source}: missing ledger commit {sha}"
                for sha in audit["missing_commits"]
            )
            errors.extend(
                f"{source}: out-of-range ledger commit {sha}"
                for sha in audit["unexpected_commits"]
            )
        errors.extend(
            f"missing ledger for {name}"
            for name in sorted(sources.keys() - history.keys())
        )
        args.history_report.parent.mkdir(parents=True, exist_ok=True)
        args.history_report.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "audit": "upstream-history-and-fixtures",
                    "bng3_revision": subprocess.check_output(
                        ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
                    ).strip(),
                    "sources": history,
                    "errors": errors,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(
            f"reconciliation validation failed ({len(errors)} error(s))",
            file=sys.stderr,
        )
        return 1
    print("reconciliation test references resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
