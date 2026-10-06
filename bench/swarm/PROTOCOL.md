# Performance swarm protocol (karpathy/autoresearch loop)

One fixed harness. One fixed baseline. Every agent proposes a patch, the
harness measures it, and the trial is either **kept** or **reverted** against
measured evidence. A no-win is a valid, recorded result — report it, do not
invent a win.

## The harness

`bench/run_bench.py` — six weighted components, composite = `sum(weight*seconds)`,
lower is better. Determinism guards on every run: `.net` sha256, SSA event
counts, ODE final-state digests, `.cdat`/`.gdat` shas, model-block counts.

```bash
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON_BINDINGS=ON
cmake --build build
python3 bench/run_bench.py --reps 5
```

Session baseline, `main` @ `c345f3a`, this host, `load1=29`:

| component | median s | weight | share of composite |
|---|---:|---:|---:|
| netgen | 0.4145 | 0.27 | 50% |
| ssa_batch | 0.2774 | 0.33 | 41% |
| ode | 0.0551 | 0.15 | 4% |
| out_write | 0.0362 | 0.10 | 2% |
| py_import | 0.0844 | 0.08 | 3% |
| py_load | 0.0044 | 0.07 | 0.3% |
| **COMPOSITE** | **0.2258 mean / 0.2195 min / cv 4.1%** | | |

**netgen and ssa_batch are 91% of the composite.** Effort spent elsewhere moves
the score least; effort there moves it most. That is the ordering to spend
against, not a target to game.

## The resolution floor

This host drifts **~11% between sessions** under co-tenant load (measured; see
`bench/README.md`). Consequences, non-negotiable:

- A number from your session is not comparable to a number from another
  session. Only paired A/B inside one session is evidence.
- A composite delta under ~11% is **not** a win and **not** a regression. Say so
  and stop; do not round it up into a claim.
- Quote `load1=` with every timing. Re-measure anything that looks marginal.
- Prefer the lane's own benchmark when it is more sensitive than the composite
  for that region.

`bench/ab.py` runs two worktrees alternately in one session and pairs the
rounds. Use it for anything you claim:

```bash
python3 bench/ab.py --a /path/baseline-tree --b <your tree> --rounds 4
```

It exits non-zero on any guard mismatch. **A guard mismatch is a correctness
failure and a hard stop** — do not paper over it.

## Method

1. **Measure before you touch anything.** Profile the component you own on its
   own, quote the self-time percentage, and say what you expect to win. An
   agent that cannot name the hotspot it is attacking should not start.
2. **One change, one hypothesis.** Smallest diff that tests the hypothesis.
3. **Re-measure paired** against the pre-change build of the same tree.
4. **Guards must be identical** to baseline before any timing claim counts.
5. **Record the trial**: slice, hypothesis, hotspot %, measured delta, verdict.
6. **Correctness beats the benchmark.** A change that wins but changes
   semantics is a failed trial, not a win.

## Rules that are not negotiable

- **Stochastic semantics.** Any change to SSA must preserve the seeded
  trajectory for a given seed, or be an explicitly documented intentional
  change. Performance never buys a different sample.
- **No new dependencies** in the core (`pyproject.toml` runtime deps stay
  `numpy`, `click`, `packaging`). An optional extra that is off by default is
  acceptable; a required dependency is not.
- **File ownership is exclusive.** Other agents own the other files, and other
  agents own the *other line regions of the same file*. Stay inside your
  region; do not reformat, reorder, or "tidy" outside it.
- **YAGNI.** No scaffolding for a future need, no abstraction with one
  implementation, no config for a value that never changes. Reuse what exists.
- **Unsupported stays unsupported.** Do not turn an unsupported construct into
  a nominal approximation to raise a number.
- **No dead code left behind.** If you supersede something, remove it.

## Reporting

Report as plain data, no narrative:

```
slice:        <name>
files:        <paths>
hypothesis:   <what, and the self-time % that says it should pay>
change:       <2-4 lines>
correctness:  <what you ran; guards identical: yes/no>
measured:     <lane> A=<x> B=<y>  <+/-%>  load1=<n>
verdict:      KEEP | REVERT | NO-WIN (<reason>)
```

If you cannot measure, say so and report NO-WIN. That is a real result and it
is cheaper than a wrong one.