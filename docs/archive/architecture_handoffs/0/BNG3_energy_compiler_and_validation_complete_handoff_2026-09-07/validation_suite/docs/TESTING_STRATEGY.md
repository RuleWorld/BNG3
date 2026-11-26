# Proposed-improvement testing strategy

> Archived strategy note. The active pass batches changes and defers the main
> verification sequence until the end; see `docs/CURRENT_PROGRESS.md`.

## 1. Separate semantic correctness from RNG identity

A generalized energy backend can represent the same continuous-time Markov chain with fewer reaction classes.
That changes how random variates are consumed. Therefore:

- Require byte-identical trajectories only when reaction-class structure and draw order are unchanged.
- Otherwise require exact local rates, total propensities, event probabilities and transformations, followed by a multi-seed distributional gate.

This prevents rejecting a correct optimization merely because its internal random-number bookkeeping differs, while still requiring a stronger semantic proof than endpoint plots.

## 2. Fail closed

Every compiler/runtime test has a complementary fallback test. Unknown state, ambiguous same-type mapping, correlated topology, predicate overflow, malformed legacy factor or failed reverse construction must preserve correctness by selecting materialized expansion/full invalidation rather than inventing a partial optimization.

## 3. Exhaust small local contexts

For <=12 predicates, enumerate all 2^N context masks and compare:

- delta G,
- forward Arrhenius factor,
- reverse Arrhenius factor,
- mapping-local propensity,
- pair-aggregated propensity.

This is cheap and is the strongest test of the local factorization math.

## 4. Property/fuzz tests

- 10,000 deterministic randomized EnergyDeltaPlans per normal CTest run.
- libFuzzer target for malformed/random condition/term combinations.
- 2,000 randomized dependency-index cases checking that the indexed result is always a superset of a literal scan.
- TSAN stress for compile-once cache.

## 5. Model corpus

The fixture manifest intentionally contains one model per topology rather than relying on a single complicated Ising model. This makes failures localizable.

Add the existing `models/isingspin_energy.bngl` as the real-world state-change regression, plus Rasi/uORF only for scaling and non-energy-regression gates.

## 6. Promotion thresholds

Generalized backend default-on candidate only if:

- all deterministic/compiler/runtime tests pass;
- unsupported corpus remains exactly on fallback;
- independent NFsim/BNG2 oracle cases pass;
- 1024-seed stochastic gates pass (4096 for small finite-state models);
- disabled overhead <=2%; non-energy overhead <=3%;
- >=6 independent context predicates achieve >=16x reaction-class reduction;
- >=8 predicates achieve >=4x construction speedup target;
- ASan/UBSan clean; TSAN clean for cache/batch paths.
