"""Source-driven coverage denominator; discovery is never proof of support.

Public Python symbols, C++ translation/header units, grammar rules, dispatched
actions, compiler features and backend enums are discovery units. Maintained
semantic claims supplement those units; they do not hide unmapped source.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import re
import warnings
from collections import Counter
from pathlib import Path

SUPPORT = {"implemented", "partial", "unsupported", "unverified"}
SOURCE_ROOTS = ("cpp", "python/bionetgen", "formal", "grammars")
MODEL_ROOTS = ("models", "tests", "examples")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_plan(root: Path, plan: dict) -> list[str]:
    errors = []
    ids = set()
    for row in plan["capabilities"]:
        if row["id"] in ids:
            errors.append(f"duplicate capability: {row['id']}")
        ids.add(row["id"])
        if row["support"] not in SUPPORT:
            errors.append(f"invalid support: {row['id']}")
        for pattern in row["sources"] + row.get("tests", []):
            if not list(root.glob(pattern.split("::")[0])):
                errors.append(f"{row['id']}: missing path {pattern}")
    suite_ids = set()
    for suite in plan["suites"]:
        if suite["id"] in suite_ids:
            errors.append(f"duplicate suite: {suite['id']}")
        suite_ids.add(suite["id"])
        for path in suite.get("tests", []):
            if not (root / path.split("::")[0]).exists():
                errors.append(f"{suite['id']}: missing test {path}")
    return errors


def discover_capabilities(root: Path, claims: list[dict]) -> list[dict]:
    rows = []
    digests = {}

    def add(identity, path, line=1, symbol=None, kind="source-unit", claim=None):
        relative = path.relative_to(root).as_posix()
        related = [
            c for c in claims if any(fnmatch.fnmatch(relative, p) for p in c["sources"])
        ]
        if path not in digests:
            digests[path] = sha256(path)
        rows.append(
            {
                "id": identity,
                "kind": kind,
                "symbol": symbol,
                "implementation": {
                    "path": relative,
                    "line": line,
                    "sha256": digests[path],
                },
                "support": claim["support"] if claim else "unverified",
                "coverage": "NOT_TESTED",
                "upstream_reference": claim.get("reference") if claim else None,
                "existing_tests": claim.get("tests", []) if claim else [],
                "candidate_claims": [c["id"] for c in related],
                "missing_tests": ["Independent semantic evidence required"],
                "issues": sorted(
                    claim.get("issues", [])
                    if claim
                    else {issue for c in related for issue in c.get("issues", [])}
                ),
                "notes": (
                    claim.get("notes", "")
                    if claim
                    else "Presence is discovery only; support and test mapping require review."
                ),
            }
        )

    for prefix in SOURCE_ROOTS:
        for path in sorted((root / prefix).rglob("*")):
            if not path.is_file() or path.suffix not in {
                ".py",
                ".cpp",
                ".hpp",
                ".h",
                ".hh",
                ".c",
                ".cu",
                ".mm",
                ".g4",
                ".lean",
            }:
                continue
            if "__pycache__" in path.parts or ".lake" in path.parts:
                continue
            name = path.relative_to(root).as_posix()
            add("source:" + name, path)
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix == ".py":
                try:
                    with warnings.catch_warnings(record=True) as diagnostics:
                        warnings.simplefilter("always", SyntaxWarning)
                        tree = ast.parse(text)
                    if diagnostics:
                        rows[-1]["discovery_diagnostics"] = [
                            str(d.message) for d in diagnostics
                        ]
                except SyntaxError:
                    rows[-1][
                        "notes"
                    ] = "Python source could not be parsed by this interpreter."
                    continue
                occurrences = Counter()

                def symbols(body, parent=""):
                    for node in body:
                        if isinstance(
                            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                        ) and not node.name.startswith("_"):
                            symbol = parent + node.name
                            occurrences[symbol] += 1
                            suffix = (
                                ""
                                if occurrences[symbol] == 1
                                else f":{occurrences[symbol]}"
                            )
                            add(
                                f"python:{name}:{symbol}{suffix}",
                                path,
                                node.lineno,
                                symbol,
                                "python-public-symbol",
                            )
                            if isinstance(node, ast.ClassDef):
                                symbols(node.body, symbol + ".")
                        elif not isinstance(
                            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                        ):
                            for field in ("body", "orelse", "finalbody", "handlers"):
                                nested = getattr(node, field, None)
                                if isinstance(nested, list):
                                    symbols(nested, parent)

                symbols(tree.body)
            if "bindings" in path.parts and path.suffix == ".cpp":
                occurrences = Counter()
                for match in re.finditer(
                    r'\.def(?:_static|_property|_readonly|_readwrite)?\s*\(\s*"([^"]+)"',
                    text,
                ):
                    occurrences[match[1]] += 1
                    add(
                        f"binding:{name}:{match[1]}:{occurrences[match[1]]}",
                        path,
                        text[: match.start()].count("\n") + 1,
                        match[1],
                        "binding",
                    )
            if path.suffix == ".lean":
                occurrences = Counter()
                for match in re.finditer(
                    r"(?m)^\s*(?:private\s+)?(theorem|lemma|axiom|def|abbrev)\s+([\w'.]+)",
                    text,
                ):
                    occurrences[match[2]] += 1
                    add(
                        f"lean:{name}:{match[2]}:{occurrences[match[2]]}",
                        path,
                        text[: match.start()].count("\n") + 1,
                        match[2],
                        "lean-declaration",
                    )
            if path.name == "ActionDispatch.cpp":
                seen = set()
                for match in re.finditer(
                    r'(?:actionName|action\.name)\s*==\s*"([\w]+)"', text
                ):
                    if match[1] not in seen:
                        seen.add(match[1])
                        add(
                            "action." + match[1],
                            path,
                            text[: match.start()].count("\n") + 1,
                            match[1],
                            "action",
                        )
            if path.suffix in {".hpp", ".h"}:
                for enum in re.finditer(
                    r"enum class (Feature|BackendKind|FiniteBackend)\b[^\{]*\{([^}]+)\}",
                    text,
                ):
                    body = re.sub(r"//[^\n]*", "", enum[2])
                    for item in body.split(","):
                        symbol = item.split("=")[0].strip()
                        if re.fullmatch(r"\w+", symbol) and symbol != "Count":
                            category = "feature" if enum[1] == "Feature" else "backend"
                            add(
                                f"{category}.{symbol}",
                                path,
                                text[: enum.start()].count("\n") + 1,
                                symbol,
                                category,
                            )
            if path.suffix == ".g4":
                for match in re.finditer(r"(?m)^([a-z]\w*)\s*:", text):
                    add(
                        f"grammar:{name}:{match[1]}",
                        path,
                        text[: match.start()].count("\n") + 1,
                        match[1],
                        "grammar-rule",
                    )
    for claim in claims:
        paths = set()
        for pattern in claim["sources"]:
            for match in root.glob(pattern):
                if match.is_file():
                    paths.add(match)
                elif match.is_dir():
                    paths.update(
                        p
                        for p in match.rglob("*")
                        if p.is_file()
                        and "__pycache__" not in p.parts
                        and ".lake" not in p.parts
                    )
        paths = sorted(paths)
        if paths:
            add(
                claim["id"],
                paths[0],
                symbol=claim["id"],
                kind="semantic-claim",
                claim=claim,
            )
            rows[-1]["implementation_paths"] = [
                p.relative_to(root).as_posix() for p in paths
            ]
    return sorted(rows, key=lambda row: row["id"])


def discover_models(root: Path, roots=MODEL_ROOTS) -> list[dict]:
    """Discover, never execute or promote, models outside locked selections.

    Hints deliberately say nothing about representability. A network-free or
    polymerizing model remains eligible for parsing without full expansion.
    """
    rows = []
    for prefix in roots:
        for path in sorted((root / prefix).rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {
                ".bngl",
                ".xml",
                ".sbml",
                ".net",
                ".json",
            }:
                continue
            if any(p in path.parts for p in ("evidence", "golden", "__pycache__")):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix == ".json" and "bngir" not in path.as_posix().lower():
                continue
            hints = []
            for pattern, label in (
                (r"simulate_nf|method\s*=>\s*['\"]nf", "network-free"),
                (r"compartments", "compartments"),
                (r"energy patterns", "energy"),
                (r"\blocal", "local-functions"),
                (r"<sbml\b", "sbml"),
                (r"multi:", "sbml-multi"),
            ):
                if re.search(pattern, text, re.I):
                    hints.append(label)
            rows.append(
                {
                    "id": path.relative_to(root).as_posix(),
                    "sha256": sha256(path),
                    "format": path.suffix[1:],
                    "bytes": path.stat().st_size,
                    "capability_hints": hints,
                    "classification_confidence": "lexical-hint",
                    "execution_policy": "stage-only",
                    "estimated_cost": "unknown",
                    "applicable_stages": (
                        ["parse"] if path.suffix == ".bngl" else ["format-inspection"]
                    ),
                }
            )
    return rows
