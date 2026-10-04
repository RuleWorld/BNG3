#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [[ "$(uname -s)" != Darwin ]]; then
  echo "SKIP: per-child process timing output uses macOS /usr/bin/time -l"
  exit 0
fi

for arm in A B; do
  cat > "$TMP/$arm" <<'SH'
#!/bin/sh
printf '0,1.000,2.000,3.000,10,100.0,5.0,90.0,4.0\n'
SH
  chmod +x "$TMP/$arm"
done

OUTPUT="$(bash "$ROOT/benchmarks/batch_ssa/run_ab.sh" \
  "$TMP/A" "$TMP/B" 1 --model ignored.bngl --reps 1 2>&1)"

grep -q '=== A process time samples (real/user/sys) ===' <<< "$OUTPUT"
grep -q '=== B process time samples (real/user/sys) ===' <<< "$OUTPUT"
grep -Eq '^[[:space:]]*[0-9.]+ real[[:space:]]+[0-9.]+ user[[:space:]]+[0-9.]+ sys$' <<< "$OUTPUT"
echo "PASS: per-child process time samples printed for both arms"
