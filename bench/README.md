# bench/ — BNG3 fitness harness

One command (from the repo root of any configured worktree):

```bash
python3 bench/run_bench.py --reps 5 --json bench/baseline.json
```

Prerequisites (checked fail-closed at startup):

- an already-configured Release build providing `build/cpp/bng_cpp`:

  ```bash
  cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON_BINDINGS=ON
  cmake --build build
  ```

  (override the binary with `BNG3_BNG_CPP=<path>`); `BUILD_TESTS` is optional.
- a `python3` that can import the `_bionetgen_cpp` extension from `build/cpp`.

## Components and weights (v2 metric)

Composite = `sum(weight * seconds)`, **lower is better**:

| component    | weight | path exercised |
|--------------|-------:|----------------|
| `netgen`     |   0.27 | C++ network generation: `bng_cpp bench/fixtures/netgen_egfr.bngl` (`generate_network` only), full process wall; output `.net` sha256 must stay stable across reps |
| `ssa_batch`  |   0.33 | simulation throughput: CPU batch SSA on `models/isomerization.bngl` (200k trajectories, t=20) + `models/gene_expr_simple.bngl` (800k trajectories, t=500), fixed `base_seed=12345`; event counts must stay identical across reps |
| `ode`        |   0.15 | ODE integration: in-process `simulate_ode` on `models/isomerization.bngl` (t=100, 1000 steps), `models/gene_expr_simple.bngl` (t=1000, 1000 steps) and `bench/fixtures/ode_many_functions.bngl` (150 zero-argument rate functions, t=100, 5000 output steps — the F×output-steps regime where per-step function bookkeeping is visible); final concentration vectors must be identical across reps |
| `out_write`  |   0.10 | output writing: full CLI run of `bench/fixtures/out_write.bngl` (`simulate_ode`, 40001 rows × 8 fields `.cdat`/`.gdat`); both files' sha256 must stay stable across reps |
| `py_import`  |   0.08 | Python-side: `import bionetgen` timed in a fresh interpreter |
| `py_load`    |   0.07 | Python-side: `bionetgen.load` of the mid-size `models/egfr_net.bngl` plus `BioNetGenModel` property reads (model-block counts must stay stable across reps) |

**v1 weights (superseded):** `netgen 0.35, ssa_batch 0.40, py_import 0.10,
py_load 0.15` — that metric had no `ode`/`out_write` components. **v1 and v2
composites are NOT comparable to each other**; a candidate must not be
"regressed" against a composite measured with the other weight set. v1
baseline (commit 528f6d8, 5 reps): composite mean 0.3196 / min 0.3064 /
cv 3.3% (recorded in git history and the PR body). The current metric's
baseline is `bench/baseline.json`.

## Resolution floor (host property, not a code property)

Cross-session composite min drift measured at 0.3275 / 0.3677 / 0.3506
(~11%), one session cv 39.6% from co-tenant load; therefore compare
interleaved same-session A/B against baseline min, never a baseline measured
in a different session. ~11% is a property of this host under contention:
a candidate claiming less than ~11% on the composite must be re-measured
before it can be called a win, and where a lane's own benchmark is more
sensitive for its region, that benchmark still governs — the composite is
for cross-branch comparison, not for replacing a good local benchmark.

Every harness run prints `load1=` (raw 1-minute loadavg at start) in its header
and in the `--json` meta (`load1_start`/`load1_end`). Quote it as a **coarse
band, not a precise reading** — memWatch calibrated the host's loadavg against
a known input and it does not respond within seconds, so treat e.g. 128.7 as
"~100-130 band". Pair any timing from this harness with (a) the loadavg band,
(b) the exact concurrent timing-sensitive process list from
`ps -axo pid,etime,command`, (c) whether the comparison was interleaved in one
session, and (d) peak RSS from `/usr/bin/time -l`. Per-process `%CPU` figures
are unreliable on this host and should not be quoted. The current metric's
baseline is `bench/baseline.json`.

## Which binary and which Python are being scored

- The header prints `_bionetgen_cpp=<path> [worktree | OUTSIDE WORKTREE]`.
  The harness scores the extension found in `build/cpp`; a worktree that has
  not built its own extension is measuring the shared tree's C++ with this
  worktree's Python — the printed path makes that visible rather than silent.
  On this host the shared build (mtime Sep 29 15:08) is behind HEAD by
  exactly one commit, `75b22a7`, which touches only
  `cpp/nfsim/NFinput/NFinput_fromCompiled.cpp`. None of the six components
  exercise NFsim, so that commit does not affect any number this harness
  reports.
- Editable-install guard: a scikit-build editable install of `bionetgen` on
  this host redirects `import bionetgen` to another checkout via a
  `sys.meta_path` finder that runs before `sys.path`. Every child interpreter
  removes `sys.meta_path` entries whose type module starts with `_editable`
  BEFORE importing, prepends this worktree's `python/` and `build/cpp` to
  `sys.path`, and asserts the imported paths live inside this worktree
  (harness fails otherwise). `SKBUILD_EDITABLE_SKIP` does not do this — it is
  a rebuild-recursion marker — so the path assertions are what make it fail
  closed.

Determinism: fixed SSA seed, fixed inputs, per-rep interleave of all six
components; the script exits non-zero on any component error or guard
mismatch (netgen `.net` sha, SSA event counts, ODE final-state digests,
`out_write` `.cdat`/`.gdat` shas, `py_load` model-block counts).

Envelope: the v2 baseline run (5 reps) measured **23.76 s wall, peak RSS
84,475,904 B (80.6 MiB)** in the loadavg ~100-130 band with two `-j4` build
slots active — inside the 60 s envelope even on this heavily contended host
(the v1 4-component run measured 5.83 s in a quiet ~10-20 band). No network
access; stdlib only.

## Generate-only network fixtures

Regenerate the PR42 fixture set and check it against independent Perl BNG2
network generation:

```bash
python3 bench/make_fixtures.py
python3 bench/check_netgen_semantics.py \
  --binary build/cpp/bng_cpp \
  --bng2 /path/to/pinned-bionetgen/bng2/BNG2.pl \
  --preserve-adapters bench/evidence/bng2-adapters \
  --json-report bench/evidence/netgen-semantics.json
```

The checker compares species graphs, reaction multiplicity, observable groups,
and rates with `tests.validation.compare`; it reports oracle rejection as
`UNSUPPORTED`. The 2026-10-03 qualification used RuleWorld/bionetgen revision
`9601746f8884ed19ab2acea49fe87fc4660ace46`: 10 fixtures passed, while
`fceri_ji_gen.bngl` remains unsupported by that oracle because its rule contains
a dangling numbered bond (`Lig(l,l!1)`). The saved evidence keeps the original
fixture, syntax-only block-marker adapter, and exact BNG2 error together.

Measure the four-fixture preset or full 11-fixture corpus with:

```bash
BENCHLOCK_DIR=/tmp/bng-bench-lock BENCHLOCK_MAX=1 \
  tools/benchlock/benchlock acquire --agent netgen --what "network generation A/B" \
  --worktree "$PWD" -- \
  python3 bench/netgen_bench.py --binary /path/to/base/bng_cpp \
    --binary build/cpp/bng_cpp --reps 7 --full \
    --json bench/evidence/netgen-ab.json
```

The order alternates each round; the run fails if any raw `.net` digest varies
across reps or binaries, including `tlbr`. Current main fixed the address-order
cause in `44664f1`. Peak RSS is normalized to bytes before displaying MiB
(macOS `ru_maxrss` is already bytes; Linux reports KiB).

## Seeded SSA A/B qualification

`verify/ab_bench.py` measures fixed-event SSA runs with alternating binary order
and a fresh directory for every simulator child. It records raw `.gdat` and
`.net` hashes, child CPU time, wall time, peak child RSS in bytes, binary/model
hashes, and load-average context in JSON. It exits nonzero and suppresses
throughput tables if either raw output differs between variants or reps.

Run it under the shared timing lock:

```bash
BENCHLOCK_DIR=/tmp/bng-bench-lock BENCHLOCK_MAX=1 \
  tools/benchlock/benchlock acquire --agent perfOracle --what "seeded SSA A/B" \
  --worktree "$PWD" -- \
  python3 verify/ab_bench.py \
    --bin baseline=/path/to/baseline/bng_cpp \
    --bin candidate=build/cpp/bng_cpp \
    --species 150 --events 2000000 --reps 5 \
    --json bench/evidence/ssa-ab.json
```

The benchmark reports full-process CPU throughput, throughput after subtracting
a paired two-event process probe, wall throughput, and per-child peak RSS. The
probe-corrected figure is an estimate; keep the full-process figure and raw
samples with any comparison.

`verify/identity_check.py` runs repository and synthetic seeded cases. Compare
its output trees before timing:

```bash
python3 verify/identity_check.py /path/to/baseline/bng_cpp \
  build/qualification/identity-baseline --only \
  isomerization,gene_expr_simple,edge_dimer,edge_zero_plateau,\
edge_reactant_is_product,edge_negative_rate,edge_chain_wide,edge_ring_long
python3 verify/identity_check.py build/cpp/bng_cpp \
  build/qualification/identity-candidate --only \
  isomerization,gene_expr_simple,edge_dimer,edge_zero_plateau,\
edge_reactant_is_product,edge_negative_rate,edge_chain_wide,edge_ring_long
python3 verify/compare_identity.py build/qualification/identity-baseline \
  build/qualification/identity-candidate
```

The synthetic cases cover identical reactants, zero-rate plateaus, a species
that is both reactant and product, negative-rate selection fallback, and wide
and long reaction chains. The BLBR network retains its source stoichiometry cap
when the identity checker reconstructs the model actions.

## CPU batch SSA pool

`benchmarks/batch_ssa/build_driver.sh` builds the direct CPU-pool measurement
driver against the configured `bng_cpp` libraries. It supports both CMake
Makefiles and Ninja builds. `run_ab.sh` alternates which binary goes first,
checks that baseline and candidate report the same total-event samples, and on
macOS prints each child process's real/user/system time plus peak RSS in bytes
from `/usr/bin/time -l`.

Run a fixed-seed comparison under the shared lock:

```bash
benchmarks/batch_ssa/build_driver.sh "$PWD" build/qualification/batch-current
BENCHLOCK_DIR=/tmp/bng-bench-lock BENCHLOCK_MAX=1 \
  tools/benchlock/benchlock acquire --agent batch-ssa \
  --what "CPU batch SSA A/B" --worktree "$PWD" -- \
  benchmarks/batch_ssa/run_ab.sh \
    build/qualification/batch-baseline \
    build/qualification/batch-candidate 3 \
    --model models/egfr_net.bngl --batch 60 --threads 15 --seed 42 \
    --t-end 10 --n-steps 10 --reps 1 --mode bench
```

Before timing, run each binary with the same configuration and `--mode dump`,
then compare the output files with `cmp`. A dump includes final species,
observables, per-trajectory event counts, and all reported mean/std arrays.
Keep the seed derivation the same in baseline and candidate. The PR58
qualification baseline preserves current per-trajectory seed fixes while
reverting only the integrator-sharing change.

The parity lane is repairing an observable-dependent functional-rate SSA
correctness issue in `michment`. Until that correction passes its independent
gate, do not treat dynamic-functional SSA timings as scientifically qualified.
The fixed-parameter fixtures above do not exercise that rate path.
