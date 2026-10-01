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

What it measures (composite = `sum(weight * seconds)`, lower is better):

| component    | weight | path exercised |
|--------------|-------:|----------------|
| `netgen`     |   0.35 | C++ network generation: `bng_cpp bench/fixtures/netgen_egfr.bngl` (`generate_network` only), full process wall; output `.net` sha256 must stay stable across reps |
| `ssa_batch`  |   0.40 | simulation throughput: CPU batch SSA on `models/isomerization.bngl` (200k trajectories, t=20) + `models/gene_expr_simple.bngl` (800k trajectories, t=500), fixed `base_seed=12345`; event counts must stay identical across reps |
| `py_import`  |   0.10 | Python-side: `import bionetgen` timed in a fresh interpreter |
| `py_load`    |   0.15 | Python-side: `bionetgen.load` of the mid-size `models/egfr_net.bngl` plus `BioNetGenModel` property reads (model-block counts must stay stable across reps) |

Editable-install guard: a scikit-build editable install of `bionetgen` on this
host redirects `import bionetgen` to another checkout via a `sys.meta_path`
finder. Every child interpreter removes `sys.meta_path` entries whose type
module starts with `_editable` **before** importing, prepends this worktree's
`python/` and `build/cpp` to `sys.path`, and asserts the imported paths live
inside this worktree (harness fails otherwise).

Determinism: fixed SSA seed, fixed inputs, per-rep interleave; the script
exits non-zero on any component error or guard mismatch. The machine may be
shared with other builds — compare `min` and `stdev`, not single runs.

Baseline for this machine: see `bench/baseline.json` and the PR body.
