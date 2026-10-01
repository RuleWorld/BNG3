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
# Wrap a measurement. This BLOCKS if both slots are busy, and holds the slot
# for the command and everything it spawns.
tools/benchlock/benchlock acquire \
    --agent <name> --what "<what you are measuring>" --worktree "$PWD" \
    -- python3 bench/run_bench.py --reps 5

# Inspect without taking anything.
tools/benchlock/benchlock status     # capacity, per-slot holder, age
tools/benchlock/benchlock holders    # JSON lines: agent, what, worktree, pid, since
```

Exit codes: `0` acquired (or the child's own code, when wrapping a command),
`2` timed out waiting, `3` usage error, `127` command not found.

Environment: `BENCHLOCK_MAX` (default 2), `BENCHLOCK_DIR` (default
`/tmp/bng-bench-lock`), `BENCHLOCK_POLL` (default 2.0 s).

## Protocol

1. Run `acquire`. It blocks if full.
2. **Once it prints `acquired slot.N`**, announce that you are live, including
   the slot number.
3. Announce again when it finishes, so the slot frees.

If you merely want to warn people you are waiting, say *queued* — that is a
different message. **Never announce a benchmark as live before you hold the
slot**: announcing intent first makes the channel over-report concurrency, and
every reader has to guess whether an announcement means running or waiting.

## The co-tenant advisory

On release, every holder receives a `BENCHLOCK_COTENANT` block listing processes
it should **review** before reporting:

- `class=NEW` — started during your hold.
- `class=PERSIST` — alive at release *and* already alive when you acquired, so
  it may have started **before** you took the slot.

`PERSIST` exists because a start-time diff alone misses the common case. A
long-running correctness sweep that began before your A/B acquired its slot
never "starts during the window", yet loads the machine throughout it.

This is **advisory**. It judges nothing and blocks on nothing. It matches on
process name and worktree path, so it is deliberately over-inclusive — a reader
can dismiss a line in a second but cannot recover a process that was never
shown. A `class=NONE` result means nothing matched, **not** that you were
alone.

## The obligation the advisory supports

Declaring every co-tenant — **including your own processes you classified as
correctness work** — is what makes a timing report interpretable. A reader who
knows there were three co-tenants can weigh the number; a reader who was told
one cannot. That is the failure the advisory exists to prevent.

## Design notes

**`fcntl.flock`, not `mkdir`.** A directory lock goes stale when the holder
dies, and on a host where agents are routinely culled and replaced that wedges
the protocol permanently. The kernel releases `flock` when the descriptor closes
or the process dies, for any reason. A crashed holder cannot block anyone.

**Release on observed absence of compiler processes, never on a self-report.**
"Who is holding slot 1" is answered by `ps` plus `lsof` on each holder's working
directory — not by asking.

**SIGPIPE is caught, not defaulted.** Setting `SIGPIPE` to `SIG_DFL` to silence a
`BrokenPipeError` looks like a tidy fix and is much worse: it turns a benign
closed pipe into process death *mid-hold*, so a process can die while holding a
slot. The advisory code comments this because it was tried and reverted.

## Tests

```sh
tools/benchlock/run_tests.sh       # 21 assertions
tools/benchlock/advisory_test.py   # 9 assertions
tools/benchlock/race_test.py       # concurrency invariant under a 6-way race
```

All three use a **unique lock directory per invocation**. That is not
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
