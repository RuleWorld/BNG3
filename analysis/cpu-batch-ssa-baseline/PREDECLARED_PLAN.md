# Predeclared plan — native CPU batch-SSA immigration–death ensemble baseline

Owner: Codex allocation (independent, scoped contribution). Written **before**
executing any stochastic run for this case. Scope: one reproducible native
finite CPU batch-SSA workload, an independent correctness check, and a measured
A/A noise baseline, toward RuleWorld/BNG3 #174. This is a **baseline task**:
no performance tuning, no product-code change, no claim to close #174.

## Workload selection (from the existing benchmark manifest)

The maintained benchmark manifest (`bench/README.md`, `bench/baseline.json`
`meta.ssa_batch`) enumerates the measured native CPU batch-SSA workloads as
`isomerization` and `gene_expr_simple`; both already have throughput, RSS and
correctness evidence. The immigration–death CTMC is **not** in that manifest as
a benchmark workload — it appears only as a correctness case elsewhere
(`analysis/c-jax-cpu` for the JAX backend, `tests/python/test_cpu_batch_ssa_moments.py`
for moment plumbing). It therefore has **no** native CPU batch-SSA throughput,
startup, RSS or A/A noise measurement. It is the nearest uncovered analytic
case and is chosen here.

Model (zero-order creation + first-order decay, mass action, real input class):

```
0 -> A()  k_on = 2.0
A() -> 0  k_off = 0.5
A(0) = 0
observable: Molecules CountA A()
```

## Independent analytic law (no BNG3 call)

Linear immigration–death with `A(0)=0` has the closed form
`A(t) ~ Poisson(lambda(t))`, `lambda(t) = (k_on/k_off)(1 - exp(-k_off t))
= 4 (1 - exp(-0.5 t))`. Hence the transient **mean and variance are equal**:
`E[A(t)] = Var[A(t)] = lambda(t)`, and `A(infty) ~ Poisson(4)`. The Poisson
CDF is evaluated from `exp(-lam) lam^i / i!` using `math` only. Nothing in the
oracle invokes BNG3 or a native engine.

## Predeclared execution parameters (fixed before running)

| Parameter | Value |
|---|---|
| Entry point | `bionetgen._bionetgen_cpp.simulate_batch_ssa_cpu` (with `build/cpp` + `python` on `sys.path`, matching `tests/test_batch_ssa_statistical_parity.py`) |
| Initial population | `A(0) = 0` |
| Horizon / grid | `t_end = 20.0 s`, `n_steps = 20` (grid 0,1,...,20; ~10 relaxation times, at stationarity at the final point) |
| Base seed | `20261119` (per-trajectory seed `base_seed + trajectory`, a documented property of the pool) |
| Ensemble size | `batch_size = 20000` trajectories |
| Thread count (primary) | `threads = 1` (single worker; deterministic, isolates host noise) |
| Thread count (supplemental) | `threads = 0` (hardware concurrency) — one observation only, not part of the A/A statistic |
| Warmups | 2 untimed full invocations, discarded before measurement |
| Measurement repetitions | 7 interleaved A/A rounds (14 measured invocations). Arm order alternates each round (A→B on odd rounds, B→A on even), following `benchmarks/batch_ssa/run_ab.sh`. Both arms use the **identical** build. |
| Startup measure | `model_prep_time_ms` from the metrics dict |
| Warm throughput measures | `sim_time_ms`, `trajectories_per_sec_sim`, `events_per_sec_sim` from the metrics dict |
| Peak RSS | `resource.getrusage(RUSAGE_SELF).ru_maxrss`; bytes on Darwin, KiB on Linux (converted to bytes). Cross-checked with `/usr/bin/time -l` (Darwin) / `-v` (Linux) captured in the replay log. Units and method recorded in the artifact. |

## Statistical controls (reused from the project, not invented here)

- **Transient mean:** per timepoint `t > 0`, `Z(t) = (mean(t) - lambda(t)) /
  (sd(t)/sqrt(N))`; require `max |Z| <= 5.0` (`MEAN_Z_LIMIT`,
  `tests/test_batch_ssa_statistical_parity.py`).
- **Transient variance:** per timepoint `t > 0`, `sample_var(t)/lambda(t)`
  in `[0.90, 1.10]` (`VARIANCE_RATIO_MIN/MAX`, same file).
- **Stationary distribution:** DKW bound at `alpha = 1e-3` (`KS_ALPHA`, same
  file): `bound = sqrt(ln(2/alpha)/(2N))`; require empirical-CDF vs Poisson(4)
  KS statistic `<= bound`.
- **Wrong-law power control (diagnostic):** KS against Poisson(6) must exceed
  the DKW bound, showing the check can reject a wrong law at this budget.
- **Invariant:** `CountA >= 0` for every trajectory at every timepoint.
- **A/A noise statistic:** per round `r = (A - B) / ((A + B)/2)` for each of
  `model_prep_time_ms` and `trajectories_per_sec_sim`; report per-round signed
  values, median, and max `|r|`, plus coefficient of variation across all 14
  reps. Both arms are the same build, so any nonzero difference is noise, not
  a code effect. Context threshold: the host's documented ~11% resolution
  floor (`bench/README.md`). An A/A spread above that is reported as a noisy
  outcome, not hidden.

## Decision rule and scope

The correctness claim is limited to the transient mean, transient variance and
stationary distribution of `CountA` for this immigration–death input at the
fixed revision, seed and budgets above. A retained failure is reported as a
concrete finding, never relabelled by changing seed, ensemble, horizon, alpha,
law or tolerance. A/A results characterize noise on each host separately
(Apple local, Linux CI); timings are **not** generalized across hosts, backends
or GPU. This baseline alone cannot close #174's `release-benchmarks`,
`release-benchmark-correctness` or `release-obligation-174` clauses.
