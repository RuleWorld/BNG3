#!/usr/bin/env python3
"""Dependency inventory for the legacy compatibility paths (issue #172).

Issue #172 asks for the imports and callers of the ``modelapi``, legacy
network/parser/simulator and Cement paths to be traced and for a deliberate
compatibility adapter to be retained.  This script is the executable form of
that inventory.

It walks the live source tree, records which modules still depend on each
legacy path, and fails when the live graph drifts away from the recorded
inventory in ``provenance/architecture/legacy_dependency_inventory.json``.
The recorded inventory is therefore evidence, not prose: a path that is
retired but still imported, or a path that grows a new caller, fails the
check instead of silently widening the compatibility surface.

Usage::

    python tools/check_legacy_dependency_inventory.py            # verify
    python tools/check_legacy_dependency_inventory.py --update   # rewrite

The inventory records, for every legacy path:

``status``
    ``retired`` when the path no longer exists, ``retained`` while it is
    still needed.
``blocker``
    For a retained path, the precise reason it cannot be retired yet.
``qualified_checks``
    The checks that already cover the path's behaviour.  A path may only be
    retired when its behaviour is covered by such a check.
``dependents``
    The live modules that import (Python) or include (C++) the path,
    separated into product and test callers.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = (
    ROOT / "provenance" / "architecture" / "legacy_dependency_inventory.json"
)
PYTHON_PACKAGE_ROOT = ROOT / "python"
PYTHON_SOURCE_ROOT = ROOT / "python" / "bionetgen"
CPP_SOURCE_ROOT = ROOT / "cpp"
TEST_SOURCE_ROOT = ROOT / "tests"


def _module_name(path: Path, root: Path, prefix: str) -> str:
    """Return the importable module name of a file below ``root``."""
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if not parts:
        return prefix
    return prefix + "." + ".".join(parts)


def _python_modules(root: Path, prefix: str) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    if not root.exists():
        return modules
    for path in sorted(root.rglob("*.py")):
        modules[_module_name(path, root, prefix)] = path
    return modules


def _resolve_relative(current: str, node: ast.ImportFrom) -> str | None:
    """Resolve a relative import to an absolute module name."""
    if not node.level:
        return node.module
    parts = current.split(".")[:-1]
    ascend = node.level - 1
    if ascend:
        parts = parts[:-ascend] if ascend <= len(parts) else []
    if node.module:
        parts = parts + node.module.split(".")
    return ".".join(parts) if parts else None


def _imported_modules(path: Path, current: str) -> set[str]:
    """Return every module name imported by one Python source file."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    except SyntaxError:
        return set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative(current, node)
            if not base:
                continue
            imported.add(base)
            for alias in node.names:
                imported.add(f"{base}.{alias.name}")
    return imported


def _import_graph(modules: dict[str, Path]) -> dict[str, set[str]]:
    """Map every module to the set of module names it imports."""
    return {name: _imported_modules(path, name) for name, path in modules.items()}


def _matches_prefix(target: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        target == prefix or target.startswith(prefix + ".") for prefix in prefixes
    )


def _cpp_dependents(
    headers: list[str], sources: list[str]
) -> tuple[set[str], set[str]]:
    """Return the product and test files that include the given C++ unit."""
    header_names = {Path(item).name for item in headers}
    source_names = {Path(item).name for item in sources}
    product: set[str] = set()
    tests: set[str] = set()
    for base, bucket in ((CPP_SOURCE_ROOT, product), (TEST_SOURCE_ROOT, tests)):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in {".cpp", ".hpp", ".hh", ".h"}:
                continue
            if path.name in source_names:
                # The unit itself is not a dependent of itself.
                continue
            text = path.read_text(errors="replace")
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped.startswith("#include") or '"' not in stripped:
                    continue
                if Path(stripped.split('"')[1]).name in header_names:
                    bucket.add(path.relative_to(ROOT).as_posix())
                    break
    return product, tests


def _observed(
    entry: dict,
    product_graph: dict[str, set[str]],
    test_graph: dict[str, set[str]],
) -> dict[str, list[str]]:
    """Compute the live dependents of one inventory entry."""
    if entry["kind"] == "python":
        prefixes = tuple(entry.get("modules", ()))
        product = sorted(
            name
            for name, imported in product_graph.items()
            if not _matches_prefix(name, prefixes)
            and any(_matches_prefix(target, prefixes) for target in imported)
        )
        tests = sorted(
            name
            for name, imported in test_graph.items()
            if any(_matches_prefix(target, prefixes) for target in imported)
        )
        return {"product": product, "tests": tests}

    product, tests = _cpp_dependents(
        list(entry.get("headers", ())), list(entry.get("sources", ()))
    )
    return {"product": sorted(product), "tests": sorted(tests)}


def _path_exists(entry: dict) -> bool:
    if entry["kind"] == "python":
        for module in entry.get("modules", ()):
            base = PYTHON_PACKAGE_ROOT / Path(*module.split("."))
            # A directory that holds only a stale ``__pycache__`` is not a live
            # source path, so look for the module's own sources.
            if base.with_suffix(".py").exists():
                return True
            if base.is_dir() and any(base.glob("*.py")):
                return True
        return False
    return any(
        (ROOT / item).exists()
        for item in entry.get("headers", ()) + entry.get("sources", ())
    )


def _build(inventory: dict) -> list[tuple[dict, dict]]:
    """Pair every inventory entry with its observed live dependents."""
    product_graph = _import_graph(_python_modules(PYTHON_SOURCE_ROOT, "bionetgen"))
    test_graph = _import_graph(_python_modules(TEST_SOURCE_ROOT, "tests"))
    return [
        (entry, _observed(entry, product_graph, test_graph))
        for entry in inventory["paths"]
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite the recorded inventory from the live source tree",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=INVENTORY_PATH,
        help="the inventory file to verify or rewrite (default: the recorded one)",
    )
    arguments = parser.parse_args(argv)

    inventory_path = arguments.inventory
    if not inventory_path.exists():
        raise SystemExit(f"missing legacy dependency inventory: {inventory_path}")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    pairs = _build(inventory)

    if arguments.update:
        for entry, observed in pairs:
            entry["dependents"] = observed
        inventory_path.write_text(
            json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"updated {inventory_path}")
        return 0

    errors: list[str] = []
    for entry, observed in pairs:
        key = entry["key"]
        status = entry.get("status")
        if status not in {"retired", "retained", "migration-target"}:
            errors.append(f"{key}: unknown status {status!r}")
            continue
        recorded = entry.get("dependents") or {}
        for group in ("product", "tests"):
            if recorded.get(group, []) != observed[group]:
                errors.append(
                    f"{key}: the recorded {group} callers drifted from the live tree; "
                    f"recorded {recorded.get(group, [])}, observed {observed[group]}"
                )
        if status == "retired":
            if _path_exists(entry):
                errors.append(
                    f"{key}: the path is recorded as retired but its sources still exist"
                )
            live = observed["product"] + observed["tests"]
            if live:
                errors.append(
                    f"{key}: the path is recorded as retired but is still imported: "
                    + ", ".join(live)
                )
            continue
        if not _path_exists(entry):
            errors.append(
                f"{key}: the path is recorded as retained but its sources are missing"
            )
        if not entry.get("blocker"):
            errors.append(
                f"{key}: the path is retained without stating what blocks its retirement"
            )

    if errors:
        print("BNG3 legacy dependency inventory check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    retained = sum(1 for entry, _ in pairs if entry.get("status") == "retained")
    retired = sum(1 for entry, _ in pairs if entry.get("status") == "retired")
    targets = sum(1 for entry, _ in pairs if entry.get("status") == "migration-target")
    print(
        "BNG3 legacy dependency inventory check passed "
        f"({retained} retained, {retired} retired, {targets} migration targets)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
