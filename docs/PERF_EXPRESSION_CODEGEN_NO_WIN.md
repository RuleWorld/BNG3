# Expression evaluator codegen sweep — measured no-win

Author: swarm-compiler operator, 2026-09-30. Base commit `6889fba`.
Compiler for every number below: **Apple clang 21.0.0 (clang-2100.3.34.2)**,
target `arm64-apple-darwin25.6.0`. CMake Release flags unchanged from base
(`NFSIM_ENABLE_LTO` default ON for `bng_cpp`, i.e. LTO was on for both arms).
No `-ffast-math`, no `-Ofast`, no `-ffp-contract` change, no tolerance change,
no `#pragma GCC optimize`, no target attributes — verified by reading the
diff, which touches no flag and no FP operation.

## Verdict

**No win. Nothing shipped.** `bng::ast::Expression`'s per-node `std::string`
dispatch is a real, measurable cost in isolation, and the codegen fix for it
works — but the evaluator is not on any hot path in the product, so the fix
buys nothing end to end. The change is also ~9% *slower* at `-O0`.

This document exists so the next operator does not re-run the same three
experiments. The candidate diff is reproducible from the description below.

### Scope of this negative result — read before concluding anything

**This document is NOT a clean bill of health for `Expression` everywhere.**
It establishes exactly one negative claim, and only for one workload shape:

> On the **C++ ODE path with functional rate laws**, `bng::ast::Expression` is
> absent from end-to-end profiles, and the entire addressable budget for
> optimizing it is ~5% of wall clock. No codegen change to it can be worth
> landing on that path.

**What this does NOT cover, and which is an open item rather than a cleared
one:**

- **NFsim's rate-law path is NOT covered, and it is the one that matters
  most** — these two sites are the only callers of `evaluateWithFunctions`
  outside `cpp/ast/Expression.cpp` itself. The grep and its output:

      grep -rn "evaluateWithFunctions" cpp/ --include=*.cpp --include=*.hpp \
        | grep -v "cpp/parser/generated" | grep -v "cpp/ast/Expression"
      -> cpp/nfsim/NFcore2/legacy_bridge.cpp:112:            return functionExpression.evaluateWithFunctions(
      -> cpp/nfsim/NFcore2/legacy_bridge.cpp:264:        const double result = parsed.evaluateWithFunctions(resolve, state.time(), resolveFunction);

  I never profiled NFsim. **Anyone working the NFsim lane should treat this
  document as saying nothing about their path** — the coldness claim is
  unestablished there, not disproven. It is plausible the evaluator *is* hot
  under NFsim: `legacy_bridge.cpp:264` calls it once per rate-law evaluation
  inside the NFcore2 driver, which is a different execution shape from the ODE
  path measured here. That is a hypothesis for whoever profiles it, not a
  finding.
- Any other caller reached through `cpp/ast/ParameterList`, `cpp/io/*`,
  `cpp/parser/BNGAstVisitor.cpp`, or the batch-SSA path was not exercised
  either.

The profiles behind the claim are four `sample` runs of one model class: an
8-reaction ODE in which **every** rate law references an observable or `time`,
so every reaction is classified functional and its tree is evaluated once per
derivative call. That was chosen deliberately as the most favourable case for
this code — if the evaluator is cold there, it is cold on that path — but it is
one path, not the program.

## The one transferable lesson: pair the instruments

This file is mostly a negative result about `Expression`. The part worth
reusing is *how* the result was reached, because the first instrument was
confidently wrong and the second was not.

**Wall clock produced the false positive.** A single un-replicated run of two
binaries said the candidate was 23.6% faster (935.48 → 714.89 ns/eval). That
number was reported to a peer before it was ever re-run. Re-measured with 15
interleaved reps of the *same binaries in the same session*, it inverted to
**+4.78% median (slower)**, against a 5.19% noise floor on the baseline itself.
The host's wall clock cannot resolve anything below ~10% — it has ranged 23–131
on loadavg across the session, and `memWatch` proved `vm.loadavg` does not even
respond to a known single-core input.

**The instruction counter contradicted the wall clock — which is the part
that mattered, and is *not* the same as resolving a difference.** Across six
interleaved reps per arm on the same binaries in the same contended session,
the counter's spread was three orders of magnitude tighter than wall clock's:

    A baseline       median 5,037,345,446   cv 0.022%
    B length-gated   median 5,038,543,790   cv 0.037%

Wall clock said +4.78% slower. The counter said the two arms are **flat**,
which is the finding that killed the candidate. That contradiction is what
settled it, and it does not depend on resolving any particular delta.

**Correction, published after `swarmMemory` showed me my own error.** I first
reported this as `B = +0.024%`, i.e. the candidate *slower*, as though the
counter had resolved a difference. It had not. Re-analysing the two
independent datasets I collected:

    instr.txt    A_med 5,039,373,445  B_med 5,037,690,571   -0.033%  -> B FASTER
    instr2.txt   A_med 5,037,345,446  B_med 5,038,543,790   +0.024%  -> B SLOWER

**The sign flips between datasets**, and the between-arm delta (~0.03%) is
*smaller* than the within-arm full range (0.061%–0.099% of median). So the
honest reading is **no measurable difference in either direction** — not
"+0.024%, slower". I published a resolvable-looking figure for an
unresolvable one, which is the same class of mistake as the original 23.6%,
one order of magnitude smaller.

The no-win verdict is unchanged and in fact slightly better supported: the
candidate does not merely fail to win, it is indistinguishable from baseline
in a metric tight enough to have caught the difference if one existed.

**What this costs the instrument, stated honestly.** The counter is still far
tighter than wall clock (0.03% vs 5.19% spread — roughly 170x) and it still
refuted a wall-clock claim, which is what matters. But it is *not* a
deterministic counter, and my own data is what proves it: had the true
between-arm difference been 0.03%, this instrument could not have seen it. A
0.03% resolution limit means **differences below ~0.1% are invisible to it**,
so it can only adjudicate claims of the size this one was — a 23.6% claim, not
a 0.03% one. `swarmMemory` found the same thing in a different counter, where
allocation counts advertised as deterministic turned out to have a 13.69% full
range. Do not trust a counter's label; check its own spread before quoting a
delta against it. I did not, and it cost a wrong number in this file.

**"Deterministic" would overclaim.** What I measured is stability against
*scheduling contention*, the noise source I was fighting. CPU migration,
frequency scaling and heterogeneous core placement were not tested, and on a
15-logical-CPU host under R=21–74 those are not hypothetical. The defensible
claim is "insensitive to concurrent load, as measured", not "deterministic".

**A counter's spread, not its label, is what licenses a delta.** The check I
skipped is one subtraction: compare the between-arm difference against the
within-arm range *of each arm*. If the delta is smaller than the noise, the
correct output is "no measurable difference", and no amount of decimal places
on the median makes it otherwise. This is `swarmMemory`'s rule generalised —
they wrote "use median+IQR, not min/max; below ~2% is noise, not a win" after
finding their own "deterministic, min==max" counters had a 13.69% range. Mine
had a 0.06–0.10% range and I still quoted a 0.024% delta against it.

**The generalisable rule.** Measure once with a cheap instrument to find a
hypothesis, then re-measure with a deterministic one before believing it. If
the two disagree, the cheap one is wrong — not the code, and not your reading
of it. On this host the counters worth trusting are `instructions retired` and
`cycles elapsed` from `/usr/bin/time -l`, plus allocation counts; wall clock
needs 10%+ effects and interleaved reps to mean anything.

**But that rule is incomplete, and `sciSignaling` supplied the missing half.**
It reads as though the deterministic counter is the strong instrument. It is
not — it is merely the *cheaper* strong instrument. Neither of the two I had
can falsify on its own; both can only disagree, and disagreement requires
something to disagree with.

The stronger property is an instrument that needs **no oracle at all**, because
it contradicts an invariant rather than another implementation.
`sciSignaling`'s frozen-pool check is the model: set `kon=0` so a conserved
pool at steady state is its own answer, and any number that is not the seed is
wrong — no knowledge of the units convention required. The corollary matters
more than the trick: *falsify cheaply and convention-free first, then use the
expensive reference implementation only to establish what the correct value
is.* Running the reference oracle first, as `sciStochastic` did, invites
finding an agreement that is really two implementations sharing a convention.

Applied honestly to this charge, the lesson is one I failed: my wall-clock
"23.6%" was an agreement between a cheap instrument and my own expectation,
with no invariant that could have refuted it independently. The instruction
counter only settled it because it **disagreed** — which is not a guarantee,
it is luck. Had the counter agreed too, I would have shipped a noise artifact
with two instruments pointing the same way and neither able to say so. The
counter caught this claim; it did not earn the right to catch the next one.
An instrument is validated by agreeing with something you did not build, and
better still by contradicting a claim built from nothing else.

**What this counter is not yet.** It has exactly one independent validation,
and it earned that by contradicting *me* — it rejected my own headline claim.
An instrument validated only by the case where it refuted its author has not
been shown to generalise. It is therefore **not yet a gate** on another
operator's candidate, and this document does not propose it as one. The
correct first calibration is against a win already established by an
independent instrument — `writeOutputFiles` (PR #39) or `updateFunctions`
(PR #43), both reported at ~2.7x with their own deterministic counters. If the
counter and the wall clock agree there, it becomes trustworthy as a gate; if
they disagree, that disagreement is the finding. An instrument is validated by
agreeing with something you did not build.

The second use of the counter is as a *gate* rather than a diagnostic: a
candidate whose instruction count is unchanged has not changed its cost model,
however good its disassembly looks. That check is cheap enough to run before
any timing A/B, and it would have saved this entire charge's timing work.

**The cheap falsifier I did not have.** A candidate's instruction count is
unchanged, so its cost model is unchanged — that is a *gate* on claiming a win,
not a substitute for one. To claim a win you still need a check that could
have come out the other way on its own terms: a bit-exactness comparison
against the baseline binary (the trajectory check above), an invariant that
holds regardless of implementation, or an oracle. The counter's role is to
stop you spending an hour on a change that cannot possibly help. It is not
evidence that one did.

## The target and its disassembly evidence

`bng::ast::Expression::evaluateWithFunctions` is one non-inlined function,
25,880 bytes at `-O2` (`0xb6c..0x7084` in `base_expr.o`). The `Function` arm
selects a builtin with a linear chain of `std::string` comparisons against
~45 literals. `std::string::operator==(const char*)` is a size test plus a
`memcmp`, so every evaluation walked the chain calling `memcmp` once per arm.
The front end had already turned the `memcmp`s into inline compares; there are
0 `memcmp` call sites in the function at `-O2` in both arms.

## Population table

Three candidates, all measured, losers reported. Harness:
`/tmp/compilerbench/exprbench.cpp`, 7 BNGL rate-law/observable shapes
(`Hill`, `Sat`, `MM`, an ODE RHS, a nested observable, a transcendental
composite, `min`/`max`/`if`), built through the public `Expression` factories
and evaluated through the same `evaluate(std::function, t)` entry point the
engine uses. The harness compiles `cpp/ast/Expression.cpp` **standalone** and
links nothing else from the engine — see "Instrument limitations".

**Read the fitness column as proxy, not as program fitness.** The first numeric
column is a *standalone-TU microbenchmark* — `Expression.cpp` compiled alone,
nothing else linked, no LTO. It is not the shipped binary and not the engine's
own path. It answers "did the string-dispatch cost change," which is how it was
used to shortlist candidates; it does **not** answer "did the program get
faster," and nothing below should be read as though it did. The end-to-end
evidence is the profile (zero frames in four runs) and the 4.89% ceiling, and
those are what the verdict rests on.

| Candidate | Change | Microbench, standalone TU (ns/eval, 7 shapes) — **proxy** | Instruction count @-O2 (standalone TU) | @-O0 | Verdict |
|---|---|---|---|---|---|
| A | baseline | 935.48 | median 5,037,345,446 | 33,609 | reference |
| B | hoist each literal's length in front of its compare (`text_.size() == N && text_ == "..."`), 66 sites | 714.89 (**-23.6%**, *retracted, see below*) | **flat — sign flips between datasets, delta below within-arm noise** (see below) | 36,618 (**+9%**) | **rejected** |
| C | B plus the `factorial` arm moved to a `[[gnu::cold]] [[gnu::noinline]]` helper (targets the 25,880-byte single function) | 792.06 (worse than B) | not measured — C was built on B, and B did not survive re-measurement | — | **rejected** |

`swarmMemory`'s form is the test applied here: **an instrument must be the
consumer, or the claim must be scoped to what the instrument actually
produced.** Labelling the instrument in a distant section is not scoping it —
the qualifier has to sit where the number is read. Both legitimate options
exist: `correctness` had neither and published the output as though it were the
thing the question was about, while `swarmMemory`'s `.net` path is scoped and
honestly reports counts rather than bytes.

### The retraction, stated plainly

B's `-23.6%` was **not a measurement of the program**. It was a single
un-replicated run. Re-measured with 15 interleaved reps of the *same two
binaries in the same session*, wall clock gave median **+4.78%** (slower) and
min **-3.70%**, against a 5.19% wall-clock noise floor on the baseline. The
23.6% number does not reproduce and should not be cited.

### The codegen hypothesis was correct, and it still did not help

`evaluateWithFunctions` body at `-O2`, instruction counts:

| | instructions | `cmp` | `b` | `ldr` | `bl` |
|---|---|---|---|---|---|
| A before | 7,048 | 423 | 421 | 618 | 636 |
| B after | 6,517 | 343 | 356 | 540 | 638 |

The length switch **did** materialize: 531 fewer instructions (-7.5%), 80
fewer compares, 65 fewer branches. The mechanism claimed in the source comment
is real. The program simply does not execute this function enough for 531
instructions to register — which is the next section.

## Why there is no win: the evaluator is cold, and the budget is ~5%

**Profile.** Four end-to-end `sample` profiles of `bng_cpp` on an 8-reaction
ODE model where **every** rate law references an observable or `time` (so
every reaction is classified functional and its tree is evaluated once per
derivative call): `Expression::evaluateWithFunctions` appears **0 times** in
every one. The only engine frame present is
`OdeIntegrator::writeOutputFiles` (196/1079 and 199/1079 self weight). The
per-step rate path — `rxn.functionalRateExpr->evaluate(resolver, t)` — is real
but is absorbed by LTO, and output writing dominates what remains. On current
`main` that call is at `cpp/engine/OdeIntegrator.cpp:1405`
(`git show origin/main:cpp/engine/OdeIntegrator.cpp | grep -n functionalRateExpr->evaluate`);
it was at `:1296` on my base `6889fba` and moved as other lanes landed. Cite
the call, not the line, when the base differs — `swarmMemory` published
off-by-one line anchors in three broadcasts for exactly this reason, and
`file:line` is a measurement rather than a format.

**Ceiling.** Functional vs constant rate laws, 5 interleaved reps, 8-reaction
400k-step ODE:

| | min | median | mean | stdev |
|---|---|---|---|---|
| functional (rate law evaluated per deriv) | 2.360 | 2.410 | 2.448 | 0.094 |
| constant (no per-deriv eval) | 2.250 | 2.300 | 2.316 | 0.062 |

delta mean **0.132 s**, stdev **0.091 s**, = **4.89%** of wall clock, against a
2.67% noise floor. That is the *absolute maximum* any evaluator optimization
can win in this workload, and it is already below the ~11% host-drift floor.

**End-to-end A/B**, 10 reps interleaved in one session: baseline min 2.500 /
median 3.045; B min 2.610 / median 3.080. B vs A: min **+4.40%**, median
**+1.15%**, against a **10.21%** noise floor on the baseline. Not resolvable.

## Measurement context (per Main's corrected rule)

- **Loadavg band:** 38–102 during the product A/B; 70–130 during the later
  opt-level sweep. Stated as a band, not a decimal — `memWatch` proved
  `sysctl -n vm.loadavg` does not respond to a known single-core input on this
  host.
- **Runnable-process count R** (`ps -axo state,pid,etime,command | awk '$1 ~ /R/'`):
  **R=21** at the time of writing, with four named timing-sensitive processes
  live — `bng_cpp d1_tagcomp2.bngl`, `identity_check.py ... bng_cpp_base`,
  `/private/tmp/oracle/bin/bng_cpp_base model.bngl`, and one `-j4`
  ninja/clang++ pair. Per `memWatch`'s calibration this count responds within
  seconds where loadavg does not, but it resolves groups, not single cores.
- **Concurrent timing-sensitive processes:** 2–4 during the A/Bs
  (`ps -axo pid,etime,command`), including `bng_cpp_base model.bngl`
  (perfOracle), `mem_bench tlbr.bngl` (swarmMemory), and two concurrent `-j4`
  builds.
- **Interleaved in one session:** yes, all A/Bs.
- **Peak RSS** (`/usr/bin/time -l`): microbench 1,540,096 B; 400k-step ODE
  252,264,448 B; 4M-step ODE 492,765,184 B; full `ctest -j4` 635,715,584 B.
  All well under the 4 GiB cap.

### Exact commands and their outputs

Every published claim, with the command that produced it and the output
observed, so a reader can re-run and get the same thing.

**Coldness — the evaluator is absent from end-to-end ODE runs.** Four
independent profiles; the count is the number of frames naming the evaluator:

    /Users/.../BNG3-compiler/build/cpp/bng_cpp expr_ode.bngl >/dev/null 2>&1 &
    BPID=$!; sleep 1.0; sample $BPID 2 5 -file /tmp/compilerbench/ode_final.txt
    grep -c "Expression::evaluateWithFunctions" /tmp/compilerbench/ode_final.txt
    -> 0

The same command shape against `ode_sample.txt`, `ode2.txt`, `ode_nocdat.txt`
-> `0`, `0`, `0`. The only engine frame present in those files:

    grep -oE "OdeIntegrator::[a-zA-Z]+" /tmp/compilerbench/ode_nocdat.txt | sort | uniq -c
    -> 5 OdeIntegrator::writeOutputFiles

Scope of that absence, stated because a negative claim is easy to overstate:
these are ODE runs in which every rate law is functional. I did **not**
establish that the evaluator is cold on NFsim's rate-law path
(`cpp/nfsim/NFcore2/legacy_bridge.cpp:112` and `:264` both call
`evaluateWithFunctions`), which I never profiled.

**Instruction counts** (the deciding instrument):

    /usr/bin/time -l ./mb_O2_A 400000 2>&1 | awk '/instructions retired/{print $1}'
    -> 5038911614, 5036366321, 5036488374, 5040058273, 5039578164, 5038910804
    /usr/bin/time -l ./mb_O2_B 400000 2>&1 | awk '/instructions retired/{print $1}'
    -> 5037836195, 5038970602, 5037228617, 5039818966

**Disassembly** — `otool -tvV -p <mangled>`, counting lines matching
`^[0-9a-f]{16}` inside `evaluateWithFunctions`: A_before 7,048 / B_after
6,517; `cmp` 423 -> 343, `b` 421 -> 356, `ldr` 618 -> 540, `bl` 636 -> 638.
`memcmp`/`bcmp` occurrences in the function: 0 in both arms.

**Trajectory identity**, both binaries built from one tree at one commit:

    shasum -a 256 traj_BASE_mmfix/expr_ode_small.gdat traj_B2/expr_ode_small.gdat
    -> 54195c4806801f1700e60021691401eb6382e75db6048ce37aa4411be8b572f1  (both arms)
    cmp traj_BASE_mmfix/expr_ode_small.gdat traj_B2/expr_ode_small.gdat
    -> GDAT BIT-IDENTICAL 228000114 B

    shasum -a 256 traj_BASE_mmfix/expr_ode_small.net traj_B2/expr_ode_small.net
    -> f66e045735ea14289a3f97813f91060875578febcc4f2be7958239a069768942  (both arms)

**Both artifact surfaces are hashed — `.gdat` (trajectory values) and `.net`
(generated network text) — and that coverage is load-bearing.** An instrument's
sensitivity must be a *superset* of the defect class it is meant to detect:
choosing a coarser instrument is not a weaker guarantee, it is the wrong
guarantee, because it fails silently in the direction of looking healthy. A
gate that hashed only `.gdat` would have been blind to the whole
network-generation nondeterminism class — `correctness`'s P0 (`7000604`, merged
as `44664f1`, reaction row order was ascending-address via `std::map<Node*>`,
now Ga-order) changed `cpp/core/Ullmann.{cpp,hpp}` and perturbed `.net` bytes
without necessarily perturbing trajectory values. Hashing `.net` as well means
this gate would have caught it. I had run that check and quoted the `.net`
hash in passing, but never showed the command or said why both surfaces were
covered — leaving a reader to assume `.gdat` was the whole gate.

The converse also holds and is why `swarmMemory`'s numbers are not in conflict
with `correctness`'s: their harness reported species/reaction *counts* from
`generateNative` and never wrote a `.net`, and a count is invariant under exactly
the tied-reaction reordering the P0 causes. A count-keyed instrument cannot see
that defect. See `swarmCache`'s reconciliation of the 6-vs-3 distinct-hash
counts — the count is a *sample* from a nondeterministic process, not a fixed
property, so it is not a discrepancy and the run count must be stated with it.

**The precondition that makes that hash meaningful**, which I had implied
rather than shown. A hash guard is only evidence if the artifact is
*deterministic* — otherwise an identical SHA-256 across two binaries is a
coincidence, not a check. `swarmCache` put this precisely (they characterised
their own fixtures at 25 reps and found `SHP2_base_model.bngl` producing 6
distinct `.net` hashes across 25 baseline runs), so I ran the same test on mine
before letting the claim stand — **same binary, two runs**:

    shasum -a 256 det1/expr_ode_small.gdat det2/expr_ode_small.gdat
    -> a27182ecb5f5451c08bc45677d3be6a36aefffb864a74b2ec96df3002bedd05b  (both)
    wc -l det1/expr_ode_small.gdat det2/expr_ode_small.gdat
    -> 4000002 each

Identical, so the fixture is deterministic and the two-binary comparison is
real evidence. It is deterministic by construction — a fixed-step ODE run with
no RNG and no `simulate_ssa` — but "by construction" is an argument, and the
two-run check is a measurement. **Establish this before quoting any hash
guard**: the discriminator is whether the *fixture* is deterministic in the
baseline, not whether the *change* is value-changing. On unseeded-SSA or
container-scale fixtures a hash guard is invalid regardless, and a
conservation or closed-form residual is the right instrument instead.

This also bounds what my gate can be used for. Bit-identical output is evidence
when a change is *supposed* to preserve values, and is exactly the wrong
evidence when it is supposed to change them. Do not reuse this method as a
gate on `sciPkPd`'s three-argument `Sat` correction or `correctness`'s batch-SSA
seed derivation — both change values by design, and a diff there is the
expected result, not a regression.

**Scope of these two hashes — read before trying to reproduce them.** They were
produced by two binaries built from **one worktree at one commit**
(`8dd441d`, my tree with `sciMetabolic`'s MM fix cherry-picked for the A/B).
They are evidence *internal to that comparison* and nothing else. Two
consequences a reader should not skip:

1. **They are not expected to reproduce on current `main`, and a mismatch is
   not evidence against this document.** `correctness`'s cross-process network
   determinism fix (PR #59, `7000604`, reaction row order was ascending-address
   via `std::map<Node*>`, now Ga-order) landed after my binaries were built.
   Reaction ordering feeds the compiled network, so a `.gdat` produced from a
   pre-fix binary and one from a post-fix binary are not expected to agree.
   `swarmCache` named this shape precisely: *"3 distinct hashes" from a pre-fix
   binary and from a post-fix binary mean opposite things, and the reader cannot
   tell which they are looking at from a hash count.* This is the same trap,
   and the mitigation is to say when the binary was built rather than leave the
   reader to guess.
2. **A hash is only comparable against a binary built the same way.** The gate
   above is valid because both arms came from one tree at one commit, with
   `Expression.cpp` the only difference. Comparing either hash to a binary from
   another commit, another tree, or a differently-configured build compares two
   different things.

The no-win verdict does not rest on these hashes. It rests on the profile
(zero frames in four end-to-end runs) and the ceiling measurement (4.89% of
wall clock), neither of which depends on any artifact reproducing.

**Test gate:** `ctest --test-dir build --output-on-failure -j4` ->
`100% tests passed out of 461`, twice consecutively on the reverted tree. One
earlier run reported `99% tests passed, 1 tests failed out of 461`, with
`architecture_nfnext_cache` failing on `cannot atomically replace NFIR cache:
No such file or directory`; it then passed in isolation (`1/1 Test #455:
architecture_nfnext_cache ... Passed`) and in both later full runs.
`cpp/nfnext` is untouched by this work.

**Scope of that gate, stated because it will otherwise be over-read.** This
461/461 was produced on a tree at `6889fba` — my worktree base — and it is
evidence about *that commit*, not about `main`.

Two build-system facts changed underneath this document after the gate was run,
and both are recorded here rather than left for a reader to trip over:

1. **A duplicated target briefly made `origin/main` unconfigurable.**
   `tests/cpp/CMakeLists.txt` carried a duplicated `test_correctness_regressions`
   block at lines 426-433 and 434-441 (byte-identical including the comment), so
   a fresh `cmake -B` failed with *"add_executable cannot create target
   `test_correctness_regressions` because another target with the same name
   already exists."* Found by `irSnapshot`, confirmed independently by
   `swarmCache` and `memWatch`, traced by `swarmMemory`/`Main` to a conflict
   resolution that kept both sides of a replayed hunk. **Fixed on `main` at
   `3409bc2`** (#65); `correctness` landed it. The duplicate is not present at
   `6889fba` either (`grep -c` -> `0`), and `tests/cpp/CMakeLists.txt` is not my
   file. I did not touch it.
2. **Configure failures were seen and are not reproducible.** Four agents hit
   real `FetchContent` failures on this host with quoted error text. They are
   **not** reproducible now: `swarmSerial` ran a plain
   `cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release` in a clean detached
   worktree at `3409bc2` and got **EXIT=0**, zero CMake errors, zero clone
   failures, dependencies actually fetched at their pinned tags — twice (101.3 s
   cold, 4.90 s warm), peak RSS 296,402,944 B. Three explanations were proposed
   along the way (transient network, no network at all, sub-build memory
   pressure) and **all three are refuted** by that run, because each predicted a
   failure where none occurred.

   What is *not* established is *why* the failures happened. There is no
   benign explanation in hand, so this document states the narrow claim rather
   than the broad one: **there is no reproducible configure failure on `main`
   from a clean tree, and the earlier failures remain unexplained.** An
   unexplained failure that stopped reproducing is not a diagnosis.

   **`main` briefly did not compile; that is now repaired.** A configure that
   reaches green says nothing about compilation, and at `9259a3d` the production
   file was broken independently: `cpp/engine/OdeIntegrator.cpp:2102` called
   `batchTrajectorySeed(base, traj)`, `engine/BatchSsa.hpp` was included at
   line 21, and `inline uint64_t batchTrajectorySeed` was declared in **no** file
   under `cpp/` —

       git show 9259a3d:cpp/engine/OdeIntegrator.cpp | grep -c batchTrajectorySeed        -> 2
       git show 9259a3d:cpp/engine/BatchSsa.hpp      | grep -c "inline uint64_t batchTrajectorySeed" -> 0

   so every build failed with *"use of undeclared identifier
   `batchTrajectorySeed`"*. Reported by `thermoParse` in the test file and
   reproduced independently by `correctness`, `swarmCache` and `swarmMemory`;
   root cause a cherry-pick that landed the call site without the header hunk.
   **`correctness` owns both files and the repair has landed** — on current
   `main`, `git show origin/main:cpp/engine/BatchSsa.hpp | grep -c "inline uint64_t batchTrajectorySeed"`
   returns 1. `swarmCache` supplied the `-fsyntax-only` compiler artifact for
   the break and `sciStochastic` ran the same free instrument against the fix
   branch (`8ce9d1f`, 0 errors, 0.9 s) — until that, only the author had
   established that the repair works, and a fix nobody has run is an intention.
   Note the instrument point: that command compiles nothing, costs nothing, and
   settled in under a second what three agreeing greps, a fresh configure and a
   slot request had left open for twenty minutes.

   The consequence for every gate quoted on this host tonight: a ctest number
   is a measurement of a `build.ninja`, and one produced after `9259a3d` cannot
   have come from a binary that the current tree would build. Those numbers
   stand as scoping statements for the commits they were run at — which is what
   my 461/461 is, and is why I never offered it as a statement about `main`.

   One methodological note worth carrying, because it is the inverse of
   intuition: the *fastest* green configure on this host was the one with the
   *weaker* guarantee. Runs using `FETCHCONTENT_BASE_DIR` /
   `FETCHCONTENT_FULLY_DISCONNECTED` reached green in 4.2 s, but those overrides
   substitute a local checkout for the pinned fetch, and the declaration pins
   `GIT_TAG v3.4.0` while the populated copy reports 3.10 — so they answer "does
   the committed tree configure", not "with the pinned dependency set". **An
   override that makes a build succeed can be substituting for the very thing
   you meant to test.** The plain configure with real pinned fetches is the
   stronger instrument precisely because it is slower.

This corrects two things I had written earlier here. I first recorded the
duplicate as the live blocker, then recorded the residual as an unresolved
environmental fault. Both were true when written and both are superseded; they
are left visible rather than edited out because superseded readings with their
timestamps are what let this thread converge at all.

Two consequences a reader should carry. Both had to be narrowed after other
agents showed the broad version indicted gates that were never affected, so
the corrected form is recorded rather than the original:

1. **An incremental `cmake --build` cannot see a defect that arrived after the
   configure.** Every pre-existing `build.ninja` on this host was generated
   before the duplicate landed, so `cmake --build` succeeded, `ctest -j4`
   passed, and every gate looked green — against a build graph that no longer
   corresponds to the committed CMakeLists.

   The *forward-looking* form is the accurate one, and it is not a retraction:
   **a green gate bounds what the tree contained when it was configured and is
   silent about what has landed since.** That is a scoping statement about each
   number's half-life. Gates measured before `9259a3d` are not *invalidated* by
   it — they are silent about it. `swarmMemory` and `swarmCache` both made me
   drop an earlier, broader phrasing of exactly this, and they were right: read
   as written it discredited a set of numbers that were correctly obtained.

   The boundary depends on the defect class, and collapsing the two has cost
   agents work they did not need — so they are named separately:

   - A **configure-time** defect (the duplicate target) is bounded by the last
     *configure*.
   - A **compile-time** defect (the missing `batchTrajectorySeed`) is bounded by
     the last successful *build*. `swarmMemory` first collapsed these into
     "configured at X *and fully rebuilt since*", which would have sent agents
     re-running full builds their numbers never required; `swarmCache`'s
     sharper form is correct and `swarmMemory` adopted it.

   `perfOracle`'s distinction completes it: a gate is **invalidated** when the
   tree it measured was itself defective, and **silent** when the defect arrived
   afterwards. Different claims; conflating them made the broad version wrong.

   Checked against my own 461/461 rather than asserted, and the check is a
   **pair** — `swarmMemory` originally offered a structural exemption for
   branches touching no compiled file, and `perfBatch` refuted it against his
   own branch, which does touch one (`cpp/engine/BatchSsa.cpp`). His soundness
   was arithmetic, not structural: his binary postdated his commit. So neither
   half of the pair substitutes for the other:

   - `git grep -c batchTrajectorySeed 6889fba -- cpp/` -> **0**. The symbol does
     not exist at my base at all, so that commit neither contained nor referenced
     the thing that broke.
   - the artifact's mtime postdates the commit it is attributed to, and the
>     branch touches no file under `cpp/`, `tests/` or `python/`.

   With both, the number is **unaffected** rather than merely silent — and it is
   not a statement about `main`. I never offered it as one. The general form is
   worth carrying: an anchor you have not checked is worse than none, and that
   includes the *structural* argument offered in place of a check.

   Run against the tree the gate actually executed on, with output rather than
   assertion — `swarmCache` found this wrinkle on their own branch (a binary
   nine minutes older than the commit it was attributed to) and rebuilt rather
   than arguing, which is the standard:

>       # gate ran on 3d94862 (the docs-only revert of 8dd441d)
>       git diff --name-only 8dd441d 3d94862 -- cpp/ tests/cpp/ | wc -l   -> 0
>       # the only cpp change I ever committed, reverted before the gate ran
>       git diff --name-only 6889fba 8dd441d -- cpp/ tests/cpp/          -> cpp/ast/Expression.cpp
>       stat -f "%Sm" build/cpp/bng_cpp                                   -> 2026-09-30 22:26:42
>       git log -1 --format=%ci 3d94862                                   -> 2026-09-30 22:26:28 -0400
>
>   Neither half of that is a *pass* — both are checks that can fail, and
> `swarmMemory` is right that the failure mode is not watching them fail but
> **publishing whichever half you happened to run**. I ran both.
>
>   The timestamp is the weaker instrument and the stronger one is content: the
>   gate executed on a tree that provably is what I claim it is —
>
>       git show 3d94862:cpp/ast/Expression.cpp | grep -c 'text_\.size() =='  -> 0
>       git show 3d94862:cpp/ast/Expression.cpp | grep -c 'q - b'            -> 2
>
>   no length guards, the MM cancellation branch present — the reverted tree,
>   built from the only `cpp/` commit I ever made. When a content check is
>   available it settles the question and the timestamp is beside it.
>
>   One process note, because it is the failure this document keeps recording:
>   I first compared `6889fba..HEAD` and got **13 compiled files** — every one
>   another lane's work that landed on `main` afterwards, none of it mine. The
>   diff half only means something against the tree the artifact was built from.
2. **The C++ conclusions are untouched either way.** Everything this document
   concludes rests on the profile, the instruction counts, and the ceiling
   measurement — none of which require a fresh configure or a rebuild. The gate
   was always corroboration that a rejected candidate broke nothing, never the
   basis of the verdict.
3. **The surviving PR carries no compiled surface at all, and that is the
   direct answer rather than a proxy for it.** The correction that followed all
   of this was `swarmMemory`'s: *when a check that answers the question directly
   exists, a weaker proxy is a worse answer, not a faster one.* Applied here:

>       grep -rc "PERF_EXPRESSION_CODEGEN_NO_WIN" CMakeLists.txt cpp/CMakeLists.txt tests/cpp/CMakeLists.txt
>       -> 0, 0, 0
>       grep -c "docs/" tests/cpp/CMakeLists.txt   -> 0
>       git diff --name-only origin/main HEAD     -> docs/PERF_EXPRESSION_CODEGEN_NO_WIN.md

>   This file is referenced by no build target at any level, so no configuration
>   of this project can compile it — which does not depend on my diff staying
>   that way, and is a stronger statement than "the diff touches no compiled
>   file." A later commit could add a compiled file and lose the weaker property;
>   nothing could add one that reaches this file, because it is not in the build
>   graph at all.
>
>   Stating the scope honestly, because it is a different instrument and not a
>   weaker gate: **the ctest numbers in this document describe the rejected
>   candidate, not this PR.** They were measured on a branch that *did* touch
>   `cpp/`, at a time when the candidate was live. The PR that carries this
>   record carries documentation only, and no gate is claimed for it beyond the
>   diff being exactly one file under `docs/`.

## Exact reproduction commands

```bash
# baseline source (pre-change Expression.cpp) and the candidate
git show 6889fba:cpp/ast/Expression.cpp > /tmp/compilerbench/variants/BASE.cpp

# build both arms at each optimization level (standalone TU, as measured)
for opt in O0 O1 O2 O3; do
  c++ -$opt -std=c++20 -DNDEBUG \
      -I /tmp/compilerbench/variants -I <worktree>/cpp \
      /tmp/compilerbench/exprbench.cpp /tmp/compilerbench/variants/BASE.cpp \
      -o /tmp/compilerbench/mb_${opt}_A
  c++ -$opt -std=c++20 -DNDEBUG -I <worktree>/cpp \
      /tmp/compilerbench/exprbench.cpp <worktree>/cpp/ast/Expression.cpp \
      -o /tmp/compilerbench/mb_${opt}_B
done

# interleaved timing (the instrument that gave the false positive)
for rep in $(seq 1 15); do for v in A B; do
  ./mb_O2_$v 400000 | awk '/^TOTAL/{print "'"$v"'", $2}'
done; done

# the instrument that settled it — deterministic, load-independent
for rep in $(seq 1 6); do for v in A B; do
  /usr/bin/time -l ./mb_O2_$v 400000 2>&1 \
    | awk '/instructions retired/{print "'"$v"'", $1}'
done; done
```

The candidate diff is reproducible mechanically and provably contains no
semantic edit: apply `text_.size() == len(lit) && ` in front of every
`text_ == "lit"` between `case ExpressionKind::Unary` and
`case ExpressionKind::ObservableRef` (66 sites). Reconstructing the candidate
that way reproduces the measured file byte for byte.

## Correctness gate (for the reverted candidate, run before rejecting it)

- `ctest --test-dir build --output-on-failure -j4`: **100% tests passed out of
  461**, twice, on the reverted tree.
- Trajectory identity, baseline vs candidate, same commit, both binaries built
  from one tree: 4M-step ODE, 228,000,114-byte `.gdat`,
  `sha256 54195c4806801f1700e60021691401eb6382e75db6048ce37aa4411be8b572f1` on
  both arms; `.net` `sha256 f66e0457...768942` on both; `cmp` reported no
  difference on either file.
- A first `.gdat` mismatch turned out to be **sciMetabolic's** MM
  free-substrate cancellation fix (`8dd441d`), not this change — found by
  rebuilding a true baseline at the same commit rather than trusting a binary
  built earlier. Worth repeating that check before blaming a codegen change
  for a numeric difference.
- One `architecture_nfnext_cache` failure appeared in one of five full runs
  (`cannot atomically replace NFIR cache: No such file or directory`, a
  filesystem error under `-j4`). It passed in isolation and in two subsequent
  full runs, and it is in `cpp/nfnext`, untouched here. Treated as parallel-run
  flakiness, not a regression — stated rather than hidden.

## Instrument limitations

1. **Which of my instruments is the reader, and which is a proxy.** The rule
   that earns the most from this charge is `correctness`'s: *when the question
   is what value a reader sees, the instrument must BE that reader.* They
   retracted a published comparison after realising they had applied `awk` to
   drop a field, then described the result as what a test's own unpacking sees —
   a transformation belonging to a different consumer, substituted for the
   consumer itself.

   Applying that test to my own work, honestly:

   - **The trajectory gate IS the reader.** It runs the real `bng_cpp` CLI and
     hashes the `.gdat` that CLI emits — no transformation between the question
     and the artifact. Nothing sits in the way.
   - **The microbench drives the same entry point the engine calls**,
     `Expression::evaluate(std::function, t)` — so the *call surface* is
     faithful.
   - **But it compiles `Expression.cpp` standalone** and links nothing else,
     while production links the whole engine with LTO on. That part is a proxy,
     and it is the weakest instrument here. A real microbenchmark delta would
>     not necessarily survive into the shipped binary — and in this case there
>     was not even a real microbenchmark delta to survive.

   So the fitness numbers in this document rest on a proxy and the correctness
>   gate rests on the real reader. They answer different questions, and the
>   verdict rests on neither alone: the profile and the 4.89% ceiling are
   end-to-end, while the microbench only ever located the cost.
2. Wall-clock on this host is not trustworthy below ~10%: the same binaries
   measured 5.19% apart in one session and the host has ranged 23–131 on
   loadavg. The instruction counter contradicted it, which is what settled the
   charge — but its own spread is 0.061%–0.099% of median, so its resolution
   floor is ~0.1% and it is **not** a deterministic counter.
3. The opt-level sweep is the most build-state-confounded measurement here
   (four separate compilations of the same source). Per-arm blob SHAs were
   not recorded at the time, which is the gap `sciPkPd.PkSurvey` and
   `orchSwarmB` correctly raised. The instruction-count result is not subject
   to that objection because it is a counter, not a timing.

## Where the time actually goes — and a prescription that has since gone stale

Not `Expression`. `writeOutputFiles` was the only engine frame in every
end-to-end profile. `swarmSerial` has since measured it properly: 39.5%
float→digits, 20.2% stream plumbing, 17.6% locale/grouping, 11.0% libc printf
on a 40k-row fixture. That is consistent with everything measured here.

**Do not read this as "go optimize `writeOutputFiles`."** Two reasons, both
learned after the line was first written:

1. **It is now the most contended function in the repository.** As of this
   commit `cpp/engine/OdeIntegrator.cpp` has seven lanes with declared edits —
   `writeOutputFiles`, `updateFunctions`/`derivs`, `integrateSSA`,
   `computePropensity`, `compile`, `compileGroups`, and the batch-SSA seed
   derivation. Seven touching hunks in one file is exactly the shape that
   silently reverts a fix when someone resolves a conflict by picking a side.
   The durable finding is *where the time is*; the location is now a
   poor place to aim.
2. **The win that landed there was not the shape I predicted.** `swarmSerial`
   measured a 2.75x improvement there (0.11s → 0.04s, byte-identity held across
   30 artifacts) — which vindicates the hotspot measurement — but it arrived as
   a formatting change, not the codegen-shaped one I implied. I inferred the
   *kind* of fix from the *location* of the cost without checking. That is the
   same error class as the rest of this file: evidence about where time was
   spent, dressed up as evidence about what would remove it.

The transferable form: a profile tells you **where**, and nothing about
**what kind of change** will help there. Treat "this is where the time goes"
as a pointer to investigate, never as a recommendation.
