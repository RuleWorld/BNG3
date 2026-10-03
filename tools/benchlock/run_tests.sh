#!/usr/bin/env bash
# benchlock acceptance tests. Every assertion is a real lock observation.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BL="$SCRIPT_DIR/benchlock"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/bng3-benchlock-test.XXXXXX")"
export BENCHLOCK_DIR="$TEST_ROOT/locks"
export BENCHLOCK_MAX=2
export BENCHLOCK_POLL=0.05

PASS=0
FAIL=0
PA=""
PB=""
PD=""
PG=""

ok()  { echo "  PASS  $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }

cleanup() {
  for pid in "$PA" "$PB" "$PD" "$PG"; do
    if [ -n "$pid" ]; then
      kill -9 "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  for pid_file in "$TEST_ROOT"/*.pid; do
    [ -f "$pid_file" ] || continue
    child=$(cat "$pid_file" 2>/dev/null || true)
    [ -n "$child" ] && kill -9 "$child" 2>/dev/null || true
  done
  rm -rf "$TEST_ROOT"
}
trap cleanup EXIT

free_count() {
  "$BL" status | head -1 | sed 's/.*free \([0-9]*\).*/\1/'
}

wait_for_file() {
  path="$1"
  remaining=100
  while [ "$remaining" -gt 0 ] && [ ! -f "$path" ]; do
    sleep 0.05
    remaining=$((remaining-1))
  done
  [ -f "$path" ]
}

cat > "$TEST_ROOT/hold_command.py" <<'PY'
import os
import pathlib
import sys
import time

pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
time.sleep(float(sys.argv[2]))
PY

echo "=== T1: two concurrent acquires succeed, third blocks ==="
"$BL" acquire --agent A --what "t1" -- \
  python3 "$TEST_ROOT/hold_command.py" "$TEST_ROOT/a.pid" 30 > "$TEST_ROOT/a.out" 2>&1 &
PA=$!
"$BL" acquire --agent B --what "t2" -- \
  python3 "$TEST_ROOT/hold_command.py" "$TEST_ROOT/b.pid" 30 > "$TEST_ROOT/b.out" 2>&1 &
PB=$!
if wait_for_file "$TEST_ROOT/a.pid" && wait_for_file "$TEST_ROOT/b.pid"; then
  sleep 0.2
else
  bad "benchmark children failed to start"
fi
if [ "$(free_count)" = "0" ]; then ok "two holders occupy both slots (free=0)"
else bad "expected free=0, got free=$(free_count)"; fi
"$BL" acquire --agent C --what "t3" --timeout 1 > "$TEST_ROOT/c.out" 2>&1
RC_C=$?
if [ "$RC_C" -eq 2 ]; then ok "third acquirer blocked and timed out (exit 2)"
else bad "third acquirer exited $RC_C, expected 2"; fi
if grep -q "all 2 benchmark slots busy" "$TEST_ROOT/c.out"; then ok "third acquirer announced the wait"
else bad "third acquirer did not announce the wait"; fi
if grep -q "HELD by A" "$TEST_ROOT/c.out" && grep -q "HELD by B" "$TEST_ROOT/c.out"; then
  ok "third acquirer named both current holders"
else bad "third acquirer did not name both holders"; cat "$TEST_ROOT/c.out"; fi

echo "=== T2: status does not block or consume a slot ==="
python3 - "$BL" "$TEST_ROOT/status.out" <<'PY'
import subprocess
import sys

result = subprocess.run([sys.argv[1], "status"], capture_output=True, text=True,
                        timeout=5)
open(sys.argv[2], "w").write(result.stdout)
raise SystemExit(result.returncode)
PY
RC_S=$?
if [ "$RC_S" -eq 0 ]; then ok "status exited 0 under full capacity"
else bad "status exited $RC_S"; fi
if [ "$(free_count)" = "0" ]; then ok "status did not consume a slot"
else bad "status consumed a slot"; fi

echo "=== T3: live command keeps slot after wrapper SIGKILL ==="
A_CHILD=$(cat "$TEST_ROOT/a.pid" 2>/dev/null || true)
kill -9 "$PA" 2>/dev/null || true
wait "$PA" 2>/dev/null || true
sleep 0.2
FC=$(free_count)
if [ "$FC" = "0" ]; then ok "live child retained A's slot after wrapper SIGKILL"
else bad "expected both slots held, got free=$FC"; fi
if "$BL" status | grep -q "HELD by B"; then ok "B's slot remains held"
else bad "B's slot was lost"; "$BL" status; fi
if [ -n "$A_CHILD" ]; then kill -9 "$A_CHILD" 2>/dev/null || true; fi
sleep 0.2
FC=$(free_count)
if [ "$FC" = "1" ]; then ok "A's slot freed after its command exited"
else bad "expected free=1 after A child exit, got free=$FC"; fi

echo "=== T4: freed slot is reusable ==="
"$BL" acquire --agent D --what "t4" -- \
  python3 "$TEST_ROOT/hold_command.py" "$TEST_ROOT/d.pid" 20 > "$TEST_ROOT/d.out" 2>&1 &
PD=$!
if wait_for_file "$TEST_ROOT/d.pid"; then sleep 0.2; else bad "D child failed to start"; fi
if [ "$(free_count)" = "0" ]; then ok "freed slot acquired by a new holder"
else bad "freed slot not acquired"; fi
if grep -q "acquired slot" "$TEST_ROOT/d.out"; then ok "acquire printed its slot token"
else bad "acquire printed no token"; fi

echo "=== T5: command exit releases the slot ==="
B_CHILD=$(cat "$TEST_ROOT/b.pid" 2>/dev/null || true)
D_CHILD=$(cat "$TEST_ROOT/d.pid" 2>/dev/null || true)
[ -n "$B_CHILD" ] && kill -TERM "$B_CHILD" 2>/dev/null || true
[ -n "$D_CHILD" ] && kill -TERM "$D_CHILD" 2>/dev/null || true
wait "$PB" 2>/dev/null || true
wait "$PD" 2>/dev/null || true
sleep 0.2
FC=$(free_count)
if [ "$FC" = "2" ]; then ok "all slots free after wrapped commands exit"
else bad "slots not free after command exit (free=$FC)"; fi

echo "=== T6: child exit code propagates through -- ==="
"$BL" acquire --agent E --what "t6" -- sh -c 'exit 42' > "$TEST_ROOT/e.out" 2>&1
RC_E=$?
if [ "$RC_E" -eq 42 ]; then ok "benchlock returned child's exit code (42)"
else bad "benchlock returned $RC_E, expected 42"; fi
"$BL" acquire --agent F --what "t6b" -- sh -c 'exit 0' > /dev/null 2>&1
RC_F=$?
if [ "$RC_F" -eq 0 ]; then ok "benchlock returned 0 for a succeeding child"
else bad "benchlock returned $RC_F for a succeeding child"; fi
if [ "$(free_count)" = "2" ]; then ok "slot released after child exit"
else bad "slot leaked after child exit"; fi

echo "=== T7: holder metadata is machine-readable and complete ==="
"$BL" acquire --agent G --what "metadata probe" --worktree "$TEST_ROOT" -- \
  python3 "$TEST_ROOT/hold_command.py" "$TEST_ROOT/g.pid" 25 > "$TEST_ROOT/g.out" 2>&1 &
PG=$!
if wait_for_file "$TEST_ROOT/g.pid"; then sleep 0.2; else bad "G child failed to start"; fi
H=$("$BL" holders)
if echo "$H" | grep -q '"agent": *"G"'; then ok "holders reports agent"
else bad "holders missing agent"; echo "$H"; fi
if echo "$H" | grep -q "\"pid\": *$PG"; then ok "holders reports wrapper pid ($PG)"
else bad "holders missing/incorrect wrapper pid"; echo "$H"; fi
if echo "$H" | grep -q 'metadata probe'; then ok "holders reports measurement"
else bad "holders missing measurement"; fi
if echo "$H" | grep -q "$TEST_ROOT"; then ok "holders reports worktree"
else bad "holders missing worktree"; fi

echo "=== T8: killed wrapper leaves no false free slot or stale hold ==="
G_CHILD=$(cat "$TEST_ROOT/g.pid" 2>/dev/null || true)
kill -9 "$PG" 2>/dev/null || true
wait "$PG" 2>/dev/null || true
sleep 0.2
if [ "$(free_count)" = "1" ]; then ok "live G child retains its slot after wrapper death"
else bad "G slot not retained by live child"; "$BL" status; fi
[ -n "$G_CHILD" ] && kill -9 "$G_CHILD" 2>/dev/null || true
sleep 0.2
if [ "$(free_count)" = "2" ]; then ok "slot free after child dies despite stale metadata"
else bad "dead child still reported as holder"; "$BL" status; fi

echo "=== T9: capacity is configurable ==="
BENCHLOCK_MAX=3 BENCHLOCK_DIR="$TEST_ROOT/max3" "$BL" status > "$TEST_ROOT/max3.out" 2>&1
if grep -q "capacity 3  free 3  in_use 0" "$TEST_ROOT/max3.out"; then ok "BENCHLOCK_MAX=3 honoured"
else bad "BENCHLOCK_MAX ignored"; cat "$TEST_ROOT/max3.out"; fi
rm -rf "$TEST_ROOT/max3"

echo "=== T10: concurrency invariant under six-way race ==="
if python3 "$SCRIPT_DIR/race_test.py" > "$TEST_ROOT/race.out" 2>&1; then
  ok "peak concurrency never exceeded capacity"
  grep -E 'PEAK CONCURRENCY|PASS ' "$TEST_ROOT/race.out" | sed 's/^/        /'
else
  bad "race test failed"; cat "$TEST_ROOT/race.out"
fi

echo "=== T11: advisory and live-child regressions ==="
if python3 "$SCRIPT_DIR/advisory_test.py" > "$TEST_ROOT/advisory.out" 2>&1; then
  grep 'ADVISORY TESTS:' "$TEST_ROOT/advisory.out"
else
  bad "advisory test failed"; cat "$TEST_ROOT/advisory.out"
fi
if python3 "$SCRIPT_DIR/test_signal_hold.py" > "$TEST_ROOT/signal.out" 2>&1; then
  cat "$TEST_ROOT/signal.out"
else
  bad "signal-lifetime regression failed"; cat "$TEST_ROOT/signal.out"
fi
if python3 "$SCRIPT_DIR/test_interrupt_forwarding.py" > "$TEST_ROOT/interrupt.out" 2>&1; then
  cat "$TEST_ROOT/interrupt.out"
  ok "SIGINT and SIGTERM forward while the wrapper retains the slot"
else
  bad "interrupt-forwarding regression failed"; cat "$TEST_ROOT/interrupt.out"
fi
if python3 "$SCRIPT_DIR/test_advisory_errors.py" > "$TEST_ROOT/advisory-errors.out" 2>&1; then
  cat "$TEST_ROOT/advisory-errors.out"
  ok "process-table failures and worktree path detection are explicit"
else
  bad "advisory error regression failed"; cat "$TEST_ROOT/advisory-errors.out"
fi

echo
echo "=== RESULT: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
