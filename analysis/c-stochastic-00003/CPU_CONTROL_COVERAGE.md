# CPU stochastic control coverage assessment (deliverable 10)

Agent C reviewed the declared CPU trajectory/moment-aggregation and seed-isolation failure modes under #471/#181 and found them already covered by existing tests. Per the coordination rule (shared validation machinery is A-owned) C made **no shared harness/native/validation edit**.

## Covered controls (verified this session, local, prebuilt native ext from primary checkout; SSA source byte-identical to 98b310af)

- `tests/python/test_cpu_batch_ssa_moments.py` — reported per-time std equals `np.std(ddof=0)` of raw trajectory samples; constant model has exactly zero std; threads 1 and 2. **23 passed** with `test_batch_ssa_numeric_limits.py`.
- `tests/python/test_batch_ssa_numeric_limits.py` — rejects float32 rate/population narrowing, preserves representable values and int32 boundaries, rejects out-of-range final populations. Included above.
- `tests/python/test_ssa_closed_form_parity.py` — independent analytic oracles: birth–death stationary Poisson, birth–death time course, three-state switching multinomial, two-state telegraph, unimolecular binomial thinning, identical-reactant combinatorial propensity, zero-rate, fixed-seed reproducibility across thread counts. **10 passed.**
- `tests/cpp/test_correctness_regressions.cpp` — `adjacent batch base seeds do not produce identical batches`, `... do not reuse trajectory RNG keys` (direct check: 0/512 shared keys, old additive mapping shared 511/512), `batch trajectory RNG keys preserve the 32-bit nonzero seed contract`. This is the exact seed-isolation failure mode the 00003 investigation considered, and it is a failing-control/passing-real-consumer pair already in-tree.

## Conclusion

The declared CPU behavior in this slice is covered; no new shared validation machinery is warranted. C's contribution to #471/#181 is the independent evidence in this directory (native reproduction at the official seed, engine seed sweep 0–15 violations, and the predeclared source-law familywise diagnostic) plus the finding that the official ±5 normal-theory SD band is mis-calibrated for the non-Gaussian birth–death law at 00003 — an oracle-scope result A can consume under #159/#184 without a product change.

## Not qualified here

- Full stochastic-surface equivalence (only one case/revision examined).
- Any GPU/network-free/hybrid behavior.
- Hosted qualification of C's own analysis (all C evidence here is local).
