#!/usr/bin/env python3
"""Race test for benchlock.

Asserts the INVARIANT that actually matters -- no more than MAX slots are held
at any single instant -- rather than "only MAX racers ever win", which is not
an invariant: a holder that finishes legitimately frees its slot for the next
waiter, so with 6 racers and 2 slots all 6 may eventually acquire.

The trace covers leaf children, where direct-command exit precedes the wrapper
closing the inherited lock descriptor. COMMAND_EXITED is not a claim that a
descendant-free kernel slot was already released; test_descendant_hold.py checks
the longer inherited-descriptor case directly through status probes.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

BL = str(Path(__file__).with_name("benchlock").resolve())
MAX = 2
RACERS = 6
# UNIQUE lockdir per invocation. Two concurrent runs of this test must not
# share a directory: every assertion here is about exact slot occupancy, which
# is only meaningful if this process is the only user. A fixed path made
# concurrent runs fight and report slot leaks that do not exist.
LOCKDIR = tempfile.mkdtemp(prefix="bng3-bl-race-")
HOLD = 3.0


env = dict(os.environ, BENCHLOCK_DIR=LOCKDIR, BENCHLOCK_MAX=str(MAX))
shutil.rmtree(LOCKDIR, ignore_errors=True)

results = {}
out_lines = {}
barrier = threading.Barrier(RACERS)
EVENT = re.compile(
    r"BENCHLOCK_EVENT (\w+) slot=(\d+) agent=(\S*) pid=(\d+) epoch=([\d.]+)")


def racer(i):
    barrier.wait()  # maximise simultaneity
    p = subprocess.Popen(
        [BL, "acquire", "--agent", f"race{i}", "--what", f"race {i}",
         "--timeout", "60", "--", "sleep", str(HOLD)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    out, _ = p.communicate()
    out_lines[i] = out
    results[i] = p.returncode


threads = [threading.Thread(target=racer, args=(i,)) for i in range(1, RACERS + 1)]
for t in threads:
    t.start()
for t in threads:
    t.join()

events = []
unexpected = []
for i, out in out_lines.items():
    for line in out.splitlines():
        m = EVENT.search(line)
        if m:
            kind, slot, agent, pid, epoch = m.groups()
            if kind not in ("ACQUIRED", "COMMAND_EXITED"):
                unexpected.append(kind)
                continue
            events.append((float(epoch), 1 if kind == "ACQUIRED" else -1,
                           int(slot), agent))

if not events:
    print("  FAIL  no BENCHLOCK_EVENT lines emitted at all")
    sys.exit(1)

# Tie-break deterministically: at equal timestamps a command exit must be
# processed before an acquire, otherwise a directly handed-off slot would be
# double-counted for an instant.
events.sort(key=lambda e: (e[0], e[1]))

cur = peak = 0
peak_at = None
per_slot = {}
violations = []
for ts, delta, slot, agent in events:
    cur += delta
    per_slot[slot] = per_slot.get(slot, 0) + delta
    if cur > peak:
        peak, peak_at = cur, ts
    if cur > MAX:
        violations.append((ts, cur, agent))
    if cur < 0:
        violations.append((ts, cur, f"NEGATIVE after {agent}"))

acq = sum(1 for e in events if e[1] == 1)
rel = sum(1 for e in events if e[1] == -1)
winners = sum(1 for r in results.values() if r == 0)
timedout = sum(1 for r in results.values() if r == 2)

print(f"racers              : {RACERS}   capacity: {MAX}   hold: {HOLD}s")
print(f"acquire events      : {acq}")
print(f"command-exit events : {rel}")
print(f"exit 0 (got a slot) : {winners}")
print(f"exit 2 (timed out)  : {timedout}")
print(f"PEAK CONCURRENCY    : {peak}  (must never exceed {MAX})")
print(f"per-slot final count: {per_slot}  (each slot must end at 0)")
print()

ok = True
if peak > MAX:
    print(f"  FAIL  peak concurrency {peak} exceeded capacity {MAX}")
    ok = False
else:
    print(f"  PASS  peak concurrency never exceeded capacity ({peak} <= {MAX})")

if any(v[0] for v in violations):
    print(f"  FAIL  invariant violations: {violations[:5]}")
    ok = False
else:
    print("  PASS  no concurrency violations and no negative count")

if unexpected:
    print(f"  FAIL  unexpected lifecycle events: {unexpected}")
    ok = False

if all(v == 0 for v in per_slot.values()):
    print("  PASS  every slot balanced (acquires == child exits per slot)")
else:
    print(f"  FAIL  unbalanced command lifecycle counts: {per_slot}")
    ok = False

if winners + timedout != RACERS:
    print(f"  FAIL  unexpected exit codes: {results}")
    ok = False
else:
    print(f"  PASS  all {RACERS} racers exited 0 or 2 (waited rather than overcommitting)")

if timedout:
    print(f"  NOTE  {timedout} racer(s) timed out, which is the protocol working: "
          f"they waited instead of running a third concurrent benchmark")
else:
    print("  NOTE  the queue drained inside the timeout, so nobody had to wait; "
          "capacity was still never exceeded")

shutil.rmtree(LOCKDIR, ignore_errors=True)
print()
print("RACE TEST:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
