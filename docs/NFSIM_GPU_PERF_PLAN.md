# NFsim performance plan: general optimization + GPU path

Branch: `plan/nfsim-gpu-perf` (from PR 26 head `22ded21`).
Scope: (A) review of PR 26 with must-fix items, (B) general (CPU) NFsim
optimizations, (C) a GPU plan for NFsim. Evidence from two read-only scouts
plus direct inspection of `cpp/engine/MetalBatchSsa.mm`,
`cpp/engine/OdeIntegrator.cpp`, `cpp/actions/ActionDispatch.cpp`,
`cpp/nfsim/NFcore2/`.

Key framing: **PR 26 is network SSA, not NFsim.** It accelerates batched
Gillespie trajectories over an already-generated fixed reaction network (one
GPU thread per trajectory over flat CSR arrays). NFsim is network-free SSA:
the per-event cost is dynamic graph matching + incremental membership
maintenance over a pointer-linked particle graph. The two share only the outer
SSA skeleton. Nothing in the PR 26 kernel transfers directly to the NFsim
event loop; what transfers is trajectory-level batch parallelism, flat
buffers, cheap per-trajectory RNG, and the fail-closed dispatch pattern.

A second fact shapes the plan: `cpp/nfsim/NFcore2/` already contains a flat,
compiled network-free engine (`bng_nfcore2` target) — `SimulationState` SoA,
`MatcherProgram`/`TransformProgram` bytecode, Fenwick `HierarchicalScheduler`,
and an `Engine` whose copy shares immutable executable metadata while owning
independent trajectory state (`engine.hh`). That is the GPU on-ramp, not the
`NFcore` pointer graph.

Per AGENTS.md: measure before optimizing (benchmark first, one change at a
time, correctness tests + parity evidence each step); unsupported stays
explicit, never approximated.

## A. PR 26 review

Verdict: correct scope and honest evaluation. Fail-closed flattening,
untouched NFsim/Atomizer/semantics, Apple-only guards with CPU-pool fallback,
and real statistical validation (trajectory Z-tests, KS, analytical
chi-square) are all the right calls. The `kGpuMinReactions=50` /
`kGpuMinBatch=1000` dispatch thresholds are grounded in measured data.
Not yet merge-safe — one live bug and several smaller items below.

### A1. Must fix: GPU path `.cdat` OOB read (live bug)

`MetalBatchSsa.mm::fillDoubleFields` builds `meanSpecies`/`stdSpecies` with
**one row** (final-state mean only), while `timePointsDouble` has `T` rows.
`OdeIntegrator::integrateBatchSSA` assigns that to
`OdeResult::concentrations`, and `ActionDispatch.cpp:1441` calls
`writeOutputFiles(..., opts.printCDAT=true, ...)` for batch results.
Both the text `.cdat` loop (`OdeIntegrator.cpp:~1695`) and
`writeBinaryOutputFiles` (`~1785`) index `result.concentrations[step]` for
`step` in `[0, T)` — heap OOB read for every GPU batch run with default
`print_CDAT`, and in binary mode too. The CPU-pool fallback returns a full
`T×S` grid, so this is also a backend-observable shape inconsistency:
`result.concentrations.size()` is `1` vs `T` depending on which backend won
the dispatch.

Options (pick one before merge):
1. Skip `.cdat` for batch runs (document: batch mode emits mean `.gdat` +
   `.bdat` only), and guard both writers against `concentrations.size() !=
   timePoints.size()`. Cheapest; matches the PR's stated contract.
2. Record the full species mean grid on device (`B×T×S` floats — 726 MB for
   EGFR at B=10k; only viable with on-device Welford accumulation into a
   `T×S` mean/M2 buffer, which is the right fix if `.cdat` output is
   required).

Either way add a regression test: BNGL `simulate_ssa({batch_size=>...})`
with default flags on a model that takes the GPU path, plus a shape
assertion (`concentrations.size() == timePoints.size()` or explicit
documented exemption) in `tests/test_batch_ssa_statistical_parity.py`.

### A2. Should fix: double propensity evaluation per event

The MSL kernel evaluates `compute_prop(r)` over all `R` reactions twice per
event — once for `totalPropensity`, once for selection. For EGFR (3749
reactions) that is ~7.5k propensity evals per event. Cache pass 1 into a
thread-local buffer (registers for small R, threadgroup/shared memory above)
and reuse for selection; expected ~1.5–2× kernel speedup on large networks.
Same applies to `integrateSSA`'s full `recomputePropensities()` on CPU, but
that is out of PR scope — note it as network-SSA CPU work (dependency-graph
propensity update instead of O(R) recompute).

### A3. Minor

- MSL pipeline compiled per `MetalBatchSsaSimulator` construction
  (`Impl` ctor: `newLibraryWithSource` + pipeline state). Cache the pipeline
  per `MTLDevice` (process-wide, keyed by shader string hash); model buffers
  stay per-instance.
- RNG doc mismatch: `MetalBatchSsa.hpp` documents
  `state_0 = base_seed + batch_size`, code does
  `rng.init(123456789 + baseSeed, trajId)`. Fix the comment; the code's
  per-trajectory stream separation is the property that matters.
- `float32` time/rates: `SimParams.tStart/tEnd` and `rateConstants` are
  float. Fine for the evaluated models, but add a fail-closed guard for
  `tEnd > 1e6` or rate dynamic range beyond float32 (or promote to double
  and remeasure — unified memory makes the bandwidth cost small).
- Host-side mean/std reduction is single-threaded `O(B·T·G)`. Negligible at
  current sizes; parallelize if species-grid accumulation (A1-option-2)
  lands.
- `memoryUsageBytes` uses `sizeof(OdeIntegrator)` — meaningless; either
  compute real buffer sizes or drop the field.
- Metal-only is correctly documented as intentional; the portable-backend
  abstraction belongs to phase 4 of part C, not this PR.

## B. General NFsim optimizations (CPU, backend-agnostic)

Ranked by scout evidence from the per-event path
`System::sim → getNextRxn → ReactionClass::fire → transform →
updateRxnMembership → TemplateMolecule::compare → update_a`
(`cpp/nfsim/NFcore/system.cpp`, `reactionClass.cpp`, `moleculeType.cpp`,
`templateMolecule.cpp`, `NFreactions/`). Do these before any NFsim GPU work:
each is independently shippable and each de-risks the GPU path by simplifying
the event loop.

### B0. Benchmark harness first (prerequisite, not optional)

No optimization without a profile. Add an NFsim event-rate benchmark over
representative models (small particle-heavy, rule-heavy, large-complex,
stiff) recording events/sec, matcher evaluations/event (`NFcore2::Engine`
already counts `matcher_evaluations`), and allocation counts. Reuse the
`BatchSsaMetrics` timing-split style (prep/sim/transfer). Gate every B-item
on measured improvement against this harness plus full `ctest` and native
NFsim parity (RuleWorld/nfsim pinned commit as oracle, never BNG3-vs-BNG3).

### B1. Scope membership re-match to affected rules

`MoleculeType::updateRxnMembership` / `updateConnectedRxnMembership`
(`moleculeType.cpp:729/1138`) re-match products against candidate reactions
via recursive `TemplateMolecule::compare` (`templateMolecule.cpp:1042`).
Cost scales as products × rules-per-type. Exploit the existing dependency
signals — connected-reaction sets and `canSkipIndirectMembership`
(`energyPattern.hh`) — plus deferred/batched membership updates already
present in `reactionClass.cpp`, so each product re-matches `O(affected)`
rather than `O(all)`. Expected largest single win on rule-heavy models.

### B2. Fast selection: replace linear scan

`DirectSelector::getNextReactionClass` (`directSelector.cpp:486`) scans
`O(R)` per event (block-sparse/active-bit helps only when many rules are
inactive). `NFcore2/scheduler.hh` already implements a Fenwick
`HierarchicalScheduler` with `O(log)` sample/update. Either backport it to
`NFcore` selectors or route performance-sensitive NFsim runs through
`NFcore2`. Measure both; keep the `NFcore` path bit-compatible.

### B3. Skip BFS + observable relabel when topology is unchanged

`ReactionClass::fire` (`reactionClass.cpp:446`) pays
`traverseBondedNeighborhood` BFS (`molecule.cpp:843`) plus observable
remove/add (`observable.cpp`) on every event. State-change-only firings
(bind/unbind-free) need neither complex dedupe nor canonical relabeling:
branch on transformation type, cache canonical (nauty) labels per
unmodified complex, and skip species-observable loops when no species
observable depends on the touched types.

### B4. Kill per-event allocation

`Molecule` ctor `new[]`s 4+ arrays, `MappingSet` churn, per-fire product
vectors, `unordered_set` complex dedupe. Pool molecule arrays and mapping
sets (free lists sized by high-water mark), reuse fire scratch vectors, and
replace per-fire `unordered_set` with versioned generation marks. Count
allocations/event in the B0 harness; drive to zero on the hot path.

### B5. RNG: faster generator, same stream discipline

Per-`System` MT19937 (`NFutil/nfsim_rng.h`) with two streams (`rng_` for
reaction choice, `mapping_rng_` for molecule/mapping choice). MT19937 is
slow to seed and heavy per draw; move to PCG32/xoshiro with one instance
per stream, preserving the two-stream separation (PR 26's single-PCG32
design must NOT be copied blindly — collapsing the streams changes the
sampled distribution vs the CPU oracle and breaks parity).

### B6. Time-dependent-function path

The TDF branch recomputes all `update_a` per event. Attach dependency
tracking (which rules read which functions/observables) so only dependent
rules update. Fail closed where functions defeat static analysis.

## C. NFsim GPU plan

### C1. Why PR 26 does not transfer (established, do not relitigate)

| PR 26 technique | NFsim applicability |
|---|---|
| Fixed CSR network flatten | None — no species/reaction enumeration exists (`System` holds `MoleculeType*`/`ReactionClass*` rules + particle lists) |
| One-thread-per-trajectory kernel | Partial — valid for ensemble/sweep batching (see C3-phase-1) |
| Two-pass dense propensity | Does not transfer — propensities live in reactant-list trees, maintained incrementally |
| `local_y[64]` register cache | Does not transfer — state is a dynamic pointer graph, uncoalesced and unbounded |
| Single PCG32 per thread | Adapt, don't copy — NFsim needs two streams (C-B5) |
| Dispatch thresholds (50 rxns, 1000 batch) | Concept transfers, constants don't — crossover lives in (rules × particles × degree × match-cost) space, must be remeasured |
| Static + per-run buffers | Pattern transfers with a device pool allocator — firing creates/deletes molecules/mappings/complexes, so fixed `B×S` buffers are impossible; needs capped pools + overflow-to-CPU fallback |

Fundamental blockers for a direct port: recursive pointer-chasing match
(`TemplateMolecule::compare`, BFS, nauty labels) is maximally SIMT-divergent;
MSL has no `new`/exceptions/unbounded recursion; and the mapping tables ARE
the propensity array, so device-side incremental coherence is the whole
problem PR 26 never faces.

### C2. The on-ramp is NFcore2, not NFcore

`NFcore2` already did the CPU-side flattening a GPU needs: SoA
`SimulationState`, bytecode `MatcherProgram`/`TransformProgram`
(iterative-interpretable, unlike recursive `compare`), Fenwick scheduler
(parallel-reduction-friendly), and `Engine` copy semantics = replica
 parallelism with shared immutable metadata. Concretely, this means the GPU
work starts from `NFcore2`, and B1–B4 (affected-rule scoping, Fenwick
selection, topology-change branching, pooling) are shared prerequisites that
pay off on CPU regardless.

### C3. Phases

**Phase 1 — NFsim ensemble batching on CPU (API + validation without GPU).**
Mirror PR 26's contract for network-free runs: `batch_size` on the NFsim
action path, per-replica `Engine` copies (or `System` clones) over a thread
pool, Welford mean/M2 accumulation, `.gdat` mean + `.bdat` std-dev. Reuses
the PR 26 statistical harness (Z/KS/analytical) with native NFsim as oracle.
Ships standalone value (sweeps, UQ) and pins the API the GPU backend must
honor, including the A1 shape contract (`concentrations` rows ==
`timePoints` rows on every backend).

**Phase 2 — Targeted device kernels with fail-closed fallback.**
Profile Phase 1 to find the dominant kernel-shaped work per model class
(candidates: iterative matcher evaluation over candidate lists, propensity
reduction, observable accumulation). Ship one kernel at a time behind the
PR-26-style dispatcher (capability probe + remeasured crossover thresholds +
`try/catch` CPU fallback). Reject list starts large (local functions, DOR,
energy patterns, compartments, symmetry, traversal limits — cf. §C1) and
shrinks per kernel with parity evidence.

**Phase 3 — Full-device replica.**
Flat SoA particle pools (type id, component states, bond-partner ids, alive
bit + free lists), flat rule-template store uploaded once, device match
bitsets + dependency tracking (`affectedMatchers`/`affectedFamilies` already
exist on `Engine`), fire/transform kernel with pool alloc/free, dual-stream
device RNG. Hardest parts in order: race-free incremental re-match (naive
re-match-all per event loses to CPU — this is where B1 must already have
won on CPU first), allocation-free graph mutation (complex merge/split),
divergence control + two-stream RNG parity. Success criterion: crossover
thresholds where device beats the Phase-1 pool, measured per model class,
not a single headline number.

**Phase 4 — Portable backend.**
PR 26 is Metal-only at three levels (`CMakeLists.txt` APPLE gate,
`__APPLE__` guards, runtime MSL string). Introduce a backend interface
(`isAvailable`/`simulate`) with per-target kernels (Metal/CUDA/HIP/SYCL/
OpenCL) behind a buffer/queue abstraction, unguarded bindings
(`backend='auto'` + `is_*_available` probes), per-backend thresholds.
Prefer SYCL/OpenCL-style portable compute for the match kernels
(integer/branch-heavy, Linux CI matters); keep the CPU pool the default
until crossover is proven with `BatchSsaMetrics`-style timing splits.

### C4. Validation rules (non-negotiable, from AGENTS.md)

- Native NFsim (pinned RuleWorld/nfsim commit; akutava21/nfsim fork only
  where its energy/perf work is explicitly identified by commit) is the
  parity oracle. BNG3-vs-BNG3 is not evidence.
- Deterministic seeds for stochastic comparison; Z/KS/analytical checks per
  PR 26's harness, extended with mapping-pick-order sensitivity (two-stream
  RNG audit).
- Unsupported stays unsupported: every new kernel carries an explicit
  reject set that fails closed to CPU, never a silent approximation.
- Each phase reports per-model-class crossover numbers, not aggregates
  alone; regressions in `unsupported→fail` transitions block the phase.

## Sequencing

1. A1 (+ A2 if cheap) as PR 26 merge conditions.
2. B0 harness, then B1 → B4 in rank order, B5/B6 opportunistically.
3. Phase 1 ensemble API on the faster CPU baseline.
4. Phases 2–4 only against the Phase-1 baseline with per-class crossovers.

Definition of done per item: semantics understood, simplest implementation,
focused regression + existing suite green, independent parity evidence where
applicable, unsupported still explicit, no unrelated changes damaged.
