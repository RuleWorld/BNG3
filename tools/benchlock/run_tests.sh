#!/usr/bin/env bash
# benchlock acceptance tests. Every assertion is a real concurrency
# observation, not an inspection of the source.
set -u
BL=/tmp/bng-bench-lock/benchlock
# A UNIQUE lockdir per invocation. Two runs of this suite must never contend:
# the suite asserts exact free-slot counts, which are only meaningful if it is
# the only user of the directory. Running it in a loop (which I did, hunting a
# flake) made iterations fight over a shared dir and produced failures that
# looked exactly like a slot leak in benchlock. It was not one -- an isolated
# repro shows the lock releases correctly on SIGKILL. The bug was here.
export BENCHLOCK_DIR="/tmp/bng-bench-lock-test.$$.$RANDOM"
rm -rf "$BENCHLOCK_DIR"
trap 'rm -rf "$BENCHLOCK_DIR"' EXIT
PASS=0; FAIL=0
ok()  { echo "  PASS  $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }
free_count() { $BL status | head -1 | sed 's/.*free \([0-9]*\).*/\1/'; }

echo "=== T1: two concurrent acquires succeed, third blocks ==="
$BL acquire --agent A --what "t1" -- sleep 30 > /tmp/bl_a.out 2>&1 & PA=$!
$BL acquire --agent B --what "t2" -- sleep 30 > /tmp/bl_b.out 2>&1 & PB=$!
sleep 1.5
if [ "$(free_count)" = "0" ]; then ok "two holders occupy both slots (free=0)"
else bad "expected free=0, got free=$(free_count)"; fi
$BL acquire --agent C --what "t3" --timeout 3 > /tmp/bl_c.out 2>&1; RC_C=$?
if [ "$RC_C" -eq 2 ]; then ok "third acquirer blocked and timed out (exit 2)"
else bad "third acquirer exited $RC_C, expected 2"; fi
if grep -q "all 2 benchmark slots busy" /tmp/bl_c.out; then ok "third acquirer announced it was waiting"
else bad "third acquirer did not announce the wait"; fi
if grep -q "HELD by A" /tmp/bl_c.out && grep -q "HELD by B" /tmp/bl_c.out; then
  ok "third acquirer named BOTH current holders"
else bad "third acquirer did not name both holders"; cat /tmp/bl_c.out; fi

echo "=== T2: status never blocks and never takes a slot ==="
timeout 5 $BL status > /tmp/bl_status.out 2>&1; RC_S=$?
if [ "$RC_S" -eq 0 ]; then ok "status exited 0 under full capacity"
else bad "status exited $RC_S"; fi
if [ "$(free_count)" = "0" ]; then ok "status did not consume a slot while reading"
else bad "status consumed a slot"; fi

echo "=== T3: SIGKILL releases exactly one slot, with no cleanup step ==="
kill -9 $PA 2>/dev/null; wait $PA 2>/dev/null
sleep 1.5
FC=$(free_count)
if [ "$FC" = "1" ]; then ok "SIGKILLed holder released its slot immediately (free=1, other still held)"
else bad "expected free=1 after one kill, got free=$FC"; fi
if $BL status | grep -q "HELD by B"; then ok "the surviving holder is still HELD and correctly named"
else bad "surviving holder lost"; $BL status; fi

echo "=== T4: freed slot is reusable at once ==="
$BL acquire --agent D --what "t4" -- sleep 20 > /tmp/bl_d.out 2>&1 & PD=$!
sleep 1.5
if [ "$(free_count)" = "0" ]; then ok "freed slot immediately acquired by a new agent"
else bad "freed slot not acquirable"; fi
if grep -q "acquired slot" /tmp/bl_d.out; then ok "acquire printed its slot token"
else bad "acquire printed no token"; cat /tmp/bl_d.out; fi

echo "=== T5: normal exit releases the slot ==="
kill -TERM $PB 2>/dev/null; wait $PB 2>/dev/null
kill -TERM $PD 2>/dev/null; wait $PD 2>/dev/null
sleep 1
FC=$(free_count)
if [ "$FC" = "2" ]; then ok "all slots free after holders exit (free=2)"
else bad "slots not free after exit (free=$FC)"; fi

echo "=== T6: child exit code propagates through -- ==="
$BL acquire --agent E --what "t6" -- sh -c 'exit 42' > /tmp/bl_e.out 2>&1; RC_E=$?
if [ "$RC_E" -eq 42 ]; then ok "benchlock returned the child's exit code (42)"
else bad "benchlock returned $RC_E, expected 42"; fi
$BL acquire --agent F --what "t6b" -- sh -c 'exit 0' > /dev/null 2>&1; RC_F=$?
if [ "$RC_F" -eq 0 ]; then ok "benchlock returned 0 for a succeeding child"
else bad "benchlock returned $RC_F for a succeeding child"; fi
if [ "$(free_count)" = "2" ]; then ok "slot released after the child exited"
else bad "slot leaked after child exit"; fi

echo "=== T7: holder metadata is machine-readable and complete ==="
$BL acquire --agent G --what "metadata probe" --worktree /tmp/some-worktree -- sleep 25 > /dev/null 2>&1 & PG=$!
sleep 1.5
H=$($BL holders)
if echo "$H" | grep -q '"agent": *"G"'; then ok "holders reports the agent name"
else bad "holders missing agent"; echo "$H"; fi
if echo "$H" | grep -q "\"pid\": *$PG"; then ok "holders reports the holder's pid ($PG)"
else bad "holders missing/incorrect pid"; echo "$H"; fi
if echo "$H" | grep -q 'metadata probe'; then ok "holders reports what is being measured"
else bad "holders missing measurement description"; fi
if echo "$H" | grep -q '/tmp/some-worktree'; then ok "holders reports the owning worktree"
else bad "holders missing worktree"; fi

echo "=== T8: stale metadata cannot masquerade as a live hold ==="
kill -9 $PG 2>/dev/null; wait $PG 2>/dev/null
sleep 1.5
if [ "$(free_count)" = "2" ]; then
  ok "killed holder shows FREE in status despite the lingering metadata file"
else bad "killed holder still reported as held"; $BL status; fi

echo "=== T9: capacity is configurable ==="
BENCHLOCK_MAX=3 BENCHLOCK_DIR="${BENCHLOCK_DIR}.max3" $BL status > /tmp/bl_c3.$$ 2>&1
if grep -q "capacity 3  free 3  in_use 0" /tmp/bl_c3.$$; then ok "BENCHLOCK_MAX=3 honoured"
else bad "BENCHLOCK_MAX ignored"; cat /tmp/bl_c3.$$; fi
rm -rf "${BENCHLOCK_DIR}.max3" /tmp/bl_c3.$$

echo "=== T10: concurrency invariant under contention (delegated) ==="
# The invariant is "never more than MAX held at any instant", not "only MAX
# racers ever win" -- a holder that finishes legitimately frees its slot, so
# with N > MAX racers all of them may eventually acquire. That is correct
# behaviour, and asserting otherwise would have been testing the wrong thing.
if python3 /tmp/bng-bench-lock/race_test.py > /tmp/bl_race.out 2>&1; then
  ok "peak concurrency never exceeded capacity under a 6-way race"
  grep -E 'PEAK CONCURRENCY|PASS ' /tmp/bl_race.out | sed 's/^/        /'
else
  bad "race test failed"; cat /tmp/bl_race.out
fi

echo
echo "=== RESULT: $PASS passed, $FAIL failed ==="
rm -rf "$BENCHLOCK_DIR"
[ "$FAIL" -eq 0 ]
