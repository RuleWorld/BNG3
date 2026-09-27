# PR 27 comprehensive plan: faster NFsim (CPU + GPU)

Branch: `plan/nfsim-gpu-perf` (from PR 26 head `22ded21`).
Goal: make network-free simulation meaningfully faster — CPU event-loop
wins first (they ship regardless), ensemble parallelism second (reliable N×),
device offload third (where it provably wins). This plan is designed from the
NFsim architecture, not from PR 26's structure; PR 26 (network batch-SSA GPU)
is a dependency and a source of reusable patterns only.

## 0. Where things stand (facts, not proposals)

- Production NFsim path: `ActionDispatch` → in-process `NFcore::System`
  via `NFinput_fromAst` (`cpp/actions/ActionDispatch.cpp:51-54`, `:1746+`).
  Single-trajectory, single-threaded, pointer-graph state
  (`Molecule** bond`, `MappingSet`, reactant trees). Per-event path:
  `System::sim → getNextRxn → ReactionClass::fire → transform →
  updateRxnMembership → TemplateMolecule::compare → update_a`.
- `NFcore2/` (flat SoA state, matcher/transform bytecode, Fenwick
  scheduler, replica-copyable `Engine`) is a standalone `bng_nfcore2` lib
  with contract tests only — **not wired to actions/engine/bindings**.
  Qualifying it is its own project (see §4 decision point).
- PR 26 gives us: a statistical parity harness (Z/KS/analytical), a
  fail-closed dispatch pattern (capability probe → GPU → CPU fallback +
  remeasured thresholds), and per-trajectory RNG discipline. Its kernel does
  not run NFsim events and never will.
- PR 26 dependency: the GPU batch path `.cdat` OOB (§6) must be fixed
  before PR 27 rebases — either in PR 26 pre-merge or cherry-picked. PR 27
  does not own that fix but cannot ship on a broken base.

## 1. Success criteria

- Primary metric: **events/sec per model class** (particle-heavy,
  rule-heavy, large-complex, stiff), measured by the §2 harness.
- Every claimed win: profile before, one change, harness delta +
  `ctest` green + parity vs **native NFsim at a pinned commit**
  (RuleWorld/nfsim; BNG3-vs-BNG3 is not evidence). Stochastic comparison
  with deterministic seeds; reuse PR 26's Z/KS harness shape.
- Unsupported stays explicit: new paths carry reject sets that fail closed
  to the proven path. No silent approximation (AGENTS.md).
- PR 27 exit: harness merged + profiled baseline published in-repo +
  CPU wins with measured deltas + ensemble API + GPU spike verdict
  (go/no-go per model class with numbers). Device kernels beyond the spike
  are explicitly PR 28+.

## 2. Track 0 — measurement harness (first, blocks everything else)

Build `benchmark_nfsim.py` + C++ event counters over representative models:
events/sec, matcher evaluations/event (NFcore2 `Engine` already counts
these; add equivalent counters to `NFcore::System`), allocations/event,
selection vs match vs transform time split. Timing-split style follows
`BatchSsaMetrics` (prep/sim/transfer) but the quantities are NFsim's.
Without this, all priorities below are guesses — the harness may reorder
§3. Gate: harness merged, baseline numbers recorded, profile flame per
model class attached to the PR.

## 3. Track 1 — NFcore CPU event-loop wins (ships first, no GPU needed)

In expected rank order (confirm with §2 profile; do in profile order, not
list order). Each is an independently reviewable commit.

1. **Scope membership re-match to affected rules.** `updateRxnMembership` /
   `updateConnectedRxnMembership` (`moleculeType.cpp:729/1138`) re-match
   each product via recursive `TemplateMolecule::compare` (`:1042`) at
   products × rules-per-type cost. Drive with connected-reaction sets +
   `canSkipIndirectMembership` + the deferred batching already in
   `reactionClass.cpp`. Expected largest win on rule-heavy models.
2. **Zero per-event allocation.** `Molecule` ctor `new[]`s arrays,
   `MappingSet` churn, per-fire vectors, `unordered_set` dedupe. Pool
   molecule arrays/mappings (high-water free lists), reuse fire scratch,
   versioned generation marks instead of per-fire sets. Drive harness
   allocs/event to ~0 on the hot path.
3. **Skip BFS + observable relabel on state-only firings.**
   `traverseBondedNeighborhood` BFS + remove/add observables run every
   event; topology-unchanged firings need neither. Branch on
   transformation type, cache canonical labels per unmodified complex.
4. **Faster selection.** `DirectSelector` linear scan (`directSelector.cpp:
   486`) → hierarchical/Fenwick reduction (design exists in
   `NFcore2/scheduler.hh`; port the data structure, not the engine).
5. **Faster RNG, same streams.** MT19937 → PCG32/xoshiro, keeping `rng_` /
   `mapping_rng_` separation (two streams is a parity requirement, not a
   preference).
6. **TDF path.** Time-dependent-function branch recomputes all `update_a`
   per event → dependency-track which rules read which functions.

## 4. Track 2 — ensemble parallelism (reliable N×, CPU)

Independent trajectories are embarrassingly parallel and NFsim's most
common expensive workload (sweeps, UQ, dose-response). Add `batch_size` to
the NFsim action path: clone `System` per worker over a thread pool, Welford
mean/M2 accumulation, `.gdat` mean + `.bdat` std-dev — same output contract
as PR 26 (including its shape-conformance lesson: identical result shapes
on every backend). This ships standalone value, needs no GPU, and pins the
API + validation harness the device backend must later honor. Decision
point: implement against `NFcore::System` clones now; if the §5 spike
chooses NFcore2 as the device vehicle, the pool backend is re-targeted,
API unchanged.

## 5. Track 3 — device offload (spike in PR 27, kernels in PR 28+)

Rejected up front: parallelizing *within* one trajectory (cross-rule match
in parallel) — fine-grained, sync-heavy, poor SIMT fit. The device plays
only **replica parallelism**: one trajectory per device thread, same as
PR 26's valid half. What must exist for that:

- Flat SoA particle pools (type/state/bond-partner/alive + free lists),
  flat rule-template store, iterative (explicit-stack) matcher, device
  dependency tracking, pool allocator with overflow-to-CPU fallback,
  dual-stream device RNG, sample-time-only D2H.
- Hardest, in order: race-free incremental re-match (§3.1 must win on CPU
  first or the device has no chance), allocation-free graph mutation
  (merge/split), divergence + two-stream parity.

**Vehicle decision (spike, not commitment):** NFcore2 is the natural base
but is production-unproven. PR 27 spikes: (a) NFcore2-vs-NFcore parity and
coverage gap on the §2 models; (b) one restricted-class device kernel
(mass-action, no compartments/energy/DOR/symmetry) proving the
bytecode→device path with parity numbers. Spike verdict picks (i) NFcore2
qualification then device, (ii) in-place NFcore device port, or (iii)
no-go per model class. Full kernels are PR 28+ regardless. Backend
portability (Metal/CUDA/HIP/SYCL abstraction) waits until a kernel wins
somewhere — one winning backend before N portable ones; SYCL/OpenCL-style
leads for match kernels (branch-heavy, Linux CI).

## 6. PR 26 review (dependency, summarized)

Correct scope, honest eval, not merge-safe. Must-fix: live `.cdat` heap OOB
on the GPU batch path (1-row `meanSpecies` vs T-row writers,
`OdeIntegrator.cpp:~1695,~1785` via `ActionDispatch.cpp:1441`) + backend
shape inconsistency; fix in PR 26 or cherry-pick. Should-fix: 2×
propensity eval per event, per-instance MSL pipeline compile, RNG doc
mismatch, float32 range guards. Full detail was in the superseded draft;
per the re-scope it lives here only as the base-hygiene dependency.

## 7. Sequencing and PR boundaries

1. §2 harness + baseline (lands first, unblocks ranking).
2. §3 items in profile order, each with measured delta.
3. §4 ensemble API on the faster baseline.
4. §5 spike → vehicle verdict → PR 28+ kernels.
5. Portability only after a kernel wins.

Definition of done per item: semantics understood, simplest change,
focused regression + suite green, independent parity evidence where
applicable, unsupported still explicit, unrelated code undamaged.
