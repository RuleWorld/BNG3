#!/usr/bin/env bash
# Meta-gate: prove that the gates in this directory can FAIL.
#
# Every check added to `static_validate.py`, `check_nfnext_header_contract.py`,
# `tests/Smoke.lean` and `tests/Coverage.lean` is paired here with a mutation
# that a plausible future edit could make, and the mutated tree is required to
# be REJECTED.  A gate that cannot fail is not a gate, and the cheapest way to
# be wrong about that is to never try to break it.
#
# This script NEVER touches a real worktree.  Each case is applied to a fresh
# rsync copy under $SCRATCH, and the original file is restored from a `cp`
# backup rather than from `git stash` (refs/stash is shared across every
# worktree of this repository and must not be used -- see the repo-wide rule).
#
# Usage:  ./scripts/check_harness_itself.sh [case-name ...]
#         ./scripts/check_harness_itself.sh          # run all
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# scripts/ -> formal/lean -> formal -> repo root.  `pwd -P` rather than a logical
# `../../..` walk, so a symlinked checkout resolves to the real tree.  The first
# version of this script got this wrong (it walked one level too far) and every
# case "passed" vacuously because the scratch copy was empty -- which is itself
# an instance of the defect this script exists to catch, and the reason
# `accept-*` cases are included below.
REPO="$(cd "$HERE/../.." && pwd -P)"
if [ ! -d "$REPO/formal/lean" ] || [ ! -d "$REPO/cpp/nfnext" ]; then
  echo "SELFTEST ABORTED: repo root does not look right: $REPO" >&2
  exit 2
fi
SCRATCH="${SCRATCH:-/tmp/lean-harness-selftest}"

# How each gate is invoked, relative to formal/lean in a scratch tree.
# Each scratch tree mirrors the REPOSITORY layout -- $tree/formal/lean and
# $tree/cpp -- because the gates resolve their own roots relative to their own
# location (parents[1] for ROOT, parents[3] for the repository root).  Getting
# this wrong made every gate exit non-zero for the wrong reason.
lean_dir() { printf '%s\n' "$1/formal/lean"; }

run_static()  { (cd "$(lean_dir "$1")" && python3 scripts/static_validate.py) >"$2" 2>&1; }
run_header()  { (cd "$(lean_dir "$1")" && python3 scripts/check_nfnext_header_contract.py) >"$2" 2>&1; }
run_smoke()   { (cd "$(lean_dir "$1")" && lake env lean tests/Smoke.lean) >"$2" 2>&1; }
run_coverage(){ (cd "$(lean_dir "$1")" && lake env lean tests/Coverage.lean) >"$2" 2>&1; }
run_axioms()  { (cd "$(lean_dir "$1")" && ./scripts/check_axiom_dependencies.sh) >"$2" 2>&1; }

pass=0
fail=0

# Everything this function prints must go to stderr: `make_tree` output is
# captured with $(...), so a diagnostic on stdout would be swallowed into the
# path variable and produce a nonsense `cd` target.
require_populated_tree() {
  local tree="$1"
  local n
  n=$(find "$tree/formal/lean" -name '*.lean' 2>/dev/null | wc -l | tr -d ' ')
  if [ "$n" -lt 30 ]; then
    echo "SELFTEST ABORTED: scratch tree $tree has only $n Lean files (expected >= 30)." >&2
    echo "  A gate failing on an empty tree is not evidence that the gate works." >&2
    exit 2
  fi
  if [ ! -f "$tree/cpp/nfnext/include/nfnext/transformation.hpp" ]; then
    echo "SELFTEST ABORTED: scratch tree $tree is missing the C++ headers." >&2
    exit 2
  fi
}

# make_tree <name> -> fresh scratch copy path, verified non-empty
make_tree() {
  local name="$1"
  local dest="$SCRATCH/$name"
  rm -rf "$dest"
  mkdir -p "$dest"
  # Copy the C++ side too: the header-contract and compiled-contract gates
  # resolve cpp/nfnext relative to the repository root two levels above formal.
  #
  # Two separate rsync invocations with explicit destination subdirectories.
  # A single `rsync src1/ src2/ dest/` merges the CONTENTS of both into dest/,
  # so cpp/nfnext/... would land at dest/nfnext/... and the header gate would
  # report every file missing -- which looks exactly like a failing gate.
  # `.lake` IS copied (only `build` is excluded) because the Lean gates need
  # the compiled olean cache: without it every case fails with "unknown module
  # prefix 'BNG'", which is a failure for a reason unrelated to the mutation --
  # exactly the false PASS this script exists to catch.
  rsync -a --exclude '.git' --exclude '/build' --exclude '__pycache__' \
    "$REPO/formal/" "$dest/formal/"
  rsync -a --exclude '.git' --exclude '/build' --exclude '__pycache__' \
    "$REPO/cpp/" "$dest/cpp/"
  # check_nfnext_header_contract.py also reads the C++ boundary test at
  # tests/architecture_contracts/nfnext/test_bng_lowering_bridge.cpp, so the
  # scratch tree needs `tests/` too or that gate reports it missing.
  rsync -a --exclude '.git' --exclude '/build' --exclude '__pycache__' \
    "$REPO/tests/" "$dest/tests/"
  require_populated_tree "$dest"
  printf '%s\n' "$dest"
}

# expect_reject <case> <gate-fn> <mutation-shell>
# Applies the mutation, runs the gate, and requires a NON-ZERO exit.
expect_reject() {
  local name="$1"; shift
  local runner="$1"; shift
  local mutate="$1"; shift

  local tree; tree="$(make_tree "$name")"
  ( cd "$tree" && eval "$mutate" ) >/dev/null 2>&1
  # If the mutation touched a LIBRARY file, the cached oleans must be rebuilt.
  # `lake env lean tests/Coverage.lean` resolves BNG.* from .lake/build/lib, so
  # without this an edit to formal/lean/BNG/*.lean is invisible to the test --
  # the test would pass on a stale library.  This was the cause of the first
  # version of `coverage-semantic-flip` "passing".
  if grep -q 'formal/lean/BNG/' <<<"$mutate"; then
    ( cd "$tree/formal/lean" && lake build ) >/dev/null 2>&1 || true
  fi

  local out="$SCRATCH/$name.out"
  local rc=0
  "$runner" "$tree" "$out" || rc=$?

  if [ "$rc" -ne 0 ]; then
    echo "PASS  $name  (gate exited $rc, as required)"
    echo "      $(head -3 "$out" | tr '\n' ' | ' | cut -c1-160)"
    pass=$((pass + 1))
  else
    echo "FAIL  $name  (gate exited 0 on a deliberately broken tree)"
    echo "      output was: $(head -3 "$out" | tr '\n' ' | ' | cut -c1-160)"
    fail=$((fail + 1))
  fi
  rm -rf "$tree"
}

# expect_accept <case> <gate-fn>  -- the UNMUTATED tree must pass
expect_accept() {
  local name="$1"; shift
  local runner="$1"; shift
  local tree; tree="$(make_tree "$name")"
  local out="$SCRATCH/$name.out"
  local rc=0
  "$runner" "$tree" "$out" || rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "PASS  $name  (unmutated tree accepted)"
    pass=$((pass + 1))
  else
    echo "FAIL  $name  (unmutated tree REJECTED -- the gate is too strict)"
    echo "      $(head -5 "$out" | tr '\n' ' | ' | cut -c1-200)"
    fail=$((fail + 1))
  fi
  rm -rf "$tree"
}

CASES="${*:-all}"
want() { [ "$CASES" = all ] || case " $CASES " in *" $1 "*) return 0;; *) return 1;; esac; }

echo "=== harness self-test: every case mutates a scratch copy, never this tree ==="
echo

# ---------------------------------------------------------------------------
# static_validate.py
# ---------------------------------------------------------------------------

if want accept-static; then
  expect_accept accept-static run_static
fi

if want static-sorryAx; then
  # Gap demonstrated before this gate existed: `sorryAx` is not matched by a
  # `\bsorry\b` pattern, so this file passed the OLD validator with rc=0.
  expect_reject static-sorryAx run_static \
    "printf '\ntheorem viaSorryAx : 1 = 1 := sorryAx\n' >> formal/lean/BNG/Util.lean"
fi

if want static-private-axiom; then
  # `^\s*axiom\b` did not match a modified declaration, so this passed before.
  expect_reject static-private-axiom run_static \
    "printf '\nprivate axiom trustedEscape : Nat\n' >> formal/lean/BNG/Util.lean"
fi

if want static-protected-axiom; then
  expect_reject static-protected-axiom run_static \
    "printf '\nprotected axiom trustedEscape2 : Nat\n' >> formal/lean/BNG/Util.lean"
fi

if want static-sorry-after-blockcomment; then
  # The old line-oriented comment filter skipped any line STARTING with `/-`,
  # so a real `sorry` sharing a line with a block comment was invisible.
  expect_reject static-sorry-after-blockcomment run_static \
    "printf '\ntheorem sneaky : True := by\n  /- not a comment -/ sorry\n' >> formal/lean/BNG/Util.lean"
fi

if want static-orphan-module; then
  # THE BIG ONE, demonstrated before this gate existed: a whole new module with
  # a plain type error, imported by nothing.  `static_validate.py`, `lake build`
  # AND `lake env lean tests/Smoke.lean` ALL exited 0, because lake builds only
  # the transitive closure of the declared library roots.
  expect_reject static-orphan-module run_static \
    "printf 'import BNG.Util\nnamespace BNG\ndef orphanValue : Nat := \"not a Nat\"\nend BNG\n' > formal/lean/BNG/Orphan.lean"
fi

if want static-coverage-floor; then
  # Gutting the coverage file to bare `#eval`s must fail the floor.
  expect_reject static-coverage-floor run_static \
    "printf 'import BNG\n#eval 1 + 1\n' > formal/lean/tests/Coverage.lean"
fi

if want static-smoke-floor; then
  expect_reject static-smoke-floor run_static \
    "printf 'import BNG\nopen BNG\nopen BNG.Examples\n#eval model.wellFormed\n' > formal/lean/tests/Smoke.lean"
fi

if want static-missing-import; then
  # A dangling import must be caught (this worked before; it must keep working).
  expect_reject static-missing-import run_static \
    "printf '\nimport BNG.NoSuchModule\n' >> formal/lean/BNG/Util.lean"
fi

if want static-unbalanced; then
  expect_reject static-unbalanced run_static \
    "printf '\ndef broken : Nat := (1 + 2\n' >> formal/lean/BNG/Util.lean"
fi

if want static-new-native-decide; then
  # A NEW native_decide outside the allowlist must be reported: it would add a
  # new kernel-opaque axiom that nothing else records.
  expect_reject static-new-native-decide run_static \
    "printf '\ntheorem sneaky : 1 = 1 := by native_decide\n' >> formal/lean/BNG/Util.lean"
fi

# ---------------------------------------------------------------------------
# check_nfnext_header_contract.py
# ---------------------------------------------------------------------------

if want accept-header; then
  expect_accept accept-header run_header
fi

if want header-missing-op; then
  # Removing an enum member from the C++ header must be caught.
  # Delete an ENUMERATOR LINE, not a substring.  `DestroyMolecule` also occurs
  # as the method name `destroyMolecule(...)` in the same file, so the OLD
  # substring check passed with the enumerator deleted.  `DestroyComplex` has
  # the same problem via `destroyComplexContaining`.
  expect_reject header-missing-op run_header \
    "perl -ni -e 'print unless /^    DestroyMolecule,\$/' cpp/nfnext/include/nfnext/transformation.hpp"
fi

if want header-enum-reordered; then
  # Same members, different DECLARATION ORDER.  `TransformationOpKind` is an
  # ordinal `std::uint8_t` enum with no explicit values, so order IS the numeric
  # value; no substring test can see this change at all.
  expect_reject header-enum-reordered run_header \
    "perl -0pi -e 's/(enum class TransformationOpKind : std::uint8_t \{\n)    SetState,\n    AddBond,/\$1    AddBond,\n    SetState,/' cpp/nfnext/include/nfnext/transformation.hpp"
fi

if want header-token-in-comment; then
  # Move a required field name so it survives ONLY inside a comment.  The old
  # check counted comment text as a declaration.
  expect_reject header-token-in-comment run_header \
    "printf '\n// connected_to is intentionally not implemented\n' >> cpp/nfnext/include/nfnext/nfir.hpp && perl -ni -e 'print unless /std::vector<std::pair<std::size_t, std::size_t>> connected_to;/' cpp/nfnext/include/nfnext/nfir.hpp"
fi

if want header-rename-predicate; then
  # `connected_to` is a PatternIR FIELD.  Renaming it breaks every call site
  # that the old substring check could not see, because `requireConnectedTo`
  # (the method) still contains a similar-looking token.
  expect_reject header-rename-predicate run_header \
    "sed -i '' 's/connected_to/connectedTo/g' cpp/nfnext/include/nfnext/nfir.hpp"
fi

if want header-missing-bridge; then
  # The Lean bridge contract token disappearing must be caught.
  expect_reject header-missing-bridge run_header \
    "sed -i '' 's/nfnextBridgeContract_holds/nfnextBridgeContract_RENAMED/' formal/lean/BNG/Examples.lean"
fi

# ---------------------------------------------------------------------------
# tests/Coverage.lean  (the file that was previously executed by nothing)
# ---------------------------------------------------------------------------

if want coverage-semantic-flip; then
  # A plausible wrong future edit: the reference rule phosphorylates to the
  # WRONG state.  Before Coverage.lean existed, nothing outside the library
  # build noticed; now the pinned post-state assertion must fail.
  expect_reject coverage-semantic-flip run_coverage \
    "sed -i '' 's/^      .changeState rx sP,$/      .changeState rx sU,/' formal/lean/BNG/Examples.lean"
fi

if want coverage-matcher-too-permissive; then
  # Weaken the matcher so `A(x~u)` also matches `A(x~p)`.  The negative
  # instance in Coverage.lean is the only thing that catches this.
  expect_reject coverage-matcher-too-permissive run_coverage \
    "sed -i '' 's/^      | some got => got == wanted$/      | some got => true/' formal/lean/BNG/Operational.lean"
fi

if want coverage-species-bond-blind; then
  # Make the species oracle ignore the bond graph, so `A.B` would be judged the
  # same species as `A+B`.  Demonstrated to pass lake build, Smoke.lean and the
  # OLD static_validate.py before this work.
  expect_reject coverage-species-bond-blind run_coverage \
    "perl -0pi -e 's/^  left\\.bonds\\.length == right\\.bonds\\.length &&\\n//m' formal/lean/BNG/Species.lean"
fi

if want coverage-capability-vacuous; then
  # Make `nfnextSupported` vacuously true for every direction.  Without the
  # negative instances, the fail-closed gate would protect nothing.
  expect_reject coverage-capability-vacuous run_coverage \
    "perl -0pi -e 's/\(nfnextUnsupportedReasons d\)\.isEmpty/true/' formal/lean/BNG/Capabilities.lean"
fi

if want coverage-bngir-too-permissive; then
  # Make the BNGIR decoder accept ANY version, so unknown IR is silently
  # accepted instead of refused.
  expect_reject coverage-bngir-too-permissive run_coverage \
    "perl -0pi -e 's/if ir\.version == \(\{ major := 0, minor := 2 \} : BNGIRVersion\)\n  then some ir\.document\n  else none/if true then some ir.document else none/' formal/lean/BNG/BNGIR.lean"
fi

if want coverage-protocol-legacy-allowed; then
  # Let the legacy escape hatch execute, so a protocol with an unsupported
  # action silently succeeds.
  expect_reject coverage-protocol-legacy-allowed run_coverage \
    "sed -i '' 's/^  | .legacyUnsupported _ _ => none$/  | .legacyUnsupported _ _ => some state/' formal/lean/BNG/Protocol.lean"
fi

if want coverage-seed-too-permissive; then
  # Let seed construction accept an ambiguous `!+` bond requirement, i.e. accept
  # a SET of possible graphs where one concrete seed state is required.
  expect_reject coverage-seed-too-permissive run_coverage \
    "sed -i '' 's/^    | .any => false$/    | .any => true/' formal/lean/BNG/Seeds.lean"
fi

if want coverage-lowering-divergence; then
  # Introduce a REAL divergence between the lowered backend and the reference
  # semantics -- the exact class of bug the refinement theorem exists to catch.
  # Skipping the state change in the backend path only.
  expect_reject coverage-lowering-divergence run_coverage \
    "perl -0pi -e 's/(def RuleDirection.executeBackendAction.*?\\| \\.setState target state =>\\n)(      match d\\.resolveComponent\\? env mix target with)/\$1      match none with/s' formal/lean/BNG/Lowering.lean"
fi

if want coverage-network-duplicate-species; then
  # Make the species pool treat the bonded complex as already present, so
  # network generation stops discovering A.B.
  expect_reject coverage-network-duplicate-species run_coverage \
    "perl -0pi -e 's/if pool\\.any \\(fun existing => existing\\.isomorphicSpecies candidate\\) then pool/if true then pool/' formal/lean/BNG/Species.lean"
fi

if want coverage-name-resolution-guess; then
  # Make name resolution fall back to a default ID instead of failing closed.
  expect_reject coverage-name-resolution-guess run_coverage \
    "sed -i '' 's/^  (resolveNamedExpr model source)\\.isSome$/  true/' formal/lean/BNG/NameResolution.lean"
fi

if want coverage-observables-counter-guessed; then
  # Make the unsupported `counter` observable return a number instead of `none`.
  expect_reject coverage-observables-counter-guessed run_coverage \
    "sed -i '' 's/^  | .counter => none$/  | .counter => some 0/' formal/lean/BNG/Observables.lean"
fi

# ---------------------------------------------------------------------------
# tests/Smoke.lean  -- the gate that existed but asserted nothing
# ---------------------------------------------------------------------------

if want smoke-semantic-flip; then
  expect_reject smoke-semantic-flip run_smoke \
    "sed -i '' 's/^      .changeState rx sP,$/      .changeState rx sU,/' formal/lean/BNG/Examples.lean"
fi

if want smoke-badpattern-accepted; then
  # Make the well-formedness validator accept an undeclared state ID.  The ONLY
  # thing that catches this is Coverage.lean's negative instance; Smoke.lean's
  # own assertions do not, which is why both files exist.
  expect_reject smoke-badpattern-accepted run_coverage \
    "perl -0pi -e 's/(def Pattern\.wellFormed \(p : Pattern\) \(sig : Signature\) :=)/\$1\n  let _ := sig; true \&\& (by/' formal/lean/BNG/Pattern.lean"
fi

# ---------------------------------------------------------------------------
# check_axiom_dependencies.sh
# ---------------------------------------------------------------------------

if want axioms-new-native; then
  # A new native_decide inside the LIBRARY (not the test files) introduces a new
  # kernel-opaque axiom.  The audit reports it; the allowlist check in
  # static_validate.py is what makes it a failure.
  expect_reject axioms-new-native run_static \
    "printf '\ntheorem sneakyNative : 1 = 1 := by native_decide\n' >> formal/lean/BNG/Util.lean"
fi

echo
echo "=== self-test summary: $pass passed, $fail failed ==="
if [ "$fail" -ne 0 ]; then
  echo "A gate that does not fail on a broken tree is not a gate."
  exit 1
fi
echo "Every strengthened check has a demonstrated failing case."
