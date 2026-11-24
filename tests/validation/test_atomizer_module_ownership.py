"""Architecture check: one owning module per named Atomizer transformation.

This is a structural contract, not a scientific result. For each semantic
transformation named in #164, exactly one module under
``python/bionetgen/atomizer/modern`` defines its public entry point, and the
public re-export, when present, resolves to that same object. Duplicate
top-level definitions are rejected so a parallel implementation cannot appear
silently. The check deliberately makes no claim about logic that is not behind
one of these named entry points.
"""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

import pytest

MODERN = Path(__file__).resolve().parents[2] / "python/bionetgen/atomizer/modern"

# transformation -> (owning module, public entry point)
OWNERSHIP = {
    "source-parsing": ("parser", "SBMLParser"),
    "structural-mapping": ("core", "infer_modification"),
    "feature-checks": ("writer", "check_mass_action"),
    "event-planning": ("events", "EventTranslationContext"),
    "fast-reaction-lowering": ("fast_reactions", "lower_fast_reactions"),
    "unit-lowering": ("units", "resolve_unit_factor"),
    "text-emission": ("writer", "generate_bngl"),
    "multi-structures": ("multi", "parse_multi_package"),
    "rate-rule-seam": ("rate_rule_constants", "RATE_RULE_NEG_PREFIX"),
}


def _top_level_definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_atomizer_transformation_ownership():
    definitions = {
        path.stem: _top_level_definitions(path)
        for path in sorted(MODERN.glob("*.py"))
        if path.name != "__init__.py"
    }
    package = import_module("bionetgen.atomizer.modern")
    failures: list[str] = []
    for transformation, (module_name, entry) in OWNERSHIP.items():
        owner = import_module(f"bionetgen.atomizer.modern.{module_name}")
        if not hasattr(owner, entry):
            failures.append(f"{transformation}: {module_name} has no {entry}")
            continue
        definers = sorted(name for name, names in definitions.items() if entry in names)
        if definers != [module_name]:
            failures.append(
                f"{transformation}: {entry} defined in {definers}, expected [{module_name!r}]"
            )
        obj = getattr(owner, entry)
        public = getattr(package, entry, None)
        if public is not None and public is not obj:
            failures.append(
                f"{transformation}: public {entry} does not resolve to owner"
            )
    assert not failures, "; ".join(failures)


@pytest.mark.parametrize("transformation", sorted(OWNERSHIP))
def test_owned_entry_point_is_importable(transformation):
    module_name, entry = OWNERSHIP[transformation]
    owner = import_module(f"bionetgen.atomizer.modern.{module_name}")
    assert hasattr(owner, entry)
