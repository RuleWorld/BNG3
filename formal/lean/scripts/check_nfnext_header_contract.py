#!/usr/bin/env python3
"""Fail loudly if the NFnext C++ contract mirrored by Lean drifts.

This is intentionally a static check.  The compiled contract test
(`run_nfnext_contract.sh`) is stronger for behaviour; this script catches
enum/field vocabulary changes early, in an environment with no C++ toolchain.

Why this file parses instead of grepping
----------------------------------------
The previous version asserted only that certain tokens appeared SOMEWHERE in a
header.  Demonstrated gap: deleting the `DestroyMolecule` enumerator from
`enum class TransformationOpKind` left the gate PASSING, because the substring
`DestroyMolecule` also occurs in the method name `destroyMolecule(...)` further
down the same file.  Every enumerator in that enum occurs at least twice in its
own header, so substring presence proves nothing about the enum at all.

So the enum members are now extracted from the enum BODY and compared as an
ordered list.  That catches:

  * a removed enumerator (the demonstrated gap);
  * a RENAMED enumerator, even though a method of the old name survives;
  * a reordered enum, which matters because `TransformationOpKind` is an
    explicitly-ordinal `std::uint8_t` enum -- see the ordinal note below;
  * an enumerator moved out of the enum into an unrelated scope.

Ordinal note, stated because it is the reason order is checked: the enum is
declared `enum class TransformationOpKind : std::uint8_t` with no explicit
values, so its numeric values ARE its declaration order.  A grep for
`static_cast<std::uint8_t>(kind)` or any ordinal arithmetic over this enum
returns nothing today, i.e. no C++ code currently depends on the numbering --
but the Lean mirror `BNG.NFnextTransformOp` lists its constructors in a
specific order and a future serialiser would silently depend on it.  Pinning
the order now makes that a deliberate decision rather than an accident.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NF = ROOT / "cpp" / "nfnext" / "include" / "nfnext"

errors: list[str] = []


def strip_cpp_comments(text: str) -> str:
    """Blank out // and /* */ comments, preserving offsets.

    A token that survives only inside a comment is not a declaration, and the
    old substring check could not tell the difference.
    """
    out = list(text)
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
        elif text[i] == "/" and i + 1 < n and text[i + 1] == "*":
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            for _ in range(2):
                if i < n:
                    out[i] = " "
                    i += 1
        else:
            i += 1
    return "".join(out)


def enum_members(path: Path, enum_name: str) -> list[str] | None:
    """Return the ordered enumerator list of `enum ... enum_name { ... };`.

    Returns None when the enum is absent, so the caller can report that
    distinctly from "the enum is present but has the wrong members".
    """
    text = strip_cpp_comments(path.read_text(encoding="utf-8"))
    # `enum class Name : type {`  or  `enum Name {`
    m = re.search(
        r"enum(?:\s+class)?\s+" + re.escape(enum_name) + r"\s*(?::[^{]*)?\{",
        text,
    )
    if not m:
        return None
    # Find the matching close brace.
    depth = 0
    i = m.end() - 1
    start = m.end()
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = text[start:i]
    members = []
    for part in body.split(","):
        part = part.strip()
        if not part:
            continue
        # `Name = 0` or `Name{...}` or `Name`
        name = re.match(r"[A-Za-z_][A-Za-z0-9_]*", part)
        if name:
            members.append(name.group(0))
    return members


# ---------------------------------------------------------------------------
# Ordered enum contracts.  These are the checks the old substring version could
# not make.
# ---------------------------------------------------------------------------
ORDERED_ENUMS = {
    NF / "transformation.hpp": {
        "TransformationOpKind": [
            "SetState",
            "AddBond",
            "DeleteBond",
            "CreateMolecule",
            "AddBondExistingToCreated",
            "AddBondCreated",
            "DestroyMolecule",
            "DestroyComplex",
        ],
    },
    NF / "nfir.hpp": {
        "MolecularityKind": ["SameComplex", "DifferentComplex"],
        "SiteConstraintKind": ["State", "StateSet", "Free", "Bound"],
    },
}

for path, enums in ORDERED_ENUMS.items():
    if not path.exists():
        errors.append(f"missing {path}")
        continue
    for enum_name, expected in enums.items():
        actual = enum_members(path, enum_name)
        if actual is None:
            errors.append(f"{path.name}: enum {enum_name} not found")
            continue
        if actual != expected:
            missing = [e for e in expected if e not in actual]
            extra = [e for e in actual if e not in expected]
            if missing:
                errors.append(
                    f"{path.name}: enum {enum_name} is missing {missing} "
                    f"(found {actual})"
                )
            if extra:
                errors.append(
                    f"{path.name}: enum {enum_name} gained unexpected {extra} "
                    f"(found {actual})"
                )
            if not missing and not extra:
                errors.append(
                    f"{path.name}: enum {enum_name} has the right members in the "
                    f"WRONG ORDER: expected {expected}, found {actual}. The enum "
                    f"is an ordinal std::uint8_t, so declaration order is its "
                    f"numeric value."
                )

# ---------------------------------------------------------------------------
# Field / vocabulary contracts. Token checks preserve the expected vocabulary,
# but a token that also appears in a method body does not establish that its
# data member still exists. Required field declarations are pinned separately.
# ---------------------------------------------------------------------------
FIELD_TOKENS = {
    NF / "transformation.hpp": [
        "AddBondExistingToCreated",
        "AddBondCreated",
        "DestroyComplex",
        "destroyComplexContaining",
        "addBondExistingToCreated",
        "addBondCreated",
    ],
    NF / "nfir.hpp": [
        "StateSet",
        "MolecularityConstraint",
        # Field NAMES, not just method names.  `connected_to` is a PatternIR
        # member; renaming it leaves `requireConnectedTo` (the method) intact,
        # so a method-name-only check cannot see the rename.
        "connected_to",
        "interchangeable",
        "requireSameComplex",
        "requireDifferentComplex",
        "requireConnectedTo",
        "markInterchangeable",
        "interchangeable",
        "siteStateSet",
        "siteFree",
        "siteBound",
    ],
}

for path, tokens in FIELD_TOKENS.items():
    if not path.exists():
        continue
    text = strip_cpp_comments(path.read_text(encoding="utf-8"))
    for token in tokens:
        if token not in text:
            errors.append(
                f"{path.name}: expected token {token!r} not found in code "
                f"(comments are ignored)"
            )

# connected_to and interchangeable also appear in method bodies, so token
# presence does not establish that the PatternIR data members still exist.
# Pin their declaration shapes separately; this catches removal or movement to
# a comment while allowing harmless whitespace changes.
FIELD_DECLARATIONS = {
    NF / "nfir.hpp": {
        "connected_to": (
            r"^\s*std::vector\s*<\s*std::pair\s*<\s*std::size_t\s*,"
            r"\s*std::size_t\s*>\s*>\s+connected_to\s*;\s*$"
        ),
        "interchangeable": (
            r"^\s*std::vector\s*<\s*std::vector\s*<\s*std::size_t\s*>\s*>"
            r"\s+interchangeable\s*;\s*$"
        ),
    },
}

for path, declarations in FIELD_DECLARATIONS.items():
    if not path.exists():
        continue
    text = strip_cpp_comments(path.read_text(encoding="utf-8"))
    for name, pattern in declarations.items():
        if not re.search(pattern, text, re.MULTILINE):
            errors.append(
                f"{path.name}: expected field declaration for {name!r} not found "
                f"(comments and method uses do not count)"
            )

# ---------------------------------------------------------------------------
# The Lean mirror must stay in step with the C++ enum.  The Lean inductive
# `BNG.NFnextTransformOp` (formal/lean/BNG/NFnextIR.lean) lists its
# constructors in the same order as the C++ enum; if the C++ side is reordered
# and this file is not, the two disagree about what operation N is.
# ---------------------------------------------------------------------------
LEAN_NFNEXT_IR = ROOT / "formal" / "lean" / "BNG" / "NFnextIR.lean"
LEAN_OP_ORDER = [
    "setState",
    "addBond",
    "deleteBond",
    "createMolecule",
    "addBondExistingToCreated",
    "addBondCreated",
    "destroyMolecule",
    "destroyComplex",
]
CPP_TO_LEAN = {
    "SetState": "setState",
    "AddBond": "addBond",
    "DeleteBond": "deleteBond",
    "CreateMolecule": "createMolecule",
    "AddBondExistingToCreated": "addBondExistingToCreated",
    "AddBondCreated": "addBondCreated",
    "DestroyMolecule": "destroyMolecule",
    "DestroyComplex": "destroyComplex",
}

if not LEAN_NFNEXT_IR.exists():
    errors.append(f"missing {LEAN_NFNEXT_IR}")
else:
    lean_text = LEAN_NFNEXT_IR.read_text(encoding="utf-8")
    m = re.search(
        r"inductive\s+NFnextTransformOp\s+where(.*?)\n\s*deriving", lean_text, re.S
    )
    if not m:
        errors.append("NFnextIR.lean: inductive NFnextTransformOp not found")
    else:
        # Constructor lines look like `  | name (args...)`.
        found = re.findall(r"^\s*\|\s*([a-z][A-Za-z0-9_]*)", m.group(1), re.M)
        if found != LEAN_OP_ORDER:
            errors.append(
                f"NFnextIR.lean: NFnextTransformOp constructors are {found}, "
                f"expected {LEAN_OP_ORDER}; this must match the C++ "
                f"TransformationOpKind order"
            )
        # And the C++ side, if readable, must map onto it positionally.
        cpp_enum = ORDERED_ENUMS[NF / "transformation.hpp"]["TransformationOpKind"]
        cpp_as_lean = [CPP_TO_LEAN.get(c, c) for c in cpp_enum]
        if cpp_as_lean != found:
            errors.append(
                f"NFnextTransformOp order {found} disagrees with the C++ "
                f"TransformationOpKind order {cpp_enum} (as Lean names: "
                f"{cpp_as_lean})"
            )

# ---------------------------------------------------------------------------
# Keep one executable semantic slice visibly identical across the proof-friendly
# Lean reference and the production parser/CompiledModel/NFIR boundary test.
# Behavioural equality is checked by the compiled tests; this textual guard
# makes fixture drift fail early in the lightweight formal job as well.
# ---------------------------------------------------------------------------
bridge_rule = "A(x~u) + B(y) -> A(x~p!1).B(y!1)"
bridge_files = {
    ROOT / "formal" / "lean" / "BNG" / "Examples.lean": [
        bridge_rule,
        "nfnextBridgeContract_holds",
    ],
    ROOT
    / "tests"
    / "architecture_contracts"
    / "nfnext"
    / "test_bng_lowering_bridge.cpp": [bridge_rule, "lowerFromBioNetGen"],
}
for path, tokens in bridge_files.items():
    if not path.exists():
        errors.append(f"missing {path}")
        continue
    text = path.read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            errors.append(f"{path.name}: bridge token {token!r} not found")

if errors:
    print("NFNEXT HEADER CONTRACT FAILED")
    for error in errors:
        print(" -", error)
    sys.exit(1)

print("NFNEXT HEADER CONTRACT PASS")
print(
    "  TransformationOpKind, MolecularityKind and SiteConstraintKind checked as"
    " ORDERED enums (not substrings); NFnextTransformOp order cross-checked"
    " against the C++ enum."
)
