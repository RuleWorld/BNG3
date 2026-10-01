#!/usr/bin/env bash
# Full local gate for the Lean semantic kernel.
#
# This script previously ran `lake build` and `tests/Smoke.lean` ONLY IF `lake`
# was on PATH, printing "LEAN KERNEL CHECK SKIPPED" and exiting 0 otherwise --
# while `.github/workflows/formal.yml` ran `lake build` unconditionally.  A
# developer running the local script therefore got a strictly weaker gate than
# CI, and the skip path exited successfully, so a missing toolchain looked like
# a pass.  That asymmetry is now closed: the kernel steps are REQUIRED, and the
# script says exactly how to install the pinned toolchain if they cannot run.
#
# The two Lean test files are named explicitly because `lake build` does not
# compile them: `lakefile.lean` declares `@[default_target] lean_lib BNG` with
# root `BNG/`, so only the library is built.  Before this script and the CI
# workflow named them, `tests/Coverage.lean` -- ~130 assertions -- was executed
# by nothing at all.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

echo "== static validation =="
python3 scripts/static_validate.py

echo
echo "== NFnext header contract =="
python3 scripts/check_nfnext_header_contract.py

echo
echo "== NFnext compiled contract =="
./scripts/run_nfnext_contract.sh

if ! command -v lake >/dev/null 2>&1; then
  echo
  echo "VALIDATION FAILED: the Lean kernel gate could not run."
  echo
  echo "  'lake' is not on PATH, so the pinned kernel check and both Lean test"
  echo "  files were skipped.  This is a FAILURE, not a skip: the project pins"
  echo "  leanprover/lean4:v4.33.1 in formal/lean/lean-toolchain, and these gates"
  echo "  are the only ones that actually check the theorems."
  echo
  echo "  Install it with:"
  echo "    curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y"
  echo "    cd formal/lean && lake build"
  exit 1
fi

echo
echo "== Lean kernel build =="
lake build

echo
echo "== Lean test: tests/Smoke.lean =="
lake env lean tests/Smoke.lean

echo
echo "== Lean test: tests/Coverage.lean =="
lake env lean tests/Coverage.lean

echo
echo "== axiom dependency audit =="
./scripts/check_axiom_dependencies.sh

echo
echo "ALL LEAN VALIDATION PASSED"
