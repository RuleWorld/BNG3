# benchlock — host-level exclusion for timing-sensitive benchmarks

`benchlock` caps how many **timing-sensitive benchmarks** run at once on one
host, across every worktree and every agent.

It is not a build-slot system and does not replace one. See *What this does not
do* below.

## The problem it solves

Measurements taken while other work loads the machine are not wrong, they are
**uninterpretable**: a reader cannot tell whether a delta came from the change
or from the co-tenants. On the host this was written for, the 1-minute load
average ranged 23–131 across a session while peak resident memory never moved
and no process ever exceeded its memory cap. The binding constraint was CPU
contention, and it came overwhelmingly from **benchmarks running concurrently**,
not from builds.

## The discriminator

A run needs a slot only if **its result depends on machine timing**.

| needs a slot | does not |
|---|---|
| A/B comparisons, benchmark harness runs, profiling runs, anything whose reported number is a duration | Correctness runs, single-model invocations, `ctest`, determinism censuses |

Counting allocations, instructions retired, subprocess spawns, or event totals
is deterministic and cannot move under load. Those need no slot — and the
exemption must be **stated by declared class**, never quietly folded into a
speedup claim.

Getting this backwards in either direction is costly. An over-broad lock
serialises work that no load could perturb; an absent one produces numbers
nobody can defend.

## Usage

```sh
# Wrap a measurement. This BLOCKS if all slots are busy, and holds a slot until
# the wrapped command exits. The command inherits the flock, so killing the
# benchlock wrapper cannot free the slot while that command still runs.
tools/benchlock/benchlock acquire \
    --agent <name> --what "<what you are measuring>" --worktree "$PWD" \
    -- python3 bench/run_bench.py --reps 5

# Inspect without taking anything.
tools/benchlock/benchlock status     # capacity, per-slot holder, age
tools/benchlock/benchlock holders    # JSON lines: agent, what, worktree, pid, since
```

An `acquire` call without a wrapped command waits for availability and exits;
it does not leave a hold for a later CLI call to release. The lock is tied to
open descriptors in the acquiring process and its descendants.

Exit codes: `0` acquired (or the child's own code, when wrapping a command),
`2` timed out waiting, `3` usage error, `127` command not found.

Environment: `BENCHLOCK_MAX` (default 2), `BENCHLOCK_DIR` (default
`/tmp/bng-bench-lock`), `BENCHLOCK_POLL` (default 2.0 s).

For coordinated acceptance measurements that must run one at a time, every
lane must share the same `BENCHLOCK_DIR` and set `BENCHLOCK_MAX=1` before
starting the wrapper. Build and correctness commands do not need a slot.

## Protocol

1. Run `acquire`. It blocks if full.
2. **Once it prints `acquired slot.N`**, announce that you are live, including
   the slot number.
3. Announce when the wrapped command finishes. A descendant may still hold the
   inherited descriptor; use `status` to confirm the slot is free.

If you merely want to warn people you are waiting, say *queued* — that is a
different message. **Never announce a benchmark as live before you hold the
slot**: announcing intent first makes the channel over-report concurrency, and
every reader has to guess whether an announcement means running or waiting.

## The co-tenant advisory

When the wrapped command exits, every holder receives a `BENCHLOCK_COTENANT`
block listing processes it should **review** before reporting:

- `class=NEW` — started during your hold.
- `class=PERSIST` — alive at the advisory snapshot *and* already alive when you acquired, so
  it may have started **before** you took the slot.

`PERSIST` exists because a start-time diff alone misses the common case. A
long-running correctness sweep that began before your A/B acquired its slot
never "starts during the window", yet loads the machine throughout it.

This is **advisory**. It judges nothing and blocks on nothing. It matches on
process name and checkout path when those appear in the command line. `ps` does
not report process working directories, so a command that hides both its name
and checkout path cannot be identified. If `ps` fails or omits the benchlock
process, the result is `class=ERROR`, never `class=NONE`. A `class=NONE` result
means nothing matched, **not** that you were alone.

## The obligation the advisory supports

Declaring every co-tenant — **including your own processes you classified as
correctness work** — is what makes a timing report interpretable. A reader who
knows there were three co-tenants can weigh the number; a reader who was told
one cannot. That is the failure the advisory exists to prevent.

## Design notes

**`fcntl.flock`, not `mkdir`.** A directory lock goes stale when the holder
dies. The lock is released when the last inherited descriptor closes, including
when the wrapper dies but its measured command is still running. Cleanup closes
the wrapper's descriptor without issuing `LOCK_UN`, because that would unlock
the shared open-file description while a child still has it. Once the last
command or descendant exits, the kernel releases the lock.

`SIGINT` and `SIGTERM` are forwarded to the wrapped command. The wrapper waits
for that command to exit before closing its descriptor. There is no standalone
`release` subcommand: another CLI process cannot release a lock held by the
acquiring process.

`BENCHLOCK_EVENT ACQUIRED` records a successful kernel lock. `COMMAND_EXITED`
records only the direct wrapped command's exit; a descendant may still hold
the lock. Use `status` as the source of truth for slot availability.

`status` probes the kernel lock before showing a holder. The metadata file may
remain after a hold ends; it is ignored while the slot is free and replaced by
the next acquirer. This also keeps useful holder details if a child descendant
still has an inherited descriptor.

**Release on observed absence of compiler processes, never on a self-report.**
"Who is holding slot 1" is answered by `ps` plus `lsof` on each holder's working
directory — not by asking.

**SIGPIPE is caught, not defaulted.** Setting `SIGPIPE` to `SIG_DFL` to silence a
`BrokenPipeError` looks like a tidy fix and is much worse: it turns a benign
closed pipe into process death *mid-hold*, so a process can die while holding a
slot. The advisory code comments this because it was tried and reverted.

## Tests

```sh
tools/benchlock/run_tests.sh       # slot lifecycle, command status, and capacity
tools/benchlock/advisory_test.py   # NEW/PERSIST co-tenant detection
tools/benchlock/race_test.py       # concurrency invariant under a 6-way race
tools/benchlock/test_signal_hold.py # wrapper death cannot unlock a live command
tools/benchlock/test_interrupt_forwarding.py # signals forward; wrapper waits
tools/benchlock/test_advisory_errors.py # ps errors and worktree paths
tools/benchlock/test_descendant_hold.py # direct-command exit can precede slot release
```

All tests use a **unique lock directory per invocation**. That is not
housekeeping. Every assertion in them concerns exact slot occupancy, which is
only meaningful if the run is the sole user of the directory; a shared path
makes concurrent runs fight and report slot leaks that do not exist. This was
a real bug here: eight concurrent suite runs produced eight failures that looked
exactly like a lock leak in `benchlock` and were entirely a fixture-isolation
defect in the tests.

`race_test.py` asserts the invariant that actually matters — **never more than
`MAX` held at any single instant** — not "only `MAX` racers ever win", which is
not an invariant: a holder that finishes legitimately frees its slot for the
next waiter, so with N > capacity all N may eventually acquire.

Verified: 16 simultaneous instances of the full suite on a loaded host, 16/16
clean. Before the isolation fix, 8 concurrent instances produced 8 failures.

## What this does not do

- It does not limit builds, and it does not protect a build from load — a build
  does not need a quiet machine, a benchmark does.
- It does not verify anything. It bounds how many measurements can contaminate
  each other; it says nothing about whether the result is correct.
- It cannot tell you whether an unlisted process was timing-relevant.
