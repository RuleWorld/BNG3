#!/usr/bin/env python3
"""Conservative static checks for the standalone BNG3 Lean project.

This script is NOT a replacement for `lake build`.  It exists because some
packaging/CI environments may not have Lean installed.  It catches mundane
artifact problems early: broken local imports, unbalanced delimiters/comments,
unreachable modules, and proof placeholders.

Design rule for this file: a check must be able to FAIL on a tree where the
thing it protects is broken.  Concretely, every check below was added together
with a demonstrated broken copy that it rejects; see
`scripts/check_harness_itself.sh`, which re-runs those demonstrations on demand.
In particular this file does not use substring matching to decide whether Lean
code contains a placeholder -- it masks comments and string literals out of the
source first, so `sorry` hidden in a comment is not a false pass and `sorry`
sharing a line with a block comment is not a false negative.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEAN_FILES = sorted(ROOT.rglob("*.lean"))

# `import BNG.Foo` or `import BNG.Foo (bar)`; the old regex demanded end-of-line
# immediately after the module name, so a scoped import was never checked.
IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z0-9_.]+)")

# Placeholders, matched against CODE ONLY (comments and string literals masked
# out by `mask_comments_and_strings`).  Every alternative below was verified to
# be a real escape hatch that `lake build` accepts:
#
#   sorry          the standard hole
#   sorryAx!       the hole that survives even with `set_option warningAsError true`
#   sorryAx        the axiom form of the same
#   admit          Lean 3 / Mathlib-style hole
#   axiom          a trusted constant; `axiom` may carry declaration modifiers,
#                  so it is matched as a word rather than only at line start
PLACEHOLDER_RE = re.compile(r"\bsorry\b|\bsorryAx\b|\badmit\b|\baxiom\b")


def local_module_path(module: str) -> Path | None:
    if module == "BNG":
        return ROOT / "BNG.lean"
    if module.startswith("BNG."):
        return ROOT / (module.replace(".", "/") + ".lean")
    return None


def module_name_for(path: Path) -> str | None:
    """Map a Lean file to the module name other files would use to import it."""
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "BNG" and len(parts) == 1:
        return "BNG"
    if parts[0] == "BNG" and len(parts) == 2:
        return "BNG." + parts[1]
    return None


def mask_comments_and_strings(text: str) -> tuple[str, list[str]]:
    """Replace comment and string-literal content with spaces, preserving offsets.

    Returns the masked text plus a list of structural errors.  Masking (rather
    than deleting) keeps byte offsets aligned so an error can still be reported
    against the original source.  Newlines are preserved so line numbers stay
    meaningful.

    This replaces the previous line-oriented filter, which had two defects that
    were demonstrated against a broken copy:

    * `sorryAx` / `sorryAx!` are not matched by a `\\bsorry\\b` pattern, so a
      file containing `theorem viaSorryAx : 1 = 1 := sorryAx` passed;
    * a line such as `  /- not a comment -/ sorry` was skipped wholesale
      because it *starts* with `/-`, so a real `sorry` was missed.
    """
    errors: list[str] = []
    out = list(text)
    stack: list[tuple[str, int]] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    comment_depth = 0
    in_string = False
    escaped = False
    i = 0

    def blank(pos: int) -> None:
        if out[pos] != "\n":
            out[pos] = " "

    while i < len(text):
        c = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if comment_depth:
            if c == "/" and nxt == "-":
                comment_depth += 1
                blank(i)
                blank(i + 1)
                i += 2
                continue
            if c == "-" and nxt == "/":
                comment_depth -= 1
                blank(i)
                blank(i + 1)
                i += 2
                continue
            blank(i)
            i += 1
            continue

        if in_string:
            if escaped:
                escaped = False
                blank(i)
            elif c == "\\":
                escaped = True
                blank(i)
            elif c == '"':
                in_string = False
                blank(i)
            else:
                blank(i)
            i += 1
            continue

        if c == "-" and nxt == "-":
            nl = text.find("\n", i + 2)
            end = len(text) if nl == -1 else nl
            for j in range(i, end):
                blank(j)
            i = end
            continue
        if c == "/" and nxt == "-":
            comment_depth = 1
            blank(i)
            blank(i + 1)
            i += 2
            continue
        if c == '"':
            in_string = True
            blank(i)
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
    return "".join(out), errors


def scan_balancing(path: Path) -> list[str]:
    _, errors = mask_comments_and_strings(path.read_text(encoding="utf-8"))
    return errors


def check_unreachable_modules(errors: list[str]) -> None:
    """Every module under `BNG/` must be reachable from `BNG.lean`.

    Demonstrated gap this closes: adding `BNG/Orphan.lean` containing a plain
    type error (`def orphanValue : Nat := "not a Nat"`) and importing nothing
    that references it passed `static_validate.py` AND `lake build` AND
    `lake env lean tests/Smoke.lean`, all with rc=0, because lake builds only
    the transitive closure of the declared library roots.  A whole file of Lean
    could be broken and every gate stayed green.
    """
    modules: dict[str, Path] = {}
    for path in LEAN_FILES:
        name = module_name_for(path)
        if name is not None:
            modules[name] = path

    reachable: set[str] = set()
    stack = ["BNG"]
    while stack:
        name = stack.pop()
        if name in reachable or name not in modules:
            continue
        reachable.add(name)
        for line in modules[name].read_text(encoding="utf-8").splitlines():
            m = IMPORT_RE.match(line)
            if m and m.group(1) in modules:
                stack.append(m.group(1))

    for name in sorted(set(modules) - reachable):
        errors.append(
            f"{modules[name].relative_to(ROOT)}: module {name} is never imported "
            f"transitively from BNG.lean, so lake build never type-checks it"
        )


def check_assertion_floor(errors: list[str]) -> None:
    """Each Lean file under `tests/` must carry a minimum number of assertions.

    Demonstrated gap this closes: `tests/Smoke.lean` consisted entirely of bare
    `#eval`s plus one `example` re-proving a theorem `lake build` already proves.
    A bare `#eval` prints its result and the build succeeds whether it prints
    `true` or `false`, so no expected value in the file was enforced -- and the
    module docstring nonetheless promised five of them.

    Two failure modes are covered:

    * a test file with NO proof obligation at all (gutted to bare printing);
    * a test file that has lost most of its assertions (the subtler version, and
      the one a well-meaning refactor would produce).

    `tests/Coverage.lean` additionally had to be WIRED IN: it existed with ~130
    assertions and was executed by nothing -- not `lake build` (whose only
    library root is `BNG/`), not `.github/workflows/formal.yml` (which ran
    exactly one Lean invocation), and not this script.  It is now run by
    `validate_all.sh` and by `formal.yml`, and appears in `required` below, so
    deleting it fails the gate rather than silently reducing coverage.
    """
    test_files = sorted((ROOT / "tests").rglob("*.lean"))
    if not test_files:
        errors.append("missing required directory: tests/ with at least one Lean file")
        return
    # NOTE the `\b` and NOT `\s+\w`: most assertions in these files are
    # ANONYMOUS `example : <prop> := by ...`, with no declaration name.  An
    # earlier version of this regex required a name and therefore counted 2 of
    # 225 declarations in tests/Coverage.lean and 0 of 13 in tests/Smoke.lean --
    # which would have made the floor permanently unsatisfiable rather than
    # merely wrong.
    decl_re = re.compile(
        r"^\s*(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+)?"
        r"(?:theorem|example|lemma)\b",
        re.MULTILINE,
    )
    # Floors are set BELOW the current counts (13 and 225) so ordinary
    # editing does not trip them, but deleting the assertions does.
    floors = {"Smoke.lean": 10, "Coverage.lean": 180}
    for path in test_files:
        code, _ = mask_comments_and_strings(path.read_text(encoding="utf-8"))
        count = len(decl_re.findall(code))
        floor = floors.get(path.name, 1)
        if count < floor:
            errors.append(
                f"{path.relative_to(ROOT)}: only {count} theorem/example/lemma "
                f"declarations, expected at least {floor}; the floor exists so a "
                f"test file cannot be gutted to bare #evals -- which cannot fail "
                f"a build -- without this gate failing"
            )


def check_no_unmasked_placeholder(errors: list[str]) -> None:
    for path in LEAN_FILES:
        text = path.read_text(encoding="utf-8")
        code, _ = mask_comments_and_strings(text)
        m = PLACEHOLDER_RE.search(code)
        if m:
            line = code[: m.start()].count("\n") + 1
            errors.append(
                f"{path.relative_to(ROOT)}:{line}: contains proof placeholder "
                f"{m.group(0)!r} in code (sorry/sorryAx/admit/axiom)"
            )


def check_trusted_proof_tactics(errors: list[str]) -> None:
    """Record -- and bound -- the use of `native_decide`, which is NOT kernel-checked.

    `native_decide` reduces through the compiled evaluator and its proof term
    depends on a per-declaration, kernel-opaque axiom
    (`<name>._native.native_decide.ax_1_1`).  Verified on this tree:

        #print axioms BNG.Examples.nfnextBridgeContract_holds
        'BNG.Examples.nfnextBridgeContract_holds' depends on axioms:
          [propext, Classical.choice, Quot.sound,
           nfnextBridgeContract_holds._native.native_decide.ax_1_1]

    So it is a weaker guarantee than `rfl`/`decide`, and a project whose value
    proposition is kernel checking should not blur the two.  Two separate rules:

    * In the LIBRARY (`BNG/**`), `native_decide` is allowlisted and any new
      occurrence must be added to NATIVE_DECIDE_ALLOWLIST with a stated reason.
      A new one is a new kernel-opaque axiom and should be a deliberate act.
    * In `tests/**`, `native_decide` is EXPECTED and is not gated -- that is the
      documented proof method for the executable-coverage assertions, and
      `tests/Coverage.lean` states the dependency in its own docstring.  What is
      gated there is the assertion FLOOR (see check_assertion_floor), so the file
      cannot be quietly emptied.
    """
    for path in LEAN_FILES:
        rel = str(path.relative_to(ROOT))
        if rel.startswith("tests" + "/"):
            continue
        text = path.read_text(encoding="utf-8")
        code, _ = mask_comments_and_strings(text)
        if not re.search(r"\bnative_decide\b", code):
            continue
        if rel not in NATIVE_DECIDE_ALLOWLIST:
            errors.append(
                f"{rel}: uses native_decide (trusted via Lean.ofReduceBool, not "
                f"kernel-checked) but is not listed in NATIVE_DECIDE_ALLOWLIST"
            )


NATIVE_DECIDE_ALLOWLIST = {
    # One entry, pre-existing before this validator learned to count.  The
    # statement is substantive; only the proof method is trusted.
    "BNG/Examples.lean": "nfnextBridgeContract_holds -- substantive statement, trusted proof method",
}

# A reason is not decoration.  Without this, `"BNG/Foo.lean": ""` silently
# weakens the `Lean.ofReduceBool` checking for a whole file and the gate stays
# green, which is the "reports success while testing nothing" shape again one
# level down.  An entry must say WHICH declaration is trusted and WHY the
# statement is nonetheless worth having, in at least MIN_REASON_CHARS characters.
MIN_REASON_CHARS = 30


def check_allowlist_reasons(errors: list[str]) -> None:
    """Every allowlist entry must carry a substantive reason.

    Also flags two ways the allowlist can rot silently:
      * an entry for a file that no longer exists (stale, so a future author may
        believe the weakening is still justified when it is not);
      * an entry for a file that no longer uses native_decide (dead, same risk).
    """
    for rel, reason in NATIVE_DECIDE_ALLOWLIST.items():
        if not isinstance(reason, str) or len(reason.strip()) < MIN_REASON_CHARS:
            errors.append(
                f"NATIVE_DECIDE_ALLOWLIST[{rel!r}]: reason is too short to be a "
                f"reviewable justification (needs >= {MIN_REASON_CHARS} chars "
                f"saying which declaration is trusted and why); got {reason!r}. "
                f"This gate exists so a new trusted `native_decide` is a visible "
                f"weakening of kernel checking rather than a silent one."
            )
        path = ROOT / rel
        if not path.exists():
            errors.append(
                f"NATIVE_DECIDE_ALLOWLIST[{rel!r}]: stale entry, the file no "
                f"longer exists; a future author may read it as still justifying "
                f"a weakening that no longer applies"
            )
            continue
        code, _ = mask_comments_and_strings(path.read_text(encoding="utf-8"))
        if not re.search(r"\bnative_decide\b", code):
            errors.append(
                f"NATIVE_DECIDE_ALLOWLIST[{rel!r}]: dead entry, the file no "
                f"longer uses native_decide"
            )


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
                errors.append(
                    f"{rel}:{line_no}: missing local import {m.group(1)} -> {local}"
                )

        for err in scan_balancing(path):
            errors.append(f"{rel}: {err}")

    check_no_unmasked_placeholder(errors)
    check_unreachable_modules(errors)
    check_assertion_floor(errors)
    check_trusted_proof_tactics(errors)
    check_allowlist_reasons(errors)

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
        ROOT / "tests" / "Coverage.lean",
        ROOT / "cpp_contract" / "nfnext_contract.cpp",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")

    umbrella = (ROOT / "BNG.lean").read_text(encoding="utf-8")
    umbrella_code, _ = mask_comments_and_strings(umbrella)
    umbrella_imports = {
        m.group(1)
        for m in (IMPORT_RE.match(l) for l in umbrella_code.splitlines())
        if m
    }
    for module in (
        "BNG.Runtime",
        "BNG.Graph",
        "BNG.Operational",
        "BNG.ExtendedOperational",
        "BNG.Correspondence",
        "BNG.MutationCompiler",
        "BNG.MatcherSpec",
        "BNG.Species",
        "BNG.Network",
        "BNG.NFnextIR",
        "BNG.BNGIR",
        "BNG.Lowering",
    ):
        if module not in umbrella_imports:
            errors.append(f"BNG.lean does not import {module}")

    if errors:
        print("STATIC VALIDATION FAILED")
        for error in errors:
            print(" -", error)
        return 1

    native = sum(
        1
        for path in LEAN_FILES
        if re.search(
            r"\bnative_decide\b",
            mask_comments_and_strings(path.read_text(encoding="utf-8"))[0],
        )
    )
    print(f"STATIC VALIDATION PASSED ({len(LEAN_FILES)} Lean files checked)")
    print("  every BNG/*.lean is transitively imported from BNG.lean")
    print(f"  Lean files using native_decide: {native} (library uses are allowlisted)")
    print("Reminder: this does not replace `lake build` / Lean kernel checking.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
