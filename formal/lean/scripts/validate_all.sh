#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
python3 scripts/static_validate.py
python3 scripts/check_nfnext_header_contract.py
./scripts/run_nfnext_contract.sh
if command -v lake >/dev/null 2>&1; then
  lake build
  lake env lean tests/Smoke.lean
else
  echo "LEAN KERNEL CHECK SKIPPED: lake is not installed"
fi
