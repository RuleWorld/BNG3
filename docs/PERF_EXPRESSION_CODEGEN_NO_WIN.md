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

- **NFsim's rate-law path is NOT covered.** `cpp/nfsim/NFcore2/legacy_bridge.cpp:112`
  and `:264` both call `evaluateWithFunctions`. I never profiled NFsim. If you
  are profiling that lane, this document tells you nothing — treat the coldness
  claim as unestablished there, not as disproven.
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

**The instruction counter settled it.** `/usr/bin/time -l … instructions retired`
is deterministic and does not move when nothing changed:

    A baseline       median 5,037,345,446   cv 0.022%
    B length-gated   median 5,038,543,790   cv 0.037%    -> +0.024%

Same binaries, same session, same wall-clock conditions — 0.03% spread instead
of 5.19%. That is a 170x tighter instrument, and it is what turned "it looked
faster" into "it is flat".

**The generalisable rule.** Measure once with a cheap instrument to find a
hypothesis, then re-measure with a *deterministic* one before believing it. If
the two disagree, the cheap one is wrong — not the code, and not your reading
of it. On this host the counters worth trusting are `instructions retired` and
`cycles elapsed` from `/usr/bin/time -l`, plus allocation counts; wall clock
needs 10%+ effects and interleaved reps to mean anything.

The second use of the counter is as a *gate* rather than a diagnostic: a
candidate whose instruction count is unchanged has not changed its cost model,
however good its disassembly looks. That check is cheap enough to run before
any timing A/B, and it would have saved this entire charge's timing work.

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

| Candidate | Change | Microbench (ns/eval, sum of 7 shapes) | Instruction count @-O2 | @-O0 | Verdict |
|---|---|---|---|---|---|
| A | baseline | 935.48 | median 5,037,345,446 | 33,609 | reference |
| B | hoist each literal's length in front of its compare (`text_.size() == N && text_ == "..."`), 66 sites | 714.89 (**-23.6%**, *retracted, see below*) | median 5,038,543,790 (**+0.024%**) | 36,618 (**+9%**) | **rejected** |
| C | B plus the `factorial` arm moved to a `[[gnu::cold]] [[gnu::noinline]]` helper (targets the 25,880-byte single function) | 792.06 (worse than B) | not measured — C was built on B, and B did not survive re-measurement | — | **rejected** |

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
per-step rate path at `OdeIntegrator.cpp:1296`
(`rxn.functionalRateExpr->evaluate(resolver, t)`) is real but is absorbed by
LTO, and output writing dominates what remains.

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

**Test gate:** `ctest --test-dir build --output-on-failure -j4` ->
`100% tests passed out of 461`, twice consecutively on the reverted tree. One
earlier run reported `99% tests passed, 1 tests failed out of 461`, with
`architecture_nfnext_cache` failing on `cannot atomically replace NFIR cache:
No such file or directory`; it then passed in isolation (`1/1 Test #455:
architecture_nfnext_cache ... Passed`) and in both later full runs.
`cpp/nfnext` is untouched by this work.

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

1. The microbenchmark compiles `Expression.cpp` **standalone** and links nothing
   else. Production links the whole engine with LTO on. A real microbenchmark
   delta would not necessarily survive into the shipped binary — and in this
   case there was not even a real microbenchmark delta.
2. Wall-clock on this host is not trustworthy below ~10%: the same binaries
   measured 5.19% apart in one session and the host has ranged 23–131 on
   loadavg. Instruction counts are the instrument that resolved this, and
   their cv here is 0.022%–0.037%.
3. The opt-level sweep is the most build-state-confounded measurement here
   (four separate compilations of the same source). Per-arm blob SHAs were
   not recorded at the time, which is the gap `sciPkPd.PkSurvey` and
   `orchSwarmB` correctly raised. The instruction-count result is not subject
   to that objection because it is a deterministic counter, not a timing.

## Where the time actually goes

Not `Expression`. `writeOutputFiles` was the only engine frame in every
end-to-end profile. `swarmSerial` has since measured it properly: 39.5%
float→digits, 20.2% stream plumbing, 17.6% locale/grouping, 11.0% libc printf
on a 40k-row fixture. That is consistent with everything measured here, and it
is where a codegen-shaped win would actually land on this platform.