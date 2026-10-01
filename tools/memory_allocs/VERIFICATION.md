# Independent allocation verification log

Records measurements taken with `mem_bench.cpp` on worktrees this harness does
not own. Method, thresholds, and the discarded techniques are in `README.md`;
this file is the result log.

## perfNetGen — move-vs-copy (cpp/ast/ReactionRule.cpp:487, :2734)

Arms linked from `/tmp/netgen_bench/libs_baseline` and
`/tmp/netgen_bench/libs_candidate`, counter compiled into each binary.
Interleaved, 8 runs per arm, alternating arm order within each round.
Median + IQR, per the `README.md` rule (never min/max).

| fixture | metric | baseline median (IQR) | candidate median (IQR) | delta |
|---|---|---|---|---|
| `models/tlbr.bngl` max_iter=3 | allocs | 184,178 (0.47%) | 170,914 (1.17%) | **-7.20%** |
| `models/tlbr.bngl` max_iter=3 | bytes | 6,515,128 (0.71%) | 5,959,192 (0.69%) | **-8.53%** |
| `models/blbr.bngl` max_iter=20 | allocs | 883,724 (2.09%) | 802,227 (0.05%) | **-9.22%** |
| `models/blbr.bngl` max_iter=20 | bytes | 31,444,419 (1.80%) | 27,744,271 (0.04%) | **-11.77%** |

Relocation guard, decided on the process total rather than the per-site number
(namespace bucket, `blbr` max_iter=20):

| bucket | baseline | candidate | delta |
|---|---|---|---|
| process TOTAL allocs | 883,724 | 802,227 | **-9.22%** |
| `PatternGraph.cpp` | 82,843 | 66,508 | -19.7% |
| `other` (copy ctors via `ReactionRule.cpp`) | 244,642 | 178,877 | -26.9% |
| `std::vector` (inlined) | 172,907 | 173,289 | +0.2% |
| `Ullmann.cpp` (control) | 373,979 | 373,979 | **0.00%** |
| `ReactionRule.cpp` | 3,750 | 3,750 | 0.00% |
| `std::string` | 6,402 | 6,402 | 0.00% |

**Verdict: real reduction, not a relocation.** The `Ullmann.cpp` control is
bit-identical to the allocation, which confirms the change is confined to
`cpp/ast/ReactionRule.cpp` and the delta is not drift. Deltas are 3-6x the ~2%
floor with non-overlapping arms.

**Not verified here:** wall-clock (none run, none claimed) and semantic
equivalence. Output *shape* is identical across all 16 runs (tlbr 19 species /
29 reactions; blbr 20 / 92); output *identity* is the owning lane's gate.

## swarmMutate — Ullmann M-matrix variants (M1..M4)

**Not yet measured.** `M1` exists at `/tmp/swm/bin/M1` but a bare CLI binary
cannot be allocation-counted (see `README.md`, discarded technique: malloc
interposition returns a silent zero against these binaries). Archived static
libs per arm are required so the counter can be linked in. Expected magnitude,
from the baseline profile on `models/isingspin_localfcn.bngl` max_iter=5
(7,740,781 allocs / 264,617,988 B total):

| site | allocs | bytes | share |
|---|---|---|---|
| `UllmannBase::initialize_M_vec` (map row node) | 2,779,882 | 133,434,336 | |
| `UllmannBase::initialize_M_vec` (`new node_container_t`) | 2,779,882 | 66,717,168 | |
| **total, both from `cpp/core/Ullmann.cpp:83`** | **5,559,764** | **200,151,504** | **71.8% allocs / 75.6% bytes** |

Controls for that measurement: `PatternGraph.cpp` and `ReactionRule.cpp` must
not move if the change is confined to `cpp/core/Ullmann.*`.
