# BNG3 development checklist

Operational companion to `AGENTS.md`. `AGENTS.md` states the rules; this file
says what to do with them, with a worked example from this repository for each.
Where the two disagree, **`AGENTS.md` wins** — checked when writing, no conflict
found.

Start with [`docs/VALIDATION_EVIDENCE.md`](VALIDATION_EVIDENCE.md): it records
what is currently verified, and by what. This file records how to verify it.

## 0. Hosted CI is not a signal right now

On 2026-09-29 every workflow run queued for hours without a job starting,
including for the head carrying the fixes referenced below. `ci.yml:10-14` and
`parity.yml:13-16` were changed so a later push cannot cancel an in-flight run
for the preceding head — that is the mechanism by which runs go missing. If you
need CI evidence, read the run yourself for your exact SHA; do not infer a status
from a prior head.

## Local verification that actually works

```bash
# policy / contract gates (the subset the `lint` job runs; lint also runs
# Black, Ruff, and the golden-manifest loop over provenance/golden/)
python scripts/validate_provenance.py            # the call CI makes
python scripts/validate_corpus_manifest.py
python scripts/generate_corpus_manifest.py --check
python -m tests.validation.exception_ledger --max-exceptions 1
python -m pytest tests/test_ci_contract.py -q

# the strict provenance gate, which NO job runs
python scripts/validate_provenance.py --require-approved

# C++ build and suites
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=ON \
      -DBUILD_PYTHON_BINDINGS=OFF -DBUILD_CLI=ON -DBUILD_NFSIM_CLI=OFF
cmake --build build
ctest --test-dir build --output-on-failure

# reference validation corpus (what the `validation` job runs)
python scripts/validate.py --bng-cpp build/cpp/bng_cpp --strict-references \
    --validation-manifest tests/validation/validation_manifest.json --verbose

# batch SSA CPU reference, and the Python suite
python tests/test_batch_ssa_statistical_parity.py --mode cpu
python -m pytest tests/python -q
```

Two caveats, recorded rather than hidden: the strict provenance call fails (13
errors at `6889fba`, re-run 2026-09-30, and no job runs it), and
`tests/validation/` is a *pytest* CI gate for exactly one of its test modules —
`test_parity_nfsim.py`. The lint job also runs that directory's non-test CLI
module (`python -m tests.validation.exception_ledger`, `ci.yml:68`), and the
corpus jobs import `tests/validation/compare.py` through `validate.py`
(`scripts/validate.py:28`).

**Editable-install hazard (verified 2026-09-30 at `6889fba`).** `bionetgen`
is installed as a scikit-build editable whose meta_path finder
(`_editable_skbc_bionetgen`) beats `sys.path`, so from *any* worktree
`import bionetgen` resolves to the shared main tree —
`python -c "import bionetgen; print(bionetgen.__file__)"` printed
`/Users/akutuva/Documents/BioNetGen/BNG3/python/bionetgen/__init__.py` while
standing in a sibling worktree, and `PYTHONPATH` loses to the finder. Before
quoting any Python-suite result, print the resolved path
(`UNDER TEST: <path>`), then either strip the `_editable_skbc_*` finders and
any `BioNetGen` entry from `sys.path` in favour of your worktree's `python/`,
or state in the report which tree was exercised. The compiled extension has
the same problem in snapshot form: `bionetgen._bionetgen_cpp` resolved to the
editable install's copy at
`site-packages/bionetgen/_bionetgen_cpp.cpython-314-darwin.so` (installed
2026-09-29 15:10 from the shared worktree's build, and stale relative to
`75b22a7`), not to anything this worktree built. A worktree that did not build
and install its own extension has exercised the shared snapshot's C++, not its
own.

---

## 1. Verify a claim by running it

A static audit in this session ranked a defect the worst in the tree; running it
showed the fail-closed path already held, and the proposed fix would have been a
regression.

A reviewer's finding was half right. Function-definition bodies leaking raw
hyphenated ids was measured at `6dc41b6` and does not describe `main`:
`bngl_function` pre-passes its body through `_standardize_declared_id_runs`
(`writer.py:152`, called at `writer.py:1038`), and `2370586` routed
assignment-rule bodies through the same pre-pass. The finding was real for the
commit it was measured at, and stale for the tree.

Three "validators" reported passes while testing nothing, measured with a
correct absolute `--bng-cpp`, and were deleted in `25a8a86`:
`validate_trajectories.py` — 0 passed, 0 failed, **7 skipped, exit 0**, because
its reference `.gdat` directory does not exist; `validate_io_roundtrip.py` —
0 passed, 4 failed, because it ran the same BNGL twice and diffed raw text, so
a deterministic writer defect reproduced identically in both outputs;
`validate_nfsim.py` — 0 passed, 2 failed, because it never invokes NFsim with a
model.

**Habit.** Before quoting a number, open the harness and confirm it ran the
thing it claims to run. Before accepting a finding, find the commit it was
measured at. A statistical gate's binning is part of the number: pooling
well-populated cells alongside sparse ones re-weights a chi-square and can
move a good sample's p-value by orders of magnitude, so the committed gates
pool only cells below a five-expected-count floor
(`tests/test_batch_ssa_statistical_parity.py:101-104`, convention recorded in
`docs/VALIDATION_EVIDENCE.md` §1) and a p-value is quotable only together with
its binning.

## 2. The documentation is a history, not a state

The convergence checklist says so in its own preamble: an unchecked box
"describes what was true when it was written, not necessarily what is true
now." An audit of it line by line found most open boxes stale — the
`simulateNfcore2` link error, "one canonical label for both engines", "10
pending provenance errors" (it is 13), "the eight SBML constructs are all
unlowered" (all are lowered or governed).

The old `docs/CI_PARITY.md:110-112` said the corpus jobs "are strict and must
report zero skipped fixtures" without naming a mechanism, and this checklist
then "corrected" it with a false one — that a missing oracle in the `ci.yml`
validation job is a skip. Read the code: that job passes `--strict-references`
(`ci.yml:398-400`), so a missing reference `.net` is an ERROR
(`scripts/validate.py:227-229`), and it passes no exclusion profile, so no skip
path can trigger — pinned by `tests/test_ci_contract.py:613-631`.
`BNG3_CI_STRICT_ORACLES`, set only at `parity.yml:24`, is read solely by the
pytest gates `parity.yml` runs (`tests/validation/strict.py:10-17`);
`validate.py` never reads it, and its exit code would pass a skip regardless
(`scripts/validate.py:516-517`). The outcome claim was right for reasons
nobody had written down, and the gloss that "fixed" it was wrong.
`docs/CI_PARITY.md:109-132` now records the per-workflow mechanics.

**Habit.** Read the code, not the doc. Check the SHA a claim was measured at
before treating it as current, and check that a `file:line` still points at the
thing it cited — line references in these documents drift as the code they
describe is edited.

## 3. A missing diagnostic, or a plausible wrong number, is worse than a crash

Commit `d04f648` fixed three cases where the code produced a
plausible-looking *model* instead of refusing one: a reaction with no
`kineticLaw` was given rate `1` by an environment-tunable fallback and still
produced a network; distinct SIds that `standardize_name` maps to one BNGL
spelling merged species and rewrote a reaction; a document declaring an L3
package outside the eleven the parser knew produced no diagnostic at all.
`969dedd` had the same shape — annotation namespaces cost a correct model its
numerical claim. `5ca19da` fabricated an event time: a `<ci> A-B </ci>` delay
folded to the difference `5 - 2 == 3` and the event fired at `t = 1 + 3`.

A crash is visible in a log. A model that runs and is wrong is not.

**Habit.** If the construct cannot be lowered exactly, the deliverable is an
explicit refusal with a named diagnostic — not an approximation that still
generates a network. `_is_id_hyphen` and `_extract_top_level_additive_terms` in
`writer.py` are the shape: fail closed rather than hand the caller a fragment of
an identifier. Pinned by `tests/python/test_reversible_rate_split.py`.

## 4. A commit message claim about emitted text is not a claim about behaviour

`6dc41b6` stopped raw hyphenated ids leaking into emitted rate text **in the
tokenizer and function paths only**. Its rate-law path was still wrong when it
landed and did not become correct until `57a0c82`. Both were claimed complete
before they were.

The only acceptance criterion for that class of fix is the trajectory.
`tests/python/test_reversible_rate_split.py` simulates both spellings through
`bng_cpp` and asserts the modelled amount at t=1 agrees to `abs=1e-9`, plus a
closed form against `10*exp(-0.3)`. Run by hand, both spellings give
`7.408181727464`; `A-B` gave `9.700` before the fix.

**Habit.** Do not accept a fix because the emitted text now looks right. Do not
accept a commit subject claiming a text fix closed a behaviour gap. Simulate,
and quote the number.

## 5. A half-fix is worse than no fix — revert and report

The same series is the worked example: `6dc41b6` closed two of three paths and
shipped as complete; `5ca19da` and `57a0c82` are where the rate-law path and
the trajectory actually landed. Landing the partial change left the tree in a
state where the defect was harder to see, not easier.

The discipline also shows in what was *not* faked. `75b22a7` removed the
seed-state-order divergence and leaves
`_KNOWN_SEED_STATE_ORDER_DIVERGENCES` **empty** because the divergence is gone —
and the test fails in both directions, so a marker that stops being needed is
itself an error. Separately, a candidate prefilter measured inside run variation
was **reverted**, with the pre-existing scan left in production.

**Habit.** If you cannot finish a fix you have started, revert it and report
what you learned. Do not leave a partial change that reads as a fix, and do not
quietly drop a check to make something pass.

## 6. Do not `git add -A` while others are working in the tree

Several worktrees are active against this repository and subagents edit the same
working tree concurrently. `AGENTS.md:84` ("Never overwrite unrelated worktree
changes") and `AGENTS.md:341` ("Preserve unrelated changes") are the policy; the
operational form is: stage explicit paths only.

**Habit.** `git status --short` and `git diff` before staging, then
`git add <specific paths>`. Never `git add -A` — a blanket add will stage a
sibling's half-finished file and commit it under your message. This happened
once here: a fix landed in one commit with its regression test left behind, so
`main` briefly carried an unverified change with no coverage.

## 7. Do not apply a fix that does not reproduce

`python/bionetgen/atomizer/modern/events.py` still builds its value-resolution
set with a narrow identifier scan inside the AST-guarded delay folder. It runs
after the hyphen guard so it cannot corrupt a rewritten expression, but a
surviving `A-B` would be resolved there as two symbols. Whether that produces a
wrong value or only a refusal is **unmeasured**, so it is listed in
`docs/VALIDATION_EVIDENCE.md` §2 and not fixed.

The `A B` case is the same shape: a `<ci>` body that is not an id at all,
ambiguous only with multiplication, and no spelling test disambiguates it.
Widening the identifier class would reintroduce the `6dc41b6` defect.

**Habit.** Reproduce first, then fix (`AGENTS.md:143`). If you cannot produce the
reproducer, the item belongs in `docs/VALIDATION_EVIDENCE.md` §2 with the
command that would settle it — not in a diff.

---

## Summary

| Rule | Costs you | Where it bit |
|---|---|---|
| Run the claim | a regression | an audit ranked a non-reproducing defect first |
| Read code, not docs | re-raising stale work | the convergence checklist, `CI_PARITY.md` |
| Refuse loudly | a model that is quietly wrong | `d04f648`, `969dedd`, `5ca19da` |
| Trajectory, not text | a different trajectory shipping | `6dc41b6` vs `57a0c82` |
| Revert a half-fix | a hidden partial change | `6dc41b6` → `57a0c82` |
| Explicit `git add` | committing a sibling's file | `AGENTS.md:84,341` |
| Reproduce before fixing | an unfixable "fix" | the guarded delay folder |
