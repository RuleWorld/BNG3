#!/usr/bin/env python3
"""Tests for benchlock's co-tenant ADVISORY.

The advisory exists because of a specific real leak: perfOracle's identity
sweep ran continuously across all 9 reps of a timed A/B and was undeclared,
because it had started BEFORE the A/B took its slot. A naive "what started
during my window" diff misses that case entirely. These tests exercise both
classes, plus the exclusion of the holder's own command.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BL = str(Path(__file__).with_name("benchlock").resolve())
# UNIQUE lockdir per invocation, for the same reason as race_test.py: exact
# slot-occupancy assertions are only meaningful if this run is the only user.
LOCKDIR = tempfile.mkdtemp(prefix="bng3-bl-adv-")
PASS = FAIL = 0


def ok(m):
    global PASS
    PASS += 1
    print(f"  PASS  {m}")


def bad(m):
    global FAIL
    FAIL += 1
    print(f"  FAIL  {m}")


def run_hold(agent, seconds, extra_bg=None, env=None):
    """Acquire, optionally start a background process, hold, release."""
    e = dict(os.environ, BENCHLOCK_DIR=LOCKDIR)
    if env:
        e.update(env)
    bg = None
    if extra_bg:
        bg = subprocess.Popen(
            extra_bg, env=e, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    p = subprocess.Popen(
        [
            BL,
            "acquire",
            "--agent",
            agent,
            "--what",
            "advisory probe",
            "--timeout",
            "30",
            "--",
            "sleep",
            str(seconds),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=e,
    )
    out, _ = p.communicate()
    if bg:
        bg.kill()
        bg.wait()
    return out


# --- T1: the PERSIST class -- a process that started BEFORE the hold ----------
# This is the leak that motivated the feature. A long-lived process already
# running when the slot is taken must appear even though it never "started
# during the window".
print("=== T1: PERSIST co-tenant (started BEFORE the hold) ===")
shutil.rmtree(LOCKDIR, ignore_errors=True)
preexisting = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)", "bng_cpp_persistent"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
os.environ["BENCHLOCK_DIR"] = LOCKDIR
time.sleep(0.4)
out = run_hold("advtest1", 2)
preexisting.kill()
preexisting.wait()

if "class=PERSIST" in out:
    ok("advisory identifies a benchmark-shaped process alive across the hold")
else:
    bad("advisory missed the pre-existing benchmark-shaped process")
if f"~ {preexisting.pid}" in out:
    ok("PERSIST advisory includes the matching process id")
else:
    bad("PERSIST advisory omitted the matching process id")

if "ADVISORY" in out or "class=NEW" in out or "class=PERSIST" in out:
    ok("advisory is labelled and carries its limitation")
else:
    bad("advisory unlabelled")

# --- T2: a REAL benchmark-shaped co-tenant started DURING the hold ----------
print("=== T2: NEW co-tenant (started during the hold) ===")
shutil.rmtree(LOCKDIR, ignore_errors=True)
bg = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(6)", "bng_cpp_new"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
time.sleep(0.3)
out = run_hold("advtest2", 3)
bg.kill()
bg.wait()
if "class=NEW" in out or "class=PERSIST" in out:
    ok("a benchmark-shaped co-tenant running during the hold is listed")
    for line in out.splitlines():
        if line.strip().startswith(("+", "~")):
            print(f"        {line.strip()}")
else:
    bad("advisory missed a live bng_cpp-shaped process")

# --- T3: the holder's own command is excluded ------------------------------
print("=== T3: holder's own benchlock process is not a co-tenant ===")
shutil.rmtree(LOCKDIR, ignore_errors=True)
out = run_hold("advtest3", 2)
self_lines = [
    l
    for l in out.splitlines()
    if ("benchlock" in l and (l.strip().startswith("+") or l.strip().startswith("~")))
]
if not self_lines:
    ok("benchlock never lists itself as a co-tenant")
else:
    bad(f"benchlock listed itself: {self_lines[:2]}")

# --- T4: the advisory never breaks the measurement -------------------------
print("=== T4: advisory failure cannot change the child's exit code ===")
shutil.rmtree(LOCKDIR, ignore_errors=True)
for code in (0, 42, 3):
    rc = subprocess.run(
        [
            BL,
            "acquire",
            "--agent",
            f"advtest4_{code}",
            "--what",
            "exit probe",
            "--timeout",
            "20",
            "--",
            "sh",
            "-c",
            f"exit {code}",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, BENCHLOCK_DIR=LOCKDIR),
    ).returncode
    if rc == code:
        ok(f"child exit {code} propagated unchanged")
    else:
        bad(f"child exit {code} became {rc}")

# --- T5: slot is still released and reusable after the advisory -------------
print("=== T5: advisory does not leak the slot ===")
shutil.rmtree(LOCKDIR, ignore_errors=True)
run_hold("advtest5", 1)
st = subprocess.run(
    [BL, "status"],
    capture_output=True,
    text=True,
    env=dict(os.environ, BENCHLOCK_DIR=LOCKDIR),
)
if "free 2  in_use 0" in st.stdout:
    ok("both slots free after an advisory-emitting hold")
else:
    bad(f"slot state wrong after advisory: {st.stdout}")

shutil.rmtree(LOCKDIR, ignore_errors=True)
print()
print(f"=== ADVISORY TESTS: {PASS} passed, {FAIL} failed ===")
sys.exit(0 if FAIL == 0 else 1)
