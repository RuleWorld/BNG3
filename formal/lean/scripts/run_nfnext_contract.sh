#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
NF="$ROOT/cpp/nfnext"
SRC="$ROOT/formal/lean/cpp_contract/nfnext_contract.cpp"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

c++ -std=c++20 -O0 -g \
  -I"$NF/include" \
  "$SRC" \
  "$NF/src/nfir.cpp" \
  "$NF/src/generic_state.cpp" \
  "$NF/src/generic_matcher.cpp" \
  "$NF/src/transformation.cpp" \
  "$NF/src/validator.cpp" \
  -o "$TMP/nfnext_contract"

"$TMP/nfnext_contract"
