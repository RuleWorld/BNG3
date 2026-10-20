#!/usr/bin/env python3
"""Check that changed Python files work on the repository's Python floor.

The CI matrix in ``.github/workflows/ci.yml`` runs the Python test suite on
every supported interpreter, starting at the package floor declared by
``requires-python`` in ``pyproject.toml``.  A pull request that only changes
Python code therefore only needs the matrix for one thing: a construct that
the floor interpreter can neither parse nor evaluate.

This script establishes that fact locally, in seconds, without waiting for a
saturated runner pool.  It is a *static* analysis of the changed files, not a
re-implementation of the matrix:

* each file is parsed with the floor interpreter's grammar, so syntax that
  the floor rejects is reported;
* the parsed tree is scanned for standard-library and builtin constructs that
  the floor does not provide;
* annotations are only treated as runtime-evaluated when the module does not
  defer them with ``from __future__ import annotations``.

A file that an interpreter cannot parse is not compatible with the floor
either: it needs an interpreter newer than the one that refused it.  The
verdict is the same on every host, whether the host reads the file or not;
only the precision differs, because a host that cannot read the file cannot
name the release that provides the construct.

A static check cannot prove runtime behaviour, so the script states what it
did not check instead of claiming success.  When it cannot establish
compatibility at all -- an unreadable file, a missing ``requires-python``, a
floor the CI matrix does not exercise -- it fails rather than passes.

Usage::

    python scripts/ci/check_python_floor.py --base origin/main
    python scripts/ci/check_python_floor.py --files a.py b.py
    python scripts/ci/check_python_floor.py            # whole repository
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The directory roots that the repository's ruff gate covers.  The whole
#: repository is the default scope so an ungated file is still checked.
LINT_SCOPE_ROOTS = ("python", "tests", "scripts", "formal")

#: ``requires-python`` in ``pyproject.toml`` is the authoritative floor.
REQUIRES_PYTHON_RE = re.compile(r"requires-python\s*=\s*[\"']>=\s*(\d+)\.(\d+)[\"']")

#: The interpreter matrix of the ``python-test`` job in ``.github/workflows``.
WORKFLOW_MATRIX_RE = re.compile(r"python-version:\s*\[([^\]]*)\]")

#: CPython reports a too-new syntax requirement in this shape.
SYNTAX_VERSION_RE = re.compile(r"only supported in Python (\d+)\.(\d+) and greater")

Version = Tuple[int, int]

#: The parser the check uses.  It takes the source, the file name and an
#: optional feature version, like ``ast.parse``.
Parser = Callable[..., ast.AST]

#: Syntax constructs and the first CPython release that accepts them.  The
#: node names are looked up on ``ast`` at run time because the script itself
#: has to run on the floor, where the newer node types do not exist yet.
SYNTAX_NODES = (
    ("match statement", "Match", (3, 10)),
    ("except* handler (exception groups)", "TryStar", (3, 11)),
    ("type alias statement (PEP 695)", "TypeAlias", (3, 12)),
    ("type parameter syntax (PEP 695)", "TypeVar", (3, 12)),
    ("type parameter syntax (PEP 695)", "ParamSpec", (3, 12)),
    ("type parameter syntax (PEP 695)", "TypeVarTuple", (3, 12)),
)

#: Standard-library modules and module attributes and the first CPython
#: release that provides them.
STDLIB_MINIMUM = {
    "graphlib": (3, 9),
    "zoneinfo": (3, 9),
    "tomllib": (3, 11),
    "itertools.pairwise": (3, 10),
    "typing.TypeAlias": (3, 10),
    "typing.ParamSpec": (3, 10),
    "typing.Concatenate": (3, 10),
    "typing.TypeGuard": (3, 10),
    "typing.Self": (3, 11),
    "typing.Never": (3, 11),
    "typing.LiteralString": (3, 11),
    "typing.Required": (3, 11),
    "typing.NotRequired": (3, 11),
    "typing.TypeAliasType": (3, 12),
    "typing.Unpack": (3, 12),
    "typing.override": (3, 12),
    "typing.ReadOnly": (3, 13),
    "datetime.UTC": (3, 11),
    "asyncio.timeout": (3, 11),
    "sys.orig_argv": (3, 10),
}

#: Builtin functions and classes and the first CPython release that provides
#: them.
BUILTIN_MINIMUM = {
    "aiter": (3, 10),
    "anext": (3, 10),
    "EncodingWarning": (3, 10),
    "ExceptionGroup": (3, 11),
    "BaseExceptionGroup": (3, 11),
    "PythonFinalizationError": (3, 13),
}

#: Method names that only exist on a builtin type and are distinctive enough
#: to match without knowing the receiver's type.
METHOD_MINIMUM_ANYWHERE = {
    "removeprefix": (3, 9),
    "removesuffix": (3, 9),
}

#: Method names that need a receiver whose type is known to be a builtin.
METHOD_MINIMUM_TYPED = {
    "bit_count": (3, 10),
    "pairget": (3, 10),
}

#: Types whose ``__getitem__`` was genericised by PEP 585.
PEP585_BUILTINS = frozenset({"list", "dict", "set", "tuple", "frozenset", "type"})

#: Names that denote a type in a PEP 604 union.
BUILTIN_TYPE_NAMES = frozenset(
    {
        "bool",
        "bytearray",
        "bytes",
        "complex",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "memoryview",
        "object",
        "set",
        "str",
        "tuple",
        "type",
    }
)

#: Constructors whose result is a builtin instance.
BUILTIN_CONSTRUCTORS = frozenset(
    {
        "bool",
        "bytes",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "set",
        "str",
        "tuple",
    }
)

#: What this check deliberately does not establish.
LIMITATIONS = (
    "The check is static: it never executes the file, so it cannot detect a "
    "failure that depends on data, on a third-party package, or on the "
    "operating system.",
    "Annotations written as string literals are not evaluated when the module "
    "is defined and are therefore not analysed; typing.get_type_hints() would "
    "evaluate them.",
    "Only the constructs listed in this script's tables are covered. A "
    "construct added to a later revision of the tables is not detected by an "
    "earlier run of the script.",
    "When the interpreter running the check cannot read a file, the report "
    "names that interpreter as the lower bound of what the file needs, not "
    "the exact release that provides the construct: only an interpreter that "
    "can read the file can name it.",
)


class CannotEstablish(Exception):
    """Raised when the check cannot establish compatibility at all."""


@dataclass(frozen=True)
class Finding:
    """One construct that the floor interpreter does not provide.

    ``minimum`` is the first release that provides the construct, when that
    release is known.  ``rejected_by`` is the interpreter whose own parser
    refused the file, when the construct could not be identified: a file that
    an interpreter cannot parse is not floor-compatible either, and the
    interpreter that refused it is the lower bound of what the file needs.
    """

    path: str
    line: int
    column: int
    feature: str
    minimum: Optional[Version]
    detail: str
    rejected_by: Optional[Version] = None
    rejected_by_role: str = ""

    def render(self) -> str:
        location = f"{self.path}:{self.line}:{self.column}: "
        if self.minimum is not None:
            return (
                f"{location}requires Python >= {format_version(self.minimum)}: "
                f"{self.feature} ({self.detail})"
            )
        if self.rejected_by is not None:
            return (
                f"{location}does not parse under Python "
                f"{format_version(self.rejected_by)} (the {self.rejected_by_role} "
                f"interpreter): the file requires a newer interpreter "
                f"({self.detail})"
            )
        return f"{location}{self.feature} ({self.detail})"

    def requires_newer_interpreter(self) -> bool:
        """Return True when the file needs an interpreter newer than the floor."""
        return self.minimum is not None or self.rejected_by is not None


def format_version(version: Version) -> str:
    return f"{version[0]}.{version[1]}"


def host_version() -> Version:
    """Return the version of the interpreter that runs the check."""
    return sys.version_info[0], sys.version_info[1]


def parse_version(text: str) -> Version:
    match = re.fullmatch(r"(\d+)\.(\d+)", text.strip())
    if match is None:
        raise CannotEstablish(f"not a Python version: {text!r}")
    return int(match.group(1)), int(match.group(2))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise CannotEstablish(f"cannot read {path}: {error}") from error


def floor_from_pyproject(root: Path) -> Version:
    """Return the floor declared by ``requires-python`` in ``pyproject.toml``."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise CannotEstablish(f"no pyproject.toml under {root}")
    match = REQUIRES_PYTHON_RE.search(read_text(pyproject))
    if match is None:
        raise CannotEstablish(f"cannot read a requires-python floor from {pyproject}")
    return int(match.group(1)), int(match.group(2))


def matrix_versions_from_workflow(root: Path) -> Optional[List[Version]]:
    """Return the interpreter versions of the CI matrix, or None if absent."""
    workflow = root / ".github" / "workflows" / "ci.yml"
    if not workflow.is_file():
        return None
    match = WORKFLOW_MATRIX_RE.search(read_text(workflow))
    if match is None:
        return None
    versions = [
        parse_version(quoted)
        for quoted in re.findall(r"[\"'](\d+\.\d+)[\"']", match.group(1))
    ]
    return versions or None


def resolve_floor(root: Path, override: Optional[str]) -> Version:
    """Return the floor to check against and cross-check it with the matrix."""
    if override is not None:
        return parse_version(override)
    floor = floor_from_pyproject(root)
    matrix = matrix_versions_from_workflow(root)
    if matrix is not None and floor not in matrix:
        raise CannotEstablish(
            f"requires-python floor {format_version(floor)} is not in the CI "
            f"matrix {[format_version(v) for v in matrix]}; the matrix would "
            "not exercise the declared floor"
        )
    return floor


def changed_python_files(root: Path, base: str) -> List[Path]:
    """Return the Python files that differ between ``base`` and the checkout."""
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise CannotEstablish("git is not available") from error
    except subprocess.CalledProcessError as error:
        raise CannotEstablish(
            f"cannot diff against {base!r}: {error.stderr.strip() or error}"
        ) from error
    files = []
    for line in completed.stdout.splitlines():
        name = line.strip()
        if not name or not name.endswith(".py"):
            continue
        files.append(root / name)
    return files


def scope_python_files(root: Path) -> List[Path]:
    """Return every Python file in the repository's lint scope."""
    files = []
    for scope in LINT_SCOPE_ROOTS:
        base = root / scope
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if any(part == "__pycache__" for part in path.parts):
                continue
            files.append(path)
    return files


def _dotted_path(node: ast.AST) -> Optional[str]:
    """Return the dotted path of a Name/Attribute chain, or None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_path(node.value)
        if prefix is None:
            return None
        return f"{prefix}.{node.attr}"
    return None


def _node_type(name: str) -> Optional[type]:
    """Return an ``ast`` node type, or None when the running Python lacks it."""
    return getattr(ast, name, None)


def _bound_names(nodes: Sequence[ast.AST]) -> Set[str]:
    """Return every name the module binds somewhere."""
    names: Set[str] = set()
    match_as = _node_type("MatchAs")
    match_star = _node_type("MatchStar")
    match_mapping = _node_type("MatchMapping")
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif match_as is not None and isinstance(node, match_as) and node.name:
            names.add(node.name)
        elif match_star is not None and isinstance(node, match_star) and node.name:
            names.add(node.name)
        elif match_mapping is not None and isinstance(node, match_mapping):
            if node.rest:
                names.add(node.rest)
    return names


def _annotation_roots(nodes: Sequence[ast.AST]) -> List[ast.AST]:
    roots: List[ast.AST] = []
    for node in nodes:
        if isinstance(node, ast.arg) and node.annotation is not None:
            roots.append(node.annotation)
        elif isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                roots.append(node.returns)
    return roots


def _defers_annotations(tree: ast.AST) -> bool:
    """Return True when the module defers annotation evaluation."""
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            for alias in node.names:
                if alias.name == "annotations":
                    return True
    return False


def _import_map(nodes: Sequence[ast.AST]) -> Dict[str, str]:
    """Map a local name to the dotted path it was imported from."""
    mapping: Dict[str, str] = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                mapping[local] = alias.name if alias.asname else local
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                mapping[local] = f"{module}.{alias.name}" if module else alias.name
    return mapping


def _is_builtin_typed_receiver(node: ast.AST) -> bool:
    """Return True when the receiver of an attribute access is a builtin."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (str, bytes))
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in BUILTIN_CONSTRUCTORS
    return False


def _is_type_like(
    node: ast.AST,
    type_names: Set[str],
    typing_modules: Set[str],
) -> bool:
    """Return True when the expression denotes a type for PEP 604 purposes.

    A module attribute is only treated as a type when its name looks like one:
    an attribute of a single capital letter is a flag or a constant
    (``re.S | re.M``), not a class.
    """
    if isinstance(node, ast.Constant):
        return node.value is None
    if isinstance(node, ast.Name):
        return node.id in type_names
    if isinstance(node, ast.Attribute):
        root = _dotted_path(node.value)
        root_name = root.split(".")[0] if root else None
        if node.attr[:1].isupper():
            if len(node.attr) > 1 or (root_name or "") in typing_modules:
                return True
        return _is_type_like(node.value, type_names, typing_modules)
    if isinstance(node, ast.Subscript):
        return _is_type_like(node.value, type_names, typing_modules)
    return False


def _required_version(error: SyntaxError) -> Optional[Version]:
    """Return the release a syntax error demands, when CPython names it."""
    match = SYNTAX_VERSION_RE.search(error.msg or "")
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _parse(source: str, filename: str, feature_version: Optional[Version] = None):
    """Parse ``source`` without reporting the warnings of unrelated code."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if feature_version is None:
            return ast.parse(source, filename=filename)
        return ast.parse(source, filename=filename, feature_version=feature_version)


def _fstring_quote(source: str, node: ast.JoinedStr) -> str:
    """Return the quote that delimits an f-string, or an empty string.

    Python 3.12 reports the whole f-string, prefix and both quotes, as the
    node's source.  An older interpreter reports the content only, so the
    delimiter cannot be recovered there; the caller then relies on the floor
    interpreter refusing to parse the file.
    """
    segment = ast.get_source_segment(source, node) or ""
    index = 0
    while index < len(segment) and segment[index] in "furbFURB":
        index += 1
    if index >= len(segment) or segment[index] not in "\"'":
        return ""
    triple = segment[index : index + 3]
    quote = triple if triple in ('"""', "'''") else segment[index]
    if not segment.endswith(quote):
        return ""
    return quote


def _syntax_finding(
    relative: str,
    error: SyntaxError,
    rejecting: Version,
    role: str,
    floor: Version,
) -> Finding:
    """Classify a syntax error raised while parsing a changed file.

    A file that an interpreter cannot parse is not compatible with the floor:
    it needs an interpreter newer than the one that refused it.  When the
    error names the release that provides the construct, that release is
    reported exactly; otherwise the interpreter that refused the file is
    reported, and with it the lower bound of what the file needs.
    """
    minimum = _required_version(error)
    if minimum is not None and minimum > floor:
        return Finding(
            path=relative,
            line=error.lineno or 0,
            column=error.offset or 0,
            feature=f"syntax that needs Python {format_version(minimum)}",
            minimum=minimum,
            detail=error.msg or str(error),
        )
    return Finding(
        path=relative,
        line=error.lineno or 0,
        column=error.offset or 0,
        feature=f"syntax that the {role} interpreter cannot parse",
        minimum=None,
        detail=error.msg or str(error),
        rejected_by=rejecting,
        rejected_by_role=role,
    )


def analyse_source(
    path: Path,
    source: str,
    floor: Version,
    relative_to: Optional[Path] = None,
    host: Optional[Version] = None,
    parser: Optional[Parser] = None,
) -> List[Finding]:
    """Return the constructs of ``source`` that the floor does not provide.

    ``host`` is the interpreter whose parser is used, and defaults to the one
    running the check.  ``parser`` replaces that parser, which lets a caller
    exercise the classification of a file that this interpreter cannot read.
    """
    try:
        relative = str(path.relative_to(relative_to)) if relative_to else str(path)
    except ValueError:
        relative = str(path)

    host = host if host is not None else host_version()
    if host < floor:
        raise CannotEstablish(
            f"{relative}: the running interpreter {format_version(host)} is "
            f"older than the floor {format_version(floor)}; its parser cannot "
            "decide the floor's grammar"
        )
    parse = parser if parser is not None else _parse

    findings: List[Finding] = []

    def add(
        node: ast.AST,
        feature: str,
        minimum: Version,
        detail: str,
        line: Optional[int] = None,
        column: Optional[int] = None,
    ) -> None:
        """Record a construct, unless the floor already provides it."""
        if minimum <= floor:
            return
        findings.append(
            Finding(
                path=relative,
                line=line if line is not None else getattr(node, "lineno", 0),
                column=column if column is not None else getattr(node, "col_offset", 0),
                feature=feature,
                minimum=minimum,
                detail=detail,
            )
        )

    try:
        tree = parse(source, str(path))
    except SyntaxError as error:
        # The interpreter cannot read the file at all.  That is evidence that
        # the file needs a newer interpreter, not that the question is
        # undecidable: the floor is never newer than the interpreter that
        # refused the file.
        findings.append(_syntax_finding(relative, error, host, "host", floor))
        return findings

    nodes = list(ast.walk(tree))

    # Syntax the floor interpreter rejects.  ``ast.parse`` names the exact
    # construct, so the message states the required release.  The named
    # constructs below report the same problem more precisely, so the generic
    # finding is only recorded when no named construct explains the failure.
    named_syntax = 0
    for feature, node_name, minimum in SYNTAX_NODES:
        node_type = _node_type(node_name)
        if node_type is None:
            continue
        for node in nodes:
            if isinstance(node, node_type):
                add(node, feature, minimum, f"ast.{node_name}")
                named_syntax += 1

    try:
        parse(source, str(path), feature_version=floor)
    except SyntaxError as error:
        # The floor's own grammar refuses the file, so the file needs an
        # interpreter newer than the floor.
        if named_syntax == 0:
            findings.append(_syntax_finding(relative, error, floor, "floor", floor))

    bound = _bound_names(nodes)
    loaded = {
        node.id
        for node in nodes
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    class_names = {node.name for node in nodes if isinstance(node, ast.ClassDef)}
    imports = _import_map(nodes)
    typing_names = {
        local for local, dotted in imports.items() if dotted.startswith("typing.")
    }
    typing_modules = {
        local for local, dotted in imports.items() if dotted.split(".")[0] == "typing"
    }

    # Standard-library modules and attributes.  The import statement is the
    # construct that breaks on the floor, so it is reported once there; a
    # later use of the same symbol is not reported a second time.
    reported: Set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                minimum = STDLIB_MINIMUM.get(alias.name)
                if minimum is None:
                    continue
                reported.add(alias.name)
                add(
                    node,
                    f"import of {alias.name}",
                    minimum,
                    "the module does not exist on the floor",
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            minimum = STDLIB_MINIMUM.get(module)
            if minimum is not None:
                reported.add(module)
                add(
                    node,
                    f"import from {module}",
                    minimum,
                    "the module does not exist on the floor",
                )
            for alias in node.names:
                dotted = f"{module}.{alias.name}" if module else alias.name
                minimum = STDLIB_MINIMUM.get(dotted)
                if minimum is None:
                    continue
                reported.add(dotted)
                add(
                    node,
                    f"use of {dotted}",
                    minimum,
                    "the symbol does not exist on the floor",
                )
        elif isinstance(node, ast.Attribute):
            dotted = _dotted_path(node)
            if dotted is None:
                continue
            root_name = dotted.split(".")[0]
            base = imports.get(root_name)
            if base is None:
                continue
            resolved = f"{base}.{dotted[len(root_name) + 1:]}"
            minimum = STDLIB_MINIMUM.get(resolved)
            if minimum is None or resolved in reported:
                continue
            add(
                node,
                f"use of {resolved}",
                minimum,
                "the symbol does not exist on the floor",
            )
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            resolved = imports.get(node.id)
            if resolved is None:
                continue
            minimum = STDLIB_MINIMUM.get(resolved)
            if minimum is None or resolved in reported:
                continue
            add(
                node,
                f"use of {resolved}",
                minimum,
                "the symbol does not exist on the floor",
            )

    # Builtin functions and classes the floor does not define.
    for node in nodes:
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if node.id in bound:
            continue
        minimum = BUILTIN_MINIMUM.get(node.id)
        if minimum is not None:
            add(
                node,
                f"use of builtin {node.id}",
                minimum,
                "the builtin does not exist on the floor",
            )

    # Builtin methods the floor does not define.
    for node in nodes:
        if not isinstance(node, ast.Attribute):
            continue
        minimum = METHOD_MINIMUM_ANYWHERE.get(node.attr)
        if minimum is None and _is_builtin_typed_receiver(node.value):
            minimum = METHOD_MINIMUM_TYPED.get(node.attr)
        if minimum is not None:
            add(
                node,
                f"use of method {node.attr}",
                minimum,
                "the method does not exist on the floor",
            )

    # PEP 701 f-strings.  Before Python 3.12 the f-string rules are strict
    # enough that the interpreter cannot read such a file at all, so the
    # parse failure above already reports it, and the positions of the parts
    # of an f-string are not reported exactly.  The textual rule is therefore
    # used only on the interpreters that can read the file and that report
    # those positions exactly.
    if host >= (3, 12):
        for node in nodes:
            if not isinstance(node, ast.JoinedStr):
                continue
            quote = _fstring_quote(source, node)
            for value in node.values:
                if not isinstance(value, ast.FormattedValue):
                    continue
                inner = ast.get_source_segment(source, value.value) or ""
                if quote and quote in inner:
                    add(
                        value,
                        "PEP 701 nested f-string",
                        (3, 12),
                        "a replacement field reuses the quote of its f-string",
                    )
                elif "\\" in inner:
                    add(
                        value,
                        "PEP 701 f-string with a backslash",
                        (3, 12),
                        "a backslash in a replacement field needs Python 3.12",
                    )

    # PEP 604 unions and PEP 585 builtin generics, but only where the
    # annotation is evaluated at runtime.
    annotation_ids: Set[int] = set()
    for root in _annotation_roots(nodes):
        for node in ast.walk(root):
            annotation_ids.add(id(node))
    deferred = _defers_annotations(tree)
    type_names = set(BUILTIN_TYPE_NAMES) | class_names | typing_names
    type_names |= {name for name in loaded if name[:1].isupper() and name not in bound}

    for node in nodes:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            if deferred and id(node) in annotation_ids:
                continue
            if _is_type_like(node.left, type_names, typing_modules) or _is_type_like(
                node.right, type_names, typing_modules
            ):
                add(
                    node,
                    "PEP 604 union of types",
                    (3, 10),
                    "'X | Y' needs Python 3.10 unless the annotation is deferred",
                )
        elif isinstance(node, ast.Subscript):
            value = node.value
            if not isinstance(value, ast.Name) or value.id not in PEP585_BUILTINS:
                continue
            if deferred and id(node) in annotation_ids:
                continue
            add(
                node,
                f"PEP 585 generic {value.id}[...]",
                (3, 9),
                "PEP 585 builtin generics need Python 3.9",
            )

    return findings


def check_files(
    files: Sequence[Path],
    floor: Version,
    root: Optional[Path] = None,
) -> List[Finding]:
    """Check every file and return the findings."""
    findings: List[Finding] = []
    for path in files:
        source = read_text(path)
        findings.extend(analyse_source(path, source, floor, relative_to=root))
    findings.sort(key=lambda finding: (finding.path, finding.line, finding.column))
    return findings


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check that the given Python files use no construct that the "
            "repository's Python floor interpreter lacks."
        )
    )
    parser.add_argument(
        "--root",
        default=str(REPO_ROOT),
        help="repository root to scan (default: the root of this checkout)",
    )
    parser.add_argument(
        "--base",
        help=(
            "git ref to compare against; only the Python files that differ "
            "from it are checked"
        ),
    )
    parser.add_argument(
        "--files",
        nargs="+",
        help="explicit list of Python files to check",
    )
    parser.add_argument(
        "--floor",
        help="override the Python floor (default: pyproject requires-python)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the findings as JSON",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    try:
        floor = resolve_floor(root, args.floor)
        if args.files:
            files = [Path(name).resolve() for name in args.files]
        elif args.base:
            files = changed_python_files(root, args.base)
        else:
            files = scope_python_files(root)
        findings = check_files(files, floor, root=root)
    except CannotEstablish as error:
        print(f"check_python_floor: cannot establish compatibility: {error}")
        return 2

    matrix = matrix_versions_from_workflow(root)
    if args.json:
        print(
            json.dumps(
                {
                    "floor": format_version(floor),
                    "checked_files": [str(path) for path in files],
                    "findings": [
                        {
                            "path": finding.path,
                            "line": finding.line,
                            "column": finding.column,
                            "feature": finding.feature,
                            "minimum": (
                                format_version(finding.minimum)
                                if finding.minimum is not None
                                else None
                            ),
                            "rejected_by": (
                                format_version(finding.rejected_by)
                                if finding.rejected_by is not None
                                else None
                            ),
                            "rejected_by_role": finding.rejected_by_role,
                            "detail": finding.detail,
                        }
                        for finding in findings
                    ],
                },
                indent=2,
            )
        )
        return 1 if findings else 0

    print(f"Python floor: {format_version(floor)}")
    if matrix:
        print("CI matrix: " + ", ".join(format_version(version) for version in matrix))
    print(f"Checked {len(files)} Python file(s).")
    if findings:
        print("")
        for finding in findings:
            print(finding.render())
        print("")
        print(
            f"{len(findings)} construct(s) require an interpreter newer than "
            f"Python {format_version(floor)}."
        )
        return 1
    print(
        f"No construct in the checked files requires an interpreter newer than "
        f"Python {format_version(floor)}."
    )
    print("")
    print("This static check does not establish:")
    for limitation in LIMITATIONS:
        print(f"  - {limitation}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
