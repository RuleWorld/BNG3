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

Every harness run prints `load1=` (1-minute loadavg at start) in its header
and in the `--json` meta (`load1_start`/`load1_end`). Quote it with any
timing taken from this harness, together with how many other timing-sensitive
benchmark processes were live; a bare composite without load context is
unverified. Baseline session for the current metric is in `bench/baseline.json`.

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
84,475,904 B (80.6 MiB)** at load1 128.7 with two build slots active —
inside the 60 s envelope even on this heavily contended host (the v1
4-component run measured 5.83 s at load1 ~13.6). No network access;
stdlib only.
