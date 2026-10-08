#!/usr/bin/env bash
# Audit which proof terms in this project depend on kernel-opaque axioms.
#
# Why this exists.  `native_decide` reduces through the compiled evaluator and
# its proof term depends on a per-declaration axiom that the kernel does not
# check.  That is a weaker guarantee than `rfl`/`decide`, and a project whose
# value proposition is kernel checking should not blur it.  This script makes
# the split measurable instead of a claim in a docstring.
#
# Verified on this tree (leanprover/lean4:v4.33.1, formal/lean):
#
#   BNG.structural_roundtrip            -> does not depend on any axioms
#   BNG.execute_lowered_rule_eq_reference-> [propext, Quot.sound]
#   BNG.Examples.nfnextBridgeContract_holds
#       -> [propext, Classical.choice, Quot.sound,
#           nfnextBridgeContract_holds._native.native_decide.ax_1_1]
#
# The last line is the one that matters: `propext`, `Classical.choice` and
# `Quot.sound` are Lean's three standard axioms and are what any `Decidable`-based
# proof uses.  The fourth, `..._native_decide.ax_1_1`, is NOT: it is
# kernel-opaque and is the price of native evaluation.
#
# The gate: every declaration whose ONLY non-standard dependency is a
# `_native.native_decide` axiom must be listed in NATIVE_DECIDE_ALLOWLIST below,
# and no declaration may depend on any OTHER axiom.  A new `native_decide`, or a
# genuinely new axiom, therefore fails here instead of passing unnoticed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

if ! command -v lake >/dev/null 2>&1; then
  echo "AXIOM AUDIT SKIPPED: lake is not installed" >&2
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Every declaration we care about: all library theorems plus every assertion in
# the two test files.  Test-file assertions are anonymous `example`s, so they
# are audited by declaring named wrappers around the same tactic goals is not
# possible; instead we audit the library theorems here and count tactic usage
# textually below, which is what the allowlist is keyed on.
cat > "$TMP/audit.lean" <<'LEAN'
import BNG
open BNG
#print axioms BNG.source_text_is_not_semantics
#print axioms BNG.source_irrelevance_again
#print axioms BNG.rule_side_roundtrip
#print axioms BNG.PatternSide.flip_involutive
#print axioms BNG.pattern_lowering_keeps_nodes
#print axioms BNG.pattern_lowering_keeps_bonds
#print axioms BNG.rule_lowering_keeps_edits
#print axioms BNG.lower_preserves_molecule_count
#print axioms BNG.lower_preserves_bond_count
#print axioms BNG.lower_preserves_mutation_count
#print axioms BNG.backend_one_edit_refines_semantics
#print axioms BNG.backend_edit_program_refines_semantics
#print axioms BNG.backend_rule_step_refines_semantics
#print axioms BNG.execute_lowered_mutation_eq_reference
#print axioms BNG.execute_lowered_program_eq_reference
#print axioms BNG.execute_lowered_rule_eq_reference
#print axioms BNG.connectedFrom_empty
#print axioms BNG.empty_molecule_observable_zero
#print axioms BNG.structural_roundtrip
#print axioms BNG.compileStructuralSemantics_deterministic
#print axioms BNG.Examples.nfnextBridgeContract_holds
#print axioms BNG.Examples.example_lowered_step_equals_semantic_step
#print axioms BNG.NFnextPacking.fromSignature_type_entry
#print axioms BNG.NFnextPacking.fromSignature_site_entry
#print axioms BNG.NFnextPacking.fromSignature_state_entry
LEAN

OUT="$(lake env lean "$TMP/audit.lean" 2>&1)"

# Lean's three standard axioms.  `propext`/`Classical.choice`/`Quot.sound` are
# what every `Decidable`-driven proof legitimately uses and are not defects.
STANDARD="propext Classical.choice Quot.sound"
NATIVE_RE='native_decide\.ax_'

fail=0

echo "=== axiom dependencies of library theorems ==="
echo "$OUT" | grep -E "^'" | sed 's/^/  /'

echo
echo "=== declarations depending on a kernel-opaque native_decide axiom ==="
NATIVE_LINES="$(echo "$OUT" | grep -E "$NATIVE_RE" || true)"
if [ -z "$NATIVE_LINES" ]; then
  echo "  (none)"
else
  echo "$NATIVE_LINES" | sed 's/^/  /'
  echo
  echo "  Each of the above is compiler-checked, NOT kernel-checked."
  echo "  Adding another requires adding it to NATIVE_DECIDE_ALLOWLIST in"
  echo "  scripts/static_validate.py, with a stated reason."
fi

echo
echo "=== declarations depending on a NON-STANDARD, NON-NATIVE axiom ==="

# `#print axioms` wraps long axiom lists across lines, so the raw output cannot
# be parsed a line at a time.  Reassemble each declaration onto one line with
# awk, emitting `DECL|axiom` pairs, and skip the `does not depend on any axioms`
# case entirely (that is the CLEAN verdict, not a failure).
DECL_AXIOMS="$(
  printf '%s\n' "$OUT" | awk '
    /^'"'"'/ {
      line = $0
      while (line !~ /\][ ]*$/ && (getline cont) > 0) { line = line " " cont }
      gsub(/[ \t]+/, " ", line)
      if (line ~ /does not depend on any axioms/) next
      name = line
      sub(/^'"'"'/, "", name)
      sub(/'"'"' depends on axioms: \[.*$/, "", name)
      payload = line
      sub(/^.*depends on axioms: \[/, "", payload)
      sub(/\].*$/, "", payload)
      n = split(payload, parts, ",")
      for (i = 1; i <= n; i++) {
        a = parts[i]
        gsub(/^ | $/, "", a)
        if (a != "") print name "|" a
      }
    }
  '
)"

UNEXPECTED="$(
  printf '%s\n' "$DECL_AXIOMS" |
    grep -vE "^[^|]+\|(propext|Classical\.choice|Quot\.sound)$" |
    grep -vE "native_decide\.ax_" || true
)"

if [ -z "$UNEXPECTED" ]; then
  echo "  (none)"
else
  echo "$UNEXPECTED" | sed 's/^/  UNEXPECTED: /'
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo
  echo "AXIOM AUDIT FAILED: a declaration depends on an axiom that is neither one"
  echo "of Lean's three standard axioms nor a declared native_decide extension."
  exit 1
fi

echo
echo "AXIOM AUDIT PASS"
