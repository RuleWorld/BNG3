# Performance swarm — trial log

One fixed harness, one fixed baseline, 23 lanes. Every lane proposed a change,
the harness measured it, and the trial was kept or dropped against evidence.
A no-win with numbers is a recorded result, not a failure.

Base commit: `c345f3a`, rebased onto `origin/main` @ `7107b6c`.
Harness: `bench/run_bench.py` (6 weighted components, determinism guards).
Session baseline, this host: composite **min 0.2195 / mean 0.2258 / cv 4.1%** at load1 29.

## Kept

| Lane | Change | Effect |
|---|---|---|
| `SsaPrecompute` | per-trajectory propensity setup hoisted into per-thread scratch; duplicate `mt19937_64` state build removed | −18.6% CPU on `ssa_batch` |
| `JitRhs` | `derivs()` resolves rate-law functions through the `functionIndex_` that `compile()` already builds, instead of a linear scan | 3.57× isolated; −12.9% end-to-end on the dominant ODE fixture |
| `OdeOut` | `.cdat`/`.gdat`/`.bdat` emitted through one accumulation buffer instead of per-value stream insertion | −15 to −26% on `out_write`, byte-identical |
| `PyImport` | package attributes resolved on first access (PEP 562) | `py_import` 0.0844 s → 0.0066 s |
| `NodeStr` | `NodeType` labels built without a per-call `std::stringstream` | direction confirmed; magnitude measured at ~2.5–3.4% of `netgen` CPU against a coin-flip null |
| `Ullmann` | memoized type-equality verdicts in `build_M0`; dropped a dead matrix restore | ~1.2–1.7% of `netgen` CPU, replicated against a coin-flip null |
| `SpeciesList` | O(nodes+edges) verified isomorphism witness before the general search; deferred fingerprint | netgen CPU win, guards identical |

Also landed, as correctness rather than speed: the duplicate `.net` write in
`generate_network` (two full NetWriter passes over a 187 KB network), the
`kon*time()` rate law folding to `rateLaw1 0` in emitted `.net` files, and NaN
byte-identity plus macOS 11/12 compilation in the output emitter.

## Dropped, with the reason

| Lane | Verdict | Why |
|---|---|---|
| `NetgenPlan` | NO-WIN | Plan construction is **0.06%** of generation CPU. `HybridModelGenerator` is 100% cold for the benchmark. |
| `NetWriter` | NO-WIN | Structural ceiling: deleting the file outright moves the composite 3.7%. A working −9% patch was **reverted** as sub-floor. |
| `ReactionRule` | NO-WIN | Both candidates measured *slower* (+1.98%, +4.42% CPU). Reverted. |
| `PatternGraph` | NO-WIN | Its one real candidate measured 6.5–9.5% **slower**; wall clock said the opposite, which was scheduler noise. |
| `BngcoreMem` | NO-WIN | `List`/`Vector` are **0.00%** of netgen allocations. Redirected 54.3% to `Ullmann`. |
| `BatchSsa` | NO-WIN | Pool-side cost is 3.6–13.2%; ceiling 3.8% of composite. Dynamic partitioning effect **withdrawn entirely** — its A/A null ran 51–57%, not the assumed 50%. |
| `OdeStep` | NO-WIN | Its whole region is **0.09%** of the ODE fixture; `euler`/`rk4` are never executed by the harness at all. |
| `CvodeJacobian` | NO-WIN | Fixtures are N=2/2/1 — structurally 100% dense, so sparse Jacobian is a guaranteed loss. Per-species `atol` was **already implemented**. |
| `OdeEval` | NO-WIN | 15-line allocation fix: −7.7 to −8.9% end-to-end despite 59.6% fewer allocations — below the floor. Reverted, diff preserved. |
| `JaxOde` | NO-WIN | ODE is 3.7% of composite; JAX one-shot is 12× **slower** than the CVODE the harness actually pays. |
| `PyLoad` | NO-WIN | Python side is 1.6% of the load path; absolute ceiling 44.7 µs of 6296 µs. |
| `JitRhs` (JIT variant) | not attempted | A true in-process native JIT needs a CMake change, a new dependency, a hand-written libc/libm prelude, per-platform import resolution and a cache. It targets tree-walking dispatch, which is what **remains** after the name-resolution fix, not what was costing the time. |

## Corrections made during the swarm

These are recorded because each one would otherwise have produced a wrong number:

1. **`sample` is unreliable on the LTO release binary** — emits an empty call graph intermittently. Allocation counting (`mem_bench`) and child-CPU time are the trustworthy instruments.
2. **The composite harness reports +12.8% on identical code** when run A/A. Measured null band: **±4.4%**. Every composite delta quoted during the swarm required a null control.
3. **`ab.py --a <integration tree>` is not a baseline** — that tree absorbs other lanes' commits mid-run. Fixed with `--expect-a`/`--expect-b` plus a negative test.
4. **A microbench ratio multiplied by a call count is not an effect size.** This mistake occurred three times independently and each was withdrawn.
5. **Default `max_iter` is 32, not 3.** Any allocation measurement taken at the wrong iteration level measures 0.2% of the real workload.
6. **`tools/memory_allocs/README.md` is wrong** — it reports counts as non-reproducible; at the real workload they are bit-exact across 9 reps and 2 processes.

## Standing limitation

No lane's claim clears the **composite** floor. The largest single component win
is ~18.6% of `ssa_batch`, which is ~6% of composite — under the measured null.
Component-level wins are real and replicated against coin-flip nulls, but the
honest summary is that this swarm improved the components it targeted and did
not measurably move the aggregate score.